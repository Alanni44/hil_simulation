"""Run the third HISTORY replay chain through virtual UDP ingress to 3.6.

The runner creates the frozen reference PCAP, parses it through the production
HISTORY/ReplayProcessor path, allocates a current standard session header and
sends the exact prepared UDP datagram to the standard 3.6 Receiver.  It does
not invoke tcpreplay, a raw NIC or a model consumer; those qualifications stay
explicitly pending.
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


def _reserve_udp_endpoint():
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()
    finally:
        probe.close()


def _identity(contract_dir):
    fixtures = json.loads((contract_dir / "input-simulator-v0.3.examples.json").read_bytes())["fixtures"]
    messages = {item["value"]["message_id"]: item["value"] for item in fixtures}
    return messages[1]["payload"]["identity"]


def _write(output, value):
    output.write(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n")
    output.flush()


def run(contract_dir, expected_sha256, output_path):
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
                            "validation_scope": "WIRE_SCHEMA_SESSION_ONLY", "model_application_verified": False,
                            "tcpreplay_qualification": "NOT_EVALUATED", "replacement_ready": False})
            session.open()
            decoded = ReplayProcessor(contract).decoder.decode(raw_pcap, history, (binding,), model_id=MODEL_ID,
                                                               declared_ids=(MESSAGE_ID,))
            stimulus = decoded.records[0].stimulus
            item = session.prepare_input(stimulus, "UDP", target_step=200)
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
            if [(reply["payload"]["stage"], reply["payload"]["error"]) for reply in replies] != [("RECEIVED", "OK"), ("VALIDATED", "OK")]:
                raise ICDError("STATE", "HISTORY replay requires correlated reception-only feedback")
            deadline = time.monotonic() + 1.0
            while len(reception.records) != 1 and time.monotonic() < deadline and not errors:
                time.sleep(0.001)
            if errors:
                raise ICDError("RESOURCE", "HISTORY virtual receiver loop failed") from errors[0]
            if len(reception.records) != 1:
                raise ICDError("STATE", "prepared HISTORY datagram was not decoded by 3.6 reception service")
            _write(output, {"format": "HIL_HISTORY_REPLAY_1", "history_decoder": "HistoryDecoder",
                            "replay_processor": "ReplayProcessor", "prepared_packets": len(prepared.packets),
                            "prepared_execution_ready": prepared.execution_ready,
                            "prepared_wire_sha256": hashlib.sha256(prepared.packets[0].wire_data).hexdigest(),
                            "source_wire_sha256": hashlib.sha256(item.frames[0]).hexdigest(),
                            "feedback": replies, "reference_validation_status": validation["status"],
                            "model_application_verified": False, "tcpreplay_qualification": "NOT_EVALUATED"})
            _write(output, reception.records[0].document())
            _write(output, {"format": "HIL_HISTORY_CHAIN_1", "status": "RECEPTION_VALIDATED",
                            "generated_samples": 1, "decoded_samples": 1, "model_application_verified": False,
                            "tcpreplay_qualification": "NOT_EVALUATED", "replacement_ready": False})
        finally:
            stop.set()
            thread.join(timeout=2)
            if thread.is_alive():
                raise ICDError("STATE", "HISTORY virtual receiver loop did not stop")
        if errors:
            raise ICDError("RESOURCE", "HISTORY virtual receiver loop failed") from errors[0]
    return {"status": "RECEPTION_VALIDATED", "generated_samples": 1, "decoded_samples": 1,
            "output": str(output_path.resolve()), "model_application_verified": False,
            "tcpreplay_qualification": "NOT_EVALUATED", "replacement_ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", type=Path, default=Path("docs/interfaces/baseline"))
    parser.add_argument("--expected-sha256", default=DEFAULT_BASELINE_SHA256)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.contract_dir, args.expected_sha256, args.output), ensure_ascii=True), flush=True)
        return 0
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                          "detail": str(error), "model_application_verified": False,
                          "replacement_ready": False}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
