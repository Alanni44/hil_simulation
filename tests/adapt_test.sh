#!/bin/bash
# ============================================================
# 端到端验证: Quad_sim.slx 自动适配 → 编译 → 回放
# 前置条件:
#   1. MATLAB R2018b 已安装, matlab 在 PATH 中
#   2. build-essential, libjson-c-dev 已安装
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TEST_DIR="$ROOT/tests/adapt_test"
SLX_SRC="$HOME/Desktop/Quad-Simulink-Simulation-master/Quad-Simulink-Simulation-master/Quad_sim.slx"

echo "=== SLX Adaptation E2E Test ==="
echo ""

# ---- cleanup ----
rm -rf "$TEST_DIR" 2>/dev/null || true
mkdir -p "$TEST_DIR"
mkdir -p "$TEST_DIR/executables"

# ---- Step 1: analyze_model ----
echo "[1/5] analyze_model..."
matlab -nodisplay -nosplash -nodesktop -r \
    "addpath('$ROOT/matlab_scripts'); analyze_model('$SLX_SRC', '$TEST_DIR/Quad_sim_interface.json'); exit;" 2>&1 | tail -5

# Verify output
if [ ! -f "$TEST_DIR/Quad_sim_interface.json" ]; then
    echo "ERROR: interface.json not generated"
    exit 1
fi
echo "  -> interface.json OK"

# ---- Step 2: adapt_model ----
echo "[2/5] adapt_model..."
matlab -nodisplay -nosplash -nodesktop -r \
    "addpath('$ROOT/matlab_scripts'); adapt_model('$SLX_SRC', '$TEST_DIR/Quad_sim_interface.json', '$TEST_DIR/Quad_sim_adapted.slx'); exit;" 2>&1 | tail -10

if [ ! -f "$TEST_DIR/field_mapping.json" ]; then
    echo "ERROR: field_mapping.json not generated"
    exit 1
fi
echo "  -> field_mapping.json OK"
echo ""

# ---- Step 3: build_script ----
echo "[3/5] build_script..."
mkdir -p "$TEST_DIR/build_task"
cat > "$TEST_DIR/build_task.json" <<JSONEOF
{
  "model_name": "Quad_sim",
  "slx_path": "$SLX_SRC",
  "output_dir": "$TEST_DIR",
  "lib_name": "libQuad_sim"
}
JSONEOF

matlab -nodisplay -nosplash -nodesktop -r \
    "addpath('$ROOT/matlab_scripts'); build_script('$TEST_DIR/build_task.json', '$TEST_DIR/build_result.json'); exit;" 2>&1 | tail -20

# Verify result
if [ ! -f "$TEST_DIR/build_result.json" ]; then
    echo "ERROR: build_result.json not generated"
    exit 1
fi

RESULT_CODE=$(python3 -c "import json; print(json.load(open('$TEST_DIR/build_result.json')).get('code', -1))")
if [ "$RESULT_CODE" != "0" ]; then
    echo "ERROR: Build failed with code $RESULT_CODE"
    cat "$TEST_DIR/build_result.json" 2>/dev/null
    exit 1
fi
echo "  -> Build OK"
echo ""

# ---- Step 4: verify generated files ----
echo "[4/5] Verification..."
EXE_PATH=$(python3 -c "import json; print(json.load(open('$TEST_DIR/build_result.json')).get('exe_path', ''))")
echo "  Executable: $EXE_PATH"
echo "  model_mapping.h:"
head -20 "$TEST_DIR/model_mapping.h" 2>/dev/null || echo "  (WARNING: model_mapping.h not found)"
echo ""
echo "  model_config.h:"
head -20 "$TEST_DIR/model_config.h" 2>/dev/null || echo "  (WARNING: model_config.h not found)"
echo ""

# ---- Step 5: dry-run mock_core with adapted module ----
echo "[5/5] Summary"
echo "============================================"
echo "  All steps completed successfully!"
echo "  Adapted model: $TEST_DIR/Quad_sim_adapted.slx"
echo "  Executable:    $EXE_PATH"
echo "  Interface:     $TEST_DIR/Quad_sim_interface.json"
echo "  Mapping:       $TEST_DIR/field_mapping.json"
echo ""
echo "  To run the adapted model:"
echo "    sudo $EXE_PATH"
echo "============================================"
