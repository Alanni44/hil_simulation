#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== HIL System (MATLAB ERT Pipeline) ==="

# ---- Config ----
SLX_PATH="${SLX_PATH:-$HOME/桌面/Quad-Simulink-Simulation-master/Quad-Simulink-Simulation-master/Quad_sim.slx}"
MODEL_NAME="${MODEL_NAME:-Quad_sim}"
MATLAB_BIN="/usr/local/MATLAB/R2018b/bin/matlab"
EXE_PATH="$ROOT/models/executables/${MODEL_NAME}_rt"

# ---- Find MATLAB ----
if [ ! -x "$MATLAB_BIN" ]; then
    MATLAB_BIN="$(command -v matlab 2>/dev/null || echo '')"
fi
if [ -z "$MATLAB_BIN" ]; then
    echo "ERROR: MATLAB R2018b not found"
    exit 1
fi

# ---- Check SLX ----
if [ ! -f "$SLX_PATH" ]; then
    echo "ERROR: SLX not found: $SLX_PATH"
    echo "Set SLX_PATH=/path/to/model.slx"
    exit 1
fi

echo "SLX:    $SLX_PATH"
echo "MATLAB: $MATLAB_BIN"
echo ""

# ---------- 1. MATLAB ERT Build ----------
echo "[1/2] MATLAB ERT build..."

mkdir -p "$ROOT/models/builds/$MODEL_NAME" "$ROOT/models/executables"

cat > /tmp/hil_build_task.json << JSONEOF
{
  "model_name": "$MODEL_NAME",
  "slx_path": "$SLX_PATH",
  "output_dir": "$ROOT/models/builds/$MODEL_NAME",
  "lib_name": "lib${MODEL_NAME}"
}
JSONEOF

"$MATLAB_BIN" -nodisplay -nosplash -nodesktop -r \
    "addpath('$ROOT/matlab_scripts'); build_script('/tmp/hil_build_task.json', '/tmp/hil_build_result.json'); exit;" \
    2>&1

if [ ! -f /tmp/hil_build_result.json ]; then
    echo "ERROR: MATLAB did not produce build result"
    exit 1
fi

RESULT=$(python3 -c "import json; print(json.load(open('/tmp/hil_build_result.json')).get('code', -1))" 2>/dev/null || echo "-1")
if [ "$RESULT" != "0" ]; then
    echo "ERROR: MATLAB ERT build failed"
    python3 -c "import json; d=json.load(open('/tmp/hil_build_result.json')); print('  reason:', d.get('message','?'))" 2>/dev/null || true
    exit 1
fi

echo "MATLAB ERT build OK"

# ---------- 2. Start services ----------
echo "[2/2] Starting services..."

sudo "$EXE_PATH" &
RT_PID=$!
echo "C core PID: $RT_PID"

sleep 1

cd python_services
python3 main.py &
PY_PID=$!
echo "Python PID: $PY_PID"
cd ..

echo ""
echo "=== All started ==="
echo "  C core:  $EXE_PATH (PID $RT_PID)"
echo "  Python:  PID $PY_PID"
echo "  Ctrl+C to stop"
echo ""

trap "kill $RT_PID $PY_PID 2>/dev/null; exit" INT TERM
wait
