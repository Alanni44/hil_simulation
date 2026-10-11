"""Run the second 3.3 simulator chain through virtual Ethernet to 3.6.

The scenario source remains the frozen W3 waveform and is sent by the original
Scapy ETHGEN source.  A local user-space Ethernet relay is used only because
this development acceptance has no physical NIC; it preserves the Scapy-built
L2/IP/UDP frame and feeds its UDP bytes into the standard 3.6 gateway.
Without ``--model-endpoint`` this remains the original E1 reception check.
With an explicit local C runtime endpoint it requires ID10 APPLIED evidence
and generated-model readback; physical Ethernet remains unqualified.
"""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import select
import socket
import sys
import threading
import time

from scapy.layers.inet import UDP
from scapy.layers.l2 import Ether
from scapy.supersocket import SimpleSocket


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.model_bindings import ModelBindings
from icd_gateway.model_consumer import EnvironmentModelConsumerService, QuadrotorEnvironmentBridge
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.udp import UDPGateway
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from input_simulator.replay_export import ExportBinding
from input_simulator.scapy_source import ScapySource
from input_simulator.send_run import SendPlan, SendRun
from input_simulator.session import SourceSession
from input_simulator.tools import ChannelReservations


DEFAULT_BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
DEFAULT_INTERFACE = "scenario-veth0"
SOURCE_MAC = "02:00:00:00:00:01"
DESTINATION_MAC = "02:00:00:00:00:02"


def _reserve_udp_endpoint():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()
    finally:
        probe.close()


def _endpoint(text):
    if type(text) is not str or text.count(":") != 1:
        raise ICDError("SCHEMA", "model endpoint must be HOST:PORT")
    host, port = text.rsplit(":", 1)
    try:
        port = int(port)
    except ValueError as error:
        raise ICDError("SCHEMA", "model endpoint port must be an integer") from error
    if not host or not 1 <= port <= 65535:
        raise ICDError("SCHEMA", "model endpoint is outside the UDP port range")
    return host, port


def _load_inputs(root, contract_dir):
    definition = json.loads((root / "config" / "generated-input-reception.json").read_text(encoding="utf-8"))
    inputs = definition["source_inputs"]
    resources = {}
    resolved_root = contract_dir.resolve()
    for reference in inputs["protocol"]["resources"]:
        resource = (resolved_root / reference["file_name"]).resolve(strict=True)
        if resource.parent != resolved_root:
            raise ICDError("RESOURCE", "protocol resource escapes its frozen directory")
        resources[reference["resource_id"]] = resource.read_bytes()
    fixtures = json.loads((resolved_root / "input-simulator-v0.3.examples.json").read_bytes())["fixtures"]
    messages = {item["value"]["message_id"]: item["value"] for item in fixtures}
    return inputs, resources, messages


def _write(output, value):
    output.write(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
    output.flush()


def run(contract_dir, expected_sha256, output_path, *, model_endpoint=None, model_contract_path=None):
    contract_dir = Path(contract_dir).resolve(strict=True)
    output_path = Path(output_path)
    contract = Contract.load(contract_dir, expected_sha256=expected_sha256)
    inputs, resources, messages = _load_inputs(ROOT, contract_dir)
    plan = SendPlan.scenario(contract, inputs, resources, model_id="quadrotor_hil")
    if {action.link_id for action in plan.actions} != {"ETHGEN"}:
        raise ICDError("STATE", "scenario software acceptance requires only the frozen ETHGEN events")

    receiver_endpoint = _reserve_udp_endpoint()
    stop = threading.Event()
    errors = []
    captured_frames = []
    records = ()
    model_application = model_endpoint is not None
    with ExitStack() as stack:
        output = stack.enter_context(output_path.open("x", encoding="utf-8"))
        left, relay = socket.socketpair()
        stack.callback(relay.close)
        l2socket = SimpleSocket(left, Ether)
        reservations = ChannelReservations()
        token = reservations.reserve("scenario-demo", "ETHGEN", (DEFAULT_INTERFACE,), mode="SEND")
        stack.callback(reservations.release, token)
        transport = ScapySource(contract, source_bind=("127.0.0.1", 0), feedback_bind=("127.0.0.1", 0),
                                receiver_endpoint=receiver_endpoint,
                                binding=ExportBinding("ETH_0", DEFAULT_INTERFACE, SOURCE_MAC, DESTINATION_MAC),
                                reservations=reservations, reservation=token, l2socket=l2socket)
        stack.callback(transport.close)
        udp_binding = PeerBinding("ETH_0", "UDP", "{}:{}".format(*transport.source_endpoint))
        identity = messages[1]["payload"]["identity"]
        registry = SessionRegistry(contract, (SourceGrant(identity, ("STIMULUS",), (udp_binding,)),))
        reception = None
        consumer = None
        bridge = None
        target_step_base = 0
        if model_application:
            if model_contract_path is None:
                raise ICDError("SCHEMA", "actual model contract path is required for model application")
            model_contract_path = Path(model_contract_path).resolve(strict=True)
            bindings = ModelBindings(contract, "quadrotor_hil",
                                     json.loads(model_contract_path.read_text(encoding="utf-8")))
            bridge = QuadrotorEnvironmentBridge(_endpoint(model_endpoint))
            consumer = EnvironmentModelConsumerService(contract, registry, bindings, bridge,
                                                       clock=time.monotonic_ns)
            receiver = Receiver(contract, registry, model_consumer_service=consumer)
        else:
            reception = ReceptionService(contract, registry, (10,))
            receiver = Receiver(contract, registry, reception_service=reception)
        gateway = UDPGateway(receiver, bind=receiver_endpoint,
                             feedback_routes={udp_binding: transport.feedback_endpoint}, channel="ETH_0")
        stack.callback(gateway.close)
        session = SourceSession(transport, identity, ("STIMULUS",), max_records=4096)
        stack.callback(session.close)

        def serve():
            buffer = b""
            try:
                while not stop.is_set():
                    readable, _, _ = select.select((relay,), (), (), 0.001)
                    if readable:
                        block = relay.recv(65536)
                        if not block:
                            raise ICDError("RESOURCE", "virtual Ethernet relay closed during transmission")
                        buffer += block
                        while len(buffer) >= 18:
                            frame_size = 14 + int.from_bytes(buffer[16:18], "big")
                            if len(buffer) < frame_size:
                                break
                            frame = Ether(buffer[:frame_size])
                            buffer = buffer[frame_size:]
                            if UDP not in frame:
                                raise ICDError("SCHEMA", "Scapy source emitted a non-UDP virtual Ethernet frame")
                            captured_frames.append(bytes(frame))
                            transport.socket.sendto(bytes(frame[UDP].payload), receiver_endpoint)
                    gateway.poll(timeout=0.001)
            except Exception as error:
                if not stop.is_set():
                    errors.append(error)

        thread = threading.Thread(target=serve, name="scenario-reception-demo", daemon=True)
        thread.start()
        try:
            if model_application:
                # Opening may consume measurable wall time.  Bind the frozen
                # relative waveform to the current C step only afterwards.
                session.open()
                target_step_base = bridge.current_step() + 50
            _write(output, {"format": "HIL_SCENARIO_CHAIN_1", "status": "STARTED", "source": "SCENARIO",
                            "transport": "ETHERNET_VIRTUAL", "sample_count": len(plan.actions),
                            "baseline_sha256": contract.baseline_sha256,
                            "validation_scope": "MODEL_BOUNDARY_READBACK" if model_application else "WIRE_SCHEMA_SESSION_ONLY",
                            "model_application_verified": model_application,
                            "physical_tool_qualification": "NOT_EVALUATED", "replacement_ready": False})
            records = SendRun(plan, session, terminal_stage="APPLIED" if model_application else "VALIDATED",
                              terminal_probe_id=1010 if model_application else 0,
                              target_step_base=target_step_base).run(
                                  on_record=lambda record: _write(output, record.document()))
            deadline = time.monotonic() + 1.0
            while ((len(consumer.records) if model_application else len(reception.records)) != len(records)
                   and time.monotonic() < deadline and not errors):
                time.sleep(0.001)
            if errors:
                raise ICDError("RESOURCE", "virtual Ethernet receiver loop failed") from errors[0]
            terminal_records = consumer.records if model_application else reception.records
            if len(terminal_records) != len(records) or len(captured_frames) < len(records):
                raise ICDError("STATE", "all scenario samples require Scapy frames and terminal receiver evidence")
            if model_application:
                for record in consumer.records:
                    _write(output, {"format": "HIL_SCENARIO_MODEL_APPLIED_1",
                                    "request": json.loads(record.request_json),
                                    "readback": json.loads(record.readback_json),
                                    "received_ns": str(record.received_ns), "completed_ns": str(record.completed_ns),
                                    "applied_step": record.applied_step, "model_revision": record.model_revision,
                                    "model_application_verified": True})
            else:
                for record in reception.records:
                    _write(output, record.document())
            _write(output, {"format": "HIL_SCENARIO_CHAIN_1",
                            "status": "MODEL_APPLIED" if model_application else "RECEPTION_VALIDATED",
                            "generated_samples": len(records), "scapy_l2_frames": len(captured_frames),
                            "decoded_samples": len(terminal_records), "model_application_verified": model_application,
                            "physical_tool_qualification": "NOT_EVALUATED", "replacement_ready": False})
        finally:
            stop.set()
            thread.join(timeout=2)
            if thread.is_alive():
                raise ICDError("STATE", "virtual Ethernet receiver loop did not stop")
        if errors:
            raise ICDError("RESOURCE", "virtual Ethernet receiver loop failed") from errors[0]
    return {"status": "MODEL_APPLIED" if model_application else "RECEPTION_VALIDATED", "generated_samples": len(records),
            "decoded_samples": len(records), "output": str(output_path.resolve()),
            "model_application_verified": model_application, "physical_tool_qualification": "NOT_EVALUATED",
            "replacement_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", type=Path, default=Path("docs/interfaces/baseline"))
    parser.add_argument("--expected-sha256", default=DEFAULT_BASELINE_SHA256)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-endpoint", help="explicit local C runtime UDP endpoint, HOST:PORT")
    parser.add_argument("--model-contract", type=Path,
                        help="generated hil_contract.json for --model-endpoint")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.contract_dir, args.expected_sha256, args.output,
                             model_endpoint=args.model_endpoint,
                             model_contract_path=args.model_contract), ensure_ascii=True), flush=True)
        return 0
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                          "detail": str(error), "model_application_verified": False,
                          "replacement_ready": False}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
