#!/usr/bin/env bash
# Build a queue-enabled L-010 candidate without touching the accepted model
# package, generated-code directory, or executable.
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [[ $# -ne 1 ]]; then
    echo "usage: $0 <new-candidate-directory>" >&2
    exit 2
fi
CANDIDATE_DIR="$(realpath -m "$1")"
case "$CANDIDATE_DIR" in
    "$ROOT_DIR"/artifacts/linux_target/*) ;;
    *) echo "candidate directory must be below $ROOT_DIR/artifacts/linux_target" >&2; exit 2 ;;
esac
if [[ -e "$CANDIDATE_DIR" ]]; then
    echo "candidate directory already exists: $CANDIDATE_DIR" >&2
    exit 2
fi
MATLAB_BIN="${MATLAB_BIN:-/usr/local/MATLAB/R2018b/bin/matlab}"
if [[ ! -x "$MATLAB_BIN" ]]; then
    echo "MATLAB R2018b executable not found: $MATLAB_BIN" >&2
    exit 2
fi

mkdir -p "$CANDIDATE_DIR/generated" "$CANDIDATE_DIR/bin"
TASK_FILE="$CANDIDATE_DIR/build_task.json"
RESULT_FILE="$CANDIDATE_DIR/build_result.json"
BUILD_LOG="$CANDIDATE_DIR/build.log"

"$ROOT_DIR/runtime/python3.12/bin/python3.12" - "$ROOT_DIR" "$CANDIDATE_DIR" "$TASK_FILE" <<'PY'
import json
import sys

root, candidate, task_file = sys.argv[1:]
task = {
    "model_name": "quadrotor_hil",
    "slx_path": root + "/artifacts/z_mission/model/quadrotor_hil.slx",
    "contract_path": root + "/artifacts/z_mission/model/hil_contract.json",
    "output_dir": candidate + "/generated",
    "executable_dir": candidate + "/bin",
    "matlab_version": "R2018b",
    "package_root": root + "/artifacts/z_mission/model",
    "dependency_paths": [],
}
with open(task_file, "w", encoding="utf-8") as output:
    json.dump(task, output, indent=2, sort_keys=True)
    output.write("\n")
PY

"$MATLAB_BIN" -nodisplay -nosplash -nodesktop -r \
    "try,addpath('$ROOT_DIR/matlab_scripts');build_script('$TASK_FILE','$RESULT_FILE');catch ME,disp(getReport(ME,'extended'));exit(1);end;exit(0);" \
    >"$BUILD_LOG" 2>&1

"$ROOT_DIR/runtime/python3.12/bin/python3.12" - "$RESULT_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    result = json.load(source)
if result.get("code") != 0:
    raise SystemExit(result.get("message", "isolated L-010 candidate build failed"))
print(result["exe_path"])
PY
