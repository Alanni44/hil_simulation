"""One-shot standard business-message sender; not a three-source executor."""

import argparse
import json
from pathlib import Path

from icd_runtime.contract import Contract
from icd_runtime.errors import ICDError
from icd_runtime.json_codec import loads
from icd_gateway.config import parse_endpoint
from .udp_source import UDPSource


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract-dir", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--source-bind", required=True)
    parser.add_argument("--feedback-bind", required=True)
    parser.add_argument("--receiver", required=True)
    parser.add_argument("--channel", default="ETH_0")
    parser.add_argument("--message-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        contract = Contract.load(args.contract_dir, expected_sha256=args.expected_sha256)
        with args.message_file.open("rb") as source:
            raw = source.read(131073)
        if len(raw) > 131072:
            raise ICDError("CAPACITY", "message file exceeds bounded sender input")
        message = loads(raw)
        with UDPSource(contract, source_bind=parse_endpoint(args.source_bind),
                       feedback_bind=parse_endpoint(args.feedback_bind), receiver_endpoint=parse_endpoint(args.receiver),
                       channel=args.channel) as source:
            feedback = source.request(message)
        failed = (feedback["message_id"] == 130 and feedback["payload"]["stage"] == "FAILED"
                  or feedback["message_id"] == 141 and feedback["payload"]["error"] != "OK")
        print(json.dumps({"status": "BUSINESS_FAILED" if failed else "NETWORK_EXCHANGE_COMPLETE",
                          "feedback": feedback, "model_hardware_replacement": "NOT_EXECUTED"}))
        return 1 if failed else 0
    except (ICDError, OSError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "STATE",
                          "detail": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
