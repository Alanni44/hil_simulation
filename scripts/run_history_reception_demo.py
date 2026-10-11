"""Run the third HISTORY replay chain through virtual UDP ingress to 3.6.

The runner creates the frozen reference PCAP, parses it through the production
HISTORY/ReplayProcessor path, allocates a current standard session header and
sends the exact prepared UDP datagram to the standard 3.6 Receiver.  The
default remains reception-only.  An explicit local C endpoint plus generated
contract enables an ID7 model-boundary check; tcpreplay and raw-NIC
qualification remain explicitly pending.
"""

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import socket
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.model_bindings import ModelBindings
from icd_gateway.model_consumer import FlightModelConsumerService, QuadrotorEnvironmentBridge
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.udp import UDPGateway
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.wire import Header
from input_simulator.history import CaptureBinding
from input_simulator.reference_pcap import (CHANNEL_ID, MESSAGE_ID, MODEL_ID, build_reference_pcap,
                                            reference_history_definition, validate_reference_pcap)
from input_simulator.replay import ReplayDestination, ReplayHeader, ReplayProcessor
from input_simulator.session import SourceSession
from input_simulator.udp_source import UDPSource


DEFAULT_BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
MODEL_TARGET_LEAD_STEPS = 90


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


def _identity(contract_dir):
    fixtures = json.loads((contract_dir / "input-simulator-v0.3.examples.json").read_bytes())["fixtures"]
    messages = {item["value"]["message_id"]: item["value"] for item in fixtures}
    return messages[1]["payload"]["identity"]


def _write(output, value):
    output.write(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
    output.flush()


def run(contract_dir, expected_sha256, output_path, *, model_endpoint=None, model_contract_path=None):
    contract_dir = Path(contract_dir).resolve(strict=True)
    output_path = Path(output_path)
    contract = Contract.load(contract_dir, expected_sha256=expected_sha256)
    raw_pcap = build_reference_pcap(contract)
    manifest, validation = validate_reference_pcap(contract, raw_pcap)
    history = reference_history_definition(raw_pcap)
    # These are the reference PCAP's frozen capture-domain identifiers.  They
    # describe its provenance; they do not identify the local UDP test socket.
    binding = CaptureBinding("reference-eth0", CHANNEL_ID, "PCAP:0:0", "interface-0", "clock-0")
    receiver_endpoint = _reserve_udp_endpoint()
    stop = threading.Event()
    errors = []
    model_application = model_endpoint is not None
    with ExitStack() as stack:
        output = stack.enter_context(output_path.open("x", encoding="utf-8"))
        transport = UDPSource(contract, source_bind=("127.0.0.1", 0), feedback_bind=("127.0.0.1", 0),
                              receiver_endpoint=receiver_endpoint, channel="ETH_0")
        stack.callback(transport.close)
        udp_binding = PeerBinding("ETH_0", "UDP", "{}:{}".format(*transport.source_endpoint))
        identity = _identity(contract_dir)
        required_role = contract.entry(MESSAGE_ID)["role"]
        roles = ("STIMULUS",) if required_role == "ANY_SESSION_ROLE" else (required_role,)
        registry = SessionRegistry(contract, (SourceGrant(identity, roles, (udp_binding,)),))
        reception = None
        consumer = None
        bridge = None
        if model_application:
            if model_contract_path is None:
                raise ICDError("SCHEMA", "actual model contract path is required for model application")
            model_contract_path = Path(model_contract_path).resolve(strict=True)
            bindings = ModelBindings(contract, MODEL_ID,
                                     json.loads(model_contract_path.read_text(encoding="utf-8")))
            bridge = QuadrotorEnvironmentBridge(_endpoint(model_endpoint))
            consumer = FlightModelConsumerService(contract, registry, bindings, bridge,
                                                   clock=time.monotonic_ns)
            receiver = Receiver(contract, registry, model_consumer_service=consumer)
        else:
            reception = ReceptionService(contract, registry, (MESSAGE_ID,))
            receiver = Receiver(contract, registry, reception_service=reception)
        gateway = UDPGateway(receiver, bind=receiver_endpoint,
                             feedback_routes={udp_binding: transport.feedback_endpoint}, channel="ETH_0")
        stack.callback(gateway.close)
        session = SourceSession(transport, identity, roles, max_records=4096)
        stack.callback(session.close)

        def serve():
            try:
                while not stop.is_set():
                    gateway.poll(timeout=0.001)
            except Exception as error:
                if not stop.is_set():
                    errors.append(error)

        thread = threading.Thread(target=serve, name="history-reception-demo", daemon=True)
        thread.start()
        try:
            _write(output, {"format": "HIL_HISTORY_CHAIN_1", "status": "STARTED", "source": "HISTORY",
                            "transport": "PCAP_REPLAY_VIRTUAL", "message_id": MESSAGE_ID,
                            "pcap_sha256": hashlib.sha256(raw_pcap).hexdigest(),
                            "validation_scope": "MODEL_BOUNDARY_READBACK" if model_application else "WIRE_SCHEMA_SESSION_ONLY",
                            "model_application_verified": model_application,
                            "tcpreplay_qualification": "NOT_EVALUATED", "replacement_ready": False})
            session.open()
            decoded = ReplayProcessor(contract).decoder.decode(raw_pcap, history, (binding,), model_id=MODEL_ID,
                                                               declared_ids=(MESSAGE_ID,))
            stimulus = decoded.records[0].stimulus
            # The local C runtime advances at 10 kHz.  This lead leaves room
            # for ingress after the step probe, while keeping the boundary
            # near enough for the frozen 100 ms ID7 validity interval even on
            # a non-RT developer host.
            target_step = (bridge.current_step() + MODEL_TARGET_LEAD_STEPS
                           if model_application else 200)
            item = session.prepare_input(stimulus, "UDP", target_step=target_step)
            replay_header = Header(**item.message["header"])
            prepared = ReplayProcessor(contract).prepare(
                raw_pcap, history, (binding,), model_id=MODEL_ID, declared_ids=(MESSAGE_ID,),
                headers=(ReplayHeader(0, replay_header),),
                destinations=(ReplayDestination("ETH_0", "ETH_0", transport.source_endpoint, receiver_endpoint),))
            if len(prepared.packets) != 1 or prepared.packets[0].wire_data != item.frames[0]:
                raise ICDError("STATE", "prepared HISTORY datagram must equal the current-session source datagram")
            request = item.message
            replies = []
            with session._operation():
                session._verify_input(item)
                session._claim_first_attempt(request)
                transport.send(request, owner=session)
                for _ in range(2):
                    reply = transport.receive_for(request, timeout=0.5, owner=session)
                    session._check_reply(request, reply, session._now(), session._now())
                    replies.append(reply)
            session.discard_input(item)
            required_terminal = "APPLIED" if model_application else "VALIDATED"
            required_probe = 1007 if model_application else 0
            if ([(reply["payload"]["stage"], reply["payload"]["error"]) for reply in replies]
                    != [("RECEIVED", "OK"), (required_terminal, "OK")]
                    or replies[-1]["payload"]["probe_id"] != required_probe
                    or model_application and replies[-1]["payload"]["applied_step"] != target_step):
                raise ICDError("STATE", "HISTORY replay requires correlated terminal model evidence")
            deadline = time.monotonic() + 1.0
            while ((len(consumer.records) if model_application else len(reception.records)) != 1
                   and time.monotonic() < deadline and not errors):
                time.sleep(0.001)
            if errors:
                raise ICDError("RESOURCE", "HISTORY virtual receiver loop failed") from errors[0]
            terminal_records = consumer.records if model_application else reception.records
            if len(terminal_records) != 1:
                raise ICDError("STATE", "prepared HISTORY datagram has no terminal 3.6 evidence")
            _write(output, {"format": "HIL_HISTORY_REPLAY_1", "history_decoder": "HistoryDecoder",
                            "replay_processor": "ReplayProcessor", "prepared_packets": len(prepared.packets),
                            "prepared_execution_ready": prepared.execution_ready,
                            "prepared_wire_sha256": hashlib.sha256(prepared.packets[0].wire_data).hexdigest(),
                            "source_wire_sha256": hashlib.sha256(item.frames[0]).hexdigest(),
                            "feedback": replies, "reference_validation_status": validation["status"],
                            "model_application_verified": model_application,
                            "tcpreplay_qualification": "NOT_EVALUATED"})
            if model_application:
                record = consumer.records[0]
                _write(output, {"format": "HIL_HISTORY_MODEL_APPLIED_1",
                                "request": json.loads(record.request_json),
                                "readback": json.loads(record.readback_json),
                                "received_ns": str(record.received_ns), "completed_ns": str(record.completed_ns),
                                "applied_step": record.applied_step, "model_revision": record.model_revision,
                                "model_application_verified": True})
            else:
                _write(output, reception.records[0].document())
            _write(output, {"format": "HIL_HISTORY_CHAIN_1",
                            "status": "MODEL_APPLIED" if model_application else "RECEPTION_VALIDATED",
                            "generated_samples": 1, "decoded_samples": 1,
                            "model_application_verified": model_application,
                            "tcpreplay_qualification": "NOT_EVALUATED", "replacement_ready": False})
        finally:
            stop.set()
            thread.join(timeout=2)
            if thread.is_alive():
                raise ICDError("STATE", "HISTORY virtual receiver loop did not stop")
        if errors:
            raise ICDError("RESOURCE", "HISTORY virtual receiver loop failed") from errors[0]
    return {"status": "MODEL_APPLIED" if model_application else "RECEPTION_VALIDATED",
            "generated_samples": 1, "decoded_samples": 1,
            "output": str(output_path.resolve()), "model_application_verified": model_application,
            "tcpreplay_qualification": "NOT_EVALUATED", "replacement_ready": False}


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
