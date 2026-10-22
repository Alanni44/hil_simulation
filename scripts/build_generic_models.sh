#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
MATLAB_BIN="${MATLAB_BIN:-/usr/local/MATLAB/R2018b/bin/matlab}"

if [[ ! -x "$MATLAB_BIN" ]]; then
    echo "MATLAB R2018b executable not found: $MATLAB_BIN" >&2
    exit 2
fi

build_one() {
    local model_name="$1"
    local model_dir="$ROOT_DIR/artifacts/generic_models/$2"
    local generator="$3"
    local logs_dir="$model_dir/logs"
    local bin_dir="$model_dir/bin"
    local task_file="$logs_dir/build_task.json"
    local result_file="$logs_dir/build_result.json"
    mkdir -p "$logs_dir" "$bin_dir"

    "$MATLAB_BIN" -nodisplay -nosplash -nodesktop -r \
        "try,addpath('$ROOT_DIR/matlab_scripts');$generator;catch ME,disp(getReport(ME,'extended'));exit(1);end;exit(0);" \
        >"$logs_dir/generate.log" 2>&1

    python3 - "$model_name" "$model_dir" "$logs_dir" "$bin_dir" "$task_file" <<'PY'
import json
import os
import sys

model_name, model_dir, logs_dir, bin_dir, task_file = sys.argv[1:]
task = {
    "model_name": model_name,
    "slx_path": os.path.join(model_dir, model_name + ".slx"),
    "contract_path": os.path.join(model_dir, "hil_contract.json"),
    "output_dir": os.path.join(logs_dir, "generated"),
    "executable_dir": bin_dir,
    "matlab_version": "R2018b",
    "package_root": model_dir,
    "dependency_paths": [],
}
with open(task_file, "w") as output:
    json.dump(task, output, indent=2, sort_keys=True)
    output.write("\n")
PY

    "$MATLAB_BIN" -nodisplay -nosplash -nodesktop -r \
        "try,addpath('$ROOT_DIR/matlab_scripts');build_script('$task_file','$result_file');catch ME,disp(getReport(ME,'extended'));exit(1);end;exit(0);" \
        >"$logs_dir/build.log" 2>&1

    python3 - "$result_file" <<'PY'
import json
import sys
with open(sys.argv[1]) as source:
    result = json.load(source)
if result.get("code") != 0:
    raise SystemExit(result.get("message", "ERT/GCC build failed"))
print(result["exe_path"])
PY
}

build_one multirotor_6_hil multirotor_6 \
    "generate_multirotor_model('$ROOT_DIR/artifacts/generic_models/multirotor_6',6);create_generic_vehicle_contract('$ROOT_DIR/artifacts/generic_models/multirotor_6','multirotor',6)"
build_one fixed_wing_hil fixed_wing \
    "generate_fixed_wing_model('$ROOT_DIR/artifacts/generic_models/fixed_wing');create_generic_vehicle_contract('$ROOT_DIR/artifacts/generic_models/fixed_wing','fixed_wing',4)"
