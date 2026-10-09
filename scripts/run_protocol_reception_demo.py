"""Run the first 3.3 simulator chain through a virtual CANFD 3.6 receiver.

This is a development-only, software-only acceptance runner.  It exercises the
frozen PROTOCOL resource, the original CANT/python-can sender, CAN ingress and
the standard 3.6 reception service.  Reception evidence is deliberately E1
only: no model writer, application probe or physical-bus qualification is
installed here.
"""

import argparse
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import socket
import sys
import threading
import time
import uuid

import can


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_gateway.can_ingress import CANGateway
from icd_gateway.receiver import Receiver
from icd_gateway.reception_service import ReceptionService
from icd_gateway.session import PeerBinding, SessionRegistry, SourceGrant
from icd_gateway.udp import UDPGateway
from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from input_simulator.can_signal import CANSignalSender
from input_simulator.live_tool_input import LiveToolInputBuilder
from input_simulator.protocol import ProtocolParser
from input_simulator.replay_export import ExportBinding
from input_simulator.send_run import SendPlan, SendRun
from input_simulator.session import SourceSession
from input_simulator.tools import ChannelReservations
from input_simulator.udp_source import UDPSource


DEFAULT_BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
DEFAULT_MESSAGE_ID = 10
DEFAULT_INTERFACE = "protocol-vcan0"


def _reserve_udp_endpoint():
    """Reserve a local endpoint long enough to select a distinct receiver role."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()
    finally:
        probe.close()


def _load_protocol_inputs(root, contract_dir):
    definition = json.loads((root / "config" / "generated-input-reception.json").read_text(encoding="utf-8"))
    inputs = definition["source_inputs"]
    resources = {}
    for reference in inputs["protocol"]["resources"]:
        resource = (contract_dir / reference["file_name"]).resolve(strict=True)
        if resource.parent != contract_dir.resolve():
            raise ICDError("RESOURCE", "protocol resource escapes its frozen directory")
        resources[reference["resource_id"]] = resource.read_bytes()
    fixtures = json.loads((contract_dir / "input-simulator-v0.3.examples.json").read_bytes())["fixtures"]
    messages = {item["value"]["message_id"]: item["value"] for item in fixtures}
    return inputs, resources, messages


def _write(output, value):
    output.write(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
    output.flush()


def run(contract_dir, expected_sha256, output_path, *, count=3, period_steps=80,
        model_id="quadrotor_hil", message_ids=(DEFAULT_MESSAGE_ID,)):
    """Generate PROTOCOL data and retain exactly one software-chain evidence file."""
    if type(count) is not int or not 1 <= count <= 64:
        raise ICDError("RANGE", "protocol demo count must be an integer in 1..64")
    if type(period_steps) is not int or not 1 <= period_steps <= 0xffffffff:
        raise ICDError("RANGE", "protocol demo period must be a positive uint32 step count")
    if (type(model_id) is not str or type(message_ids) is not tuple or not message_ids
            or any(type(mid) is not int for mid in message_ids) or len(set(message_ids)) != len(message_ids)):
        raise ICDError("SCHEMA", "explicit model and distinct protocol message IDs are required")
    contract_dir = Path(contract_dir).resolve(strict=True)
    output_path = Path(output_path)
    contract = Contract.load(contract_dir, expected_sha256=expected_sha256)
    inputs, resources, messages = _load_protocol_inputs(ROOT, contract_dir)
    stimuli = []
    roles = set()
    for mid in message_ids:
        entry = contract.entry(mid)
        if mid not in messages or model_id not in entry["model_ids"]:
            raise ICDError("MODEL", "protocol message fixture is not applicable to the requested model")
        if entry["role"] != "ANY_SESSION_ROLE":
            roles.add(entry["role"])
        stimuli.append({"message_id": mid, "payload": messages[mid]["payload"]})
    roles = tuple(role for role in ("STIMULUS", "CONTROLLER", "OBSERVER") if role in roles) or ("STIMULUS",)
    plan = SendPlan.protocol(contract, inputs, resources, model_id=model_id, stimuli=stimuli,
                             count=count, period_steps=period_steps, first_step=0)

    receiver_endpoint = _reserve_udp_endpoint()
    channel_id = uuid.uuid4().hex
    stop = threading.Event()
    errors = []
    records = ()
    with ExitStack() as stack:
        output = stack.enter_context(output_path.open("x", encoding="utf-8"))
        transport = UDPSource(contract, source_bind=("127.0.0.1", 0), feedback_bind=("127.0.0.1", 0),
                              receiver_endpoint=receiver_endpoint, channel="ETH_0")
        stack.callback(transport.close)
        udp_binding = PeerBinding("ETH_0", "UDP", "{}:{}".format(*transport.source_endpoint))
        can_binding = PeerBinding("CANFD_0", "CANFD", DEFAULT_INTERFACE)
        identity = copy.deepcopy(messages[1]["payload"]["identity"])
        identity["model_id"] = model_id
        registry = SessionRegistry(contract, (SourceGrant(identity, roles, (udp_binding, can_binding)),))
        reception = ReceptionService(contract, registry, tuple(message_ids))
        receiver = Receiver(contract, registry, reception_service=reception)
        gateway = UDPGateway(receiver, bind=receiver_endpoint,
                             feedback_routes={udp_binding: transport.feedback_endpoint}, channel="ETH_0")
        stack.callback(gateway.close)
        tx_bus = can.Bus(interface="virtual", channel=channel_id, ignore_config=True)
        rx_bus = can.Bus(interface="virtual", channel=channel_id, ignore_config=True)
        stack.callback(tx_bus.shutdown)
        can_gateway = CANGateway(receiver, channel="CANFD_0", interface=DEFAULT_INTERFACE, bus=rx_bus)
        stack.callback(can_gateway.close)
        reservations = ChannelReservations()
        token = reservations.reserve("protocol-demo", "CANT", (DEFAULT_INTERFACE,), mode="SEND")
        stack.callback(reservations.release, token)
        session = SourceSession(transport, identity, roles, max_records=4096)
        stack.callback(session.close)
        parser = ProtocolParser(contract)
        parser.parse(inputs["protocol"], resources)
        sender = CANSignalSender(LiveToolInputBuilder(reservations, session, protocol=parser), token,
                                 ExportBinding("CANFD_0", DEFAULT_INTERFACE), bus=tx_bus)
        stack.callback(sender.close)

        def serve():
            try:
                while not stop.is_set():
                    gateway.poll(timeout=0.001)
                    can_gateway.poll(timeout=0)
            except Exception as error:  # Surface infrastructure failures to the caller.
                errors.append(error)

        thread = threading.Thread(target=serve, name="protocol-reception-demo", daemon=True)
        thread.start()
        try:
            _write(output, {"format": "HIL_PROTOCOL_CHAIN_1", "status": "STARTED",
                            "source": "PROTOCOL", "transport": "CANFD_VIRTUAL", "model_id": model_id,
                            "message_ids": list(message_ids), "sample_count": len(plan.actions),
                            "baseline_sha256": contract.baseline_sha256,
                            "validation_scope": "WIRE_SCHEMA_SESSION_ONLY", "model_application_verified": False,
                            "physical_tool_qualification": "NOT_EVALUATED", "replacement_ready": False})
            records = SendRun(plan, session, can_sender=sender).run(
                on_record=lambda record: _write(output, record.document()))
            deadline = time.monotonic() + 1.0
            while len(reception.records) != len(records) and time.monotonic() < deadline and not errors:
                time.sleep(0.001)
            if errors:
                raise ICDError("RESOURCE", "software receiver loop failed") from errors[0]
            if len(reception.records) != len(records):
                raise ICDError("STATE", "all transmitted protocol samples must be decoded before completion")
            for record in reception.records:
                _write(output, record.document())
            _write(output, {"format": "HIL_PROTOCOL_CHAIN_1", "status": "RECEPTION_VALIDATED",
                            "model_id": model_id, "message_ids": list(message_ids),
                            "generated_samples": len(records), "decoded_samples": len(reception.records),
                            "model_application_verified": False, "physical_tool_qualification": "NOT_EVALUATED",
                            "replacement_ready": False})
        finally:
            stop.set()
            thread.join(timeout=2)
            if thread.is_alive():
                raise ICDError("STATE", "software receiver loop did not stop")
        if errors:
            raise ICDError("RESOURCE", "software receiver loop failed") from errors[0]
    return {"status": "RECEPTION_VALIDATED", "model_id": model_id, "message_ids": list(message_ids),
            "generated_samples": len(records),
            "decoded_samples": len(records), "output": str(output_path.resolve()),
            "model_application_verified": False, "physical_tool_qualification": "NOT_EVALUATED",
            "replacement_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", type=Path, default=Path("docs/interfaces/baseline"))
    parser.add_argument("--expected-sha256", default=DEFAULT_BASELINE_SHA256)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--period-steps", type=int, default=80)
    parser.add_argument("--model-id", default="quadrotor_hil")
    parser.add_argument("--message-id", type=int, action="append")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.contract_dir, args.expected_sha256, args.output,
                             count=args.count, period_steps=args.period_steps, model_id=args.model_id,
                             message_ids=tuple(args.message_id or (DEFAULT_MESSAGE_ID,))), ensure_ascii=True), flush=True)
        return 0
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                          "detail": str(error), "model_application_verified": False,
                          "replacement_ready": False}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
