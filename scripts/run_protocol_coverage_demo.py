"""Exercise every frozen CANFD simulator input against reception-only 3.6."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from icd_runtime.errors import ICDError


DEFAULT_BASELINE_SHA256 = "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
MODEL_INPUTS = (
    ("quadrotor_hil", (7, 10, 11, 14)),
    ("multirotor_6_hil", (8, 10, 12, 15)),
    ("fixed_wing_hil", (9, 10, 13, 16)),
)


def _protocol_demo():
    path = ROOT / "scripts" / "run_protocol_reception_demo.py"
    spec = importlib.util.spec_from_file_location("_protocol_reception_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(contract_dir, expected_sha256, output_directory):
    target = Path(output_directory)
    target.mkdir(parents=True, exist_ok=False)
    demo = _protocol_demo()
    results = []
    for model_id, message_ids in MODEL_INPUTS:
        evidence = target / (model_id + ".jsonl")
        result = demo.run(contract_dir, expected_sha256, evidence, count=1, period_steps=80,
                          model_id=model_id, message_ids=message_ids)
        if result["generated_samples"] != len(message_ids) or result["decoded_samples"] != len(message_ids):
            raise ICDError("STATE", "protocol coverage result lacks a decoded frozen input")
        results.append(result)
    all_ids = sorted({mid for _, mids in MODEL_INPUTS for mid in mids})
    manifest = {"format": "HIL_PROTOCOL_COVERAGE_1", "status": "RECEPTION_VALIDATED",
                "baseline_sha256": expected_sha256, "models": results, "unique_message_ids": all_ids,
                "generated_samples": sum(row["generated_samples"] for row in results),
                "decoded_samples": sum(row["decoded_samples"] for row in results),
                "model_application_verified": False, "physical_tool_qualification": "NOT_EVALUATED",
                "replacement_ready": False}
    path = target / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n",
                    encoding="utf-8")
    return {**manifest, "output_directory": str(target.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-dir", type=Path, default=Path("docs/interfaces/baseline"))
    parser.add_argument("--expected-sha256", default=DEFAULT_BASELINE_SHA256)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.contract_dir, args.expected_sha256, args.output_directory), ensure_ascii=True), flush=True)
        return 0
    except (ICDError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code if isinstance(error, ICDError) else "RESOURCE",
                          "detail": str(error), "model_application_verified": False,
                          "replacement_ready": False}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
