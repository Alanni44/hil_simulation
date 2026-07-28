#!/usr/bin/env bash
set -euo pipefail

# The generated ERT/GCC binary is deployable only after this script runs on
# the acceptance target: Ubuntu 18.04 with a PREEMPT_RT kernel and MATLAB
# R2018b.  A Windows source checkout cannot provide that build evidence.
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
MODEL_DIR="$ROOT_DIR/artifacts/z_mission/model"
BIN_DIR="$ROOT_DIR/artifacts/z_mission/bin"
LOG_DIR="$ROOT_DIR/artifacts/z_mission/logs"
TASK_FILE="$LOG_DIR/build_task.json"
RESULT_FILE="$LOG_DIR/build_result.json"
BUILD_LOG="$LOG_DIR/build.log"

if ! grep -q 'VERSION_ID="18.04"' /etc/os-release; then
    echo 'quadrotor build requires Ubuntu 18.04 RT' >&2
    exit 2
fi
if ! uname -a | grep -Eqi 'PREEMPT[ _-]?RT'; then
    echo 'quadrotor build requires a PREEMPT_RT kernel' >&2
    exit 2
fi

mkdir -p "$MODEL_DIR" "$BIN_DIR" "$LOG_DIR"
MATLAB_BIN="${MATLAB_BIN:-/usr/local/MATLAB/R2018b/bin/matlab}"
if [[ ! -x "$MATLAB_BIN" ]]; then
    echo "MATLAB R2018b executable not found: $MATLAB_BIN" >&2
    exit 2
fi

"$MATLAB_BIN" -nodisplay -nosplash -nodesktop -r \
    "try,addpath('$ROOT_DIR/matlab_scripts');generate_quadrotor_model('$MODEL_DIR');create_quadrotor_contract('$MODEL_DIR');catch ME,disp(getReport(ME,'extended'));exit(1);end;exit(0);" \
    >"$BUILD_LOG" 2>&1

python3 - "$ROOT_DIR" "$MODEL_DIR" "$BIN_DIR" "$LOG_DIR" "$TASK_FILE" <<'PY'
import json
import os
import sys

root_dir, model_dir, bin_dir, log_dir, task_file = sys.argv[1:]
task = {
    'model_name': 'quadrotor_hil',
    'slx_path': os.path.join(model_dir, 'quadrotor_hil.slx'),
    'contract_path': os.path.join(model_dir, 'hil_contract.json'),
    'output_dir': os.path.join(log_dir, 'generated'),
    'executable_dir': bin_dir,
    'matlab_version': 'R2018b',
    'package_root': model_dir,
    'dependency_paths': [],
}
with open(task_file, 'w') as output:
    json.dump(task, output, indent=2, sort_keys=True)
    output.write('\n')
PY

"$MATLAB_BIN" -nodisplay -nosplash -nodesktop -r \
    "try,addpath('$ROOT_DIR/matlab_scripts');build_script('$TASK_FILE','$RESULT_FILE');catch ME,disp(getReport(ME,'extended'));exit(1);end;exit(0);" \
    >>"$BUILD_LOG" 2>&1

python3 - "$RESULT_FILE" <<'PY'
import json
import sys

with open(sys.argv[1]) as source:
    result = json.load(source)
if result.get('code') != 0:
    raise SystemExit(result.get('message', 'quadrotor ERT/GCC build failed'))
print(result['exe_path'])
PY
