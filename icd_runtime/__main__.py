import argparse
import json
from pathlib import Path

from .errors import ICDError
from .selfcheck import verify_offline


def main():
    parser = argparse.ArgumentParser(description="Offline common HIL-ICD codec verification only")
    parser.add_argument("--contract-dir", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True, help="externally pinned four-component fingerprint")
    args = parser.parse_args()
    try:
        report = verify_offline(args.contract_dir, args.expected_sha256)
    except (ICDError, OSError, ValueError, KeyError, IndexError) as exc:
        report = {"status": "OFFLINE_CODEC_FAILED", "error": exc.code if isinstance(exc, ICDError) else "SCHEMA",
                  "detail": str(exc), "runtime_network_model_hardware_replacement": "NOT_EXECUTED"}
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
