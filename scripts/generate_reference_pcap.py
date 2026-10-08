"""Generate the first deterministic software-level HISTORY reference PCAP."""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from icd_runtime.contract import Contract
from input_simulator.reference_pcap import BASELINE_SHA256, write_reference_artifacts


def main():
    contract = Contract.load(ROOT / "docs" / "interfaces" / "baseline",
                            expected_sha256=BASELINE_SHA256)
    result = write_reference_artifacts(
        contract, ROOT / "artifacts" / "history" / "round1")
    print(json.dumps({
        "output_directory": result["output_directory"],
        "pcap_sha256": result["manifest"]["pcap_sha256"],
        "message_id": result["manifest"]["message_id"],
        "packet_count": result["frame_count"],
        "replay_packet_count": result["validation"]["stages"]["prepared"]["packet_count"],
        "execution_ready": result["validation"]["stages"]["prepared"]["execution_ready"],
    }, indent=2))


if __name__ == "__main__":
    main()
