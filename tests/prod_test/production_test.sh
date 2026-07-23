#!/bin/bash
# ============================================================
# HIL 生产模式一键测试
# 自动: 编译 → 启动 → 测试 → 清理
#
# 前置:
#   1. Ubuntu 18.04 + build-essential + libjson-c-dev
#   2. Python 3.6.9 + pyyaml
#   3. MATLAB R2018b（可选）
#
# 用法:
#   bash tests/prod_test/production_test.sh
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROD_DIR="$ROOT/tests/prod_test"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

PIDS=()
PROD_MODE="UNKNOWN"   # will be set during Phase 0

cleanup() {
    echo ""
    echo -e "${YELLOW}[cleanup] Stopping all services...${NC}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    pkill -f "python3 main.py" 2>/dev/null || true
    pkill -f "test_ue4_client.py" 2>/dev/null || true
    pkill -f "mock_core.py" 2>/dev/null || true
    pkill -f "_rt" 2>/dev/null || true
    wait 2>/dev/null || true
    echo -e "${GREEN}[cleanup] Done${NC}"
}
trap cleanup EXIT INT TERM

# ---- find MATLAB binary ----
find_matlab() {
    for candidate in \
        /usr/local/MATLAB/R2018b/bin/matlab \
        /usr/local/bin/matlab \
        /opt/matlab/R2018b/bin/matlab \
        "$HOME/MATLAB/R2018b/bin/matlab"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    # try PATH
    if command -v matlab &>/dev/null; then
        echo "matlab"
        return 0
    fi
    return 1
}

echo "============================================================"
echo "  HIL Production Mode Full Test"
echo "============================================================"
echo ""

# ---- Config ----
# Auto-detect desktop path (Chinese or English)
USER_DESKTOP="$HOME"
for candidate in "$HOME/Desktop" "$HOME/桌面"; do
    if [ -d "$candidate" ]; then
        USER_DESKTOP="$candidate"
        break
    fi
done

SLX_PATH="${SLX_PATH:-$USER_DESKTOP/Quad-Simulink-Simulation-master/Quad-Simulink-Simulation-master/Quad_sim.slx}"
MODEL_NAME="${MODEL_NAME:-Quad_sim}"
EXE_PATH="$ROOT/models/executables/${MODEL_NAME}_rt"
MATLAB_BIN="$(find_matlab 2>/dev/null || echo '')"

# ---- Preflight ----
echo -e "${CYAN}[preflight] Checking required paths...${NC}"
echo "  Desktop: $USER_DESKTOP"
MISSING=0

# Check SLX
if [ -f "$SLX_PATH" ]; then
    echo "  [OK]  SLX: $SLX_PATH"
else
    echo "  [MISS] SLX: $SLX_PATH"
    MISSING=1
fi

# Check MATLAB
if [ -n "$MATLAB_BIN" ]; then
    echo "  [OK]  MATLAB: $MATLAB_BIN"
else
    echo "  [MISS] MATLAB: not found in any of:"
    echo "           /usr/local/MATLAB/R2018b/bin/matlab"
    echo "           /usr/local/bin/matlab"
    echo "           /opt/matlab/R2018b/bin/matlab"
    echo "           \$HOME/MATLAB/R2018b/bin/matlab"
    echo "           \$PATH"
    MISSING=1
fi

# Check required dev tools
for dep in gcc g++ python3; do
    if command -v $dep &>/dev/null; then
        echo "  [OK]  $dep: $(which $dep)"
    else
        echo "  [MISS] $dep"
        MISSING=1
    fi
done

# Check libjson-c (header)
JSON_H_FOUND=$(find /usr/include -name "json.h" -path "*json-c*" 2>/dev/null | head -1)
if [ -n "$JSON_H_FOUND" ]; then
    echo "  [OK]  libjson-c-dev: $JSON_H_FOUND"
elif [ -f "/usr/include/json-c/json.h" ]; then
    echo "  [OK]  libjson-c-dev: /usr/include/json-c/json.h"
elif [ -f "/usr/include/json/json.h" ]; then
    echo "  [OK]  libjson-c-dev: /usr/include/json/json.h"
else
    echo "  [MISS] libjson-c-dev (run: sudo apt install -y libjson-c-dev)"
    MISSING=1
fi

# Check pyyaml
if python3 -c "import yaml" 2>/dev/null; then
    echo "  [OK]  pyyaml"
else
    echo "  [MISS] pyyaml (run: pip3 install pyyaml)"
    MISSING=1
fi

# Mode prediction
echo ""
if [ "$MISSING" -eq 0 ] && [ -f "$SLX_PATH" ] && [ -n "$MATLAB_BIN" ]; then
    echo -e "  ${GREEN}Predict: MATLAB_ERT (full production)${NC}"
elif [ "$MISSING" -eq 0 ]; then
    echo -e "  ${YELLOW}Predict: GCC_FALLBACK (C core without ERT)${NC}"
else
    echo -e "  ${RED}Predict: FAIL — missing dependencies (see [MISS] above)${NC}"
    echo ""
    echo "  Fix missing items before running this script."
    echo ""
    echo "  Quick install:"
    echo "    sudo apt install -y build-essential libjson-c-dev"
    echo "    pip3 install pyyaml"
    echo ""
    exit 1
fi
echo ""

echo -e "${CYAN}[preflight] Environment check${NC}"
echo "  SLX:    ${SLX_PATH:-NOT SET}"
echo "  MATLAB: ${MATLAB_BIN:-NOT FOUND}"
echo "  gcc:    $(which gcc 2>/dev/null || echo 'NOT FOUND')"
echo "  python3: $(which python3)"
echo ""

# ============================================================
#  Phase 0: Build C core
# ============================================================
echo -e "${CYAN}=== Phase 0: Build C Core ===${NC}"

BUILD_NEEDED=0
if [ ! -f "$EXE_PATH" ]; then
    echo "  Executable not found, building..."
    BUILD_NEEDED=1
elif [ "${BUILD_ALWAYS:-0}" = "1" ]; then
    echo "  BUILD_ALWAYS=1, rebuilding..."
    BUILD_NEEDED=1
fi

if [ "$BUILD_NEEDED" = "1" ]; then
    if [ -n "$MATLAB_BIN" ] && [ -f "$SLX_PATH" ]; then
        echo ""
        echo -e "${MAGENTA}  >>> PRODUCTION MODE: MATLAB ERT Pipeline <<<${NC}"
        echo "  analyze_model.m → adapt_model.m → build_script.m → GCC"
        echo ""
        PROD_MODE="MATLAB_ERT"
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
            2>&1 | tail -40

        if [ -f /tmp/hil_build_result.json ]; then
            RESULT=$(python3 -c "import json; print(json.load(open('/tmp/hil_build_result.json')).get('code', -1))" 2>/dev/null || echo "-1")
            if [ "$RESULT" = "0" ]; then
                echo -e "${GREEN}  MATLAB ERT build OK${NC}"
                echo "  model_mapping.h + model_config.h auto-generated"
            else
                echo -e "${RED}  MATLAB build FAILED (code=$RESULT)${NC}"
                python3 -c "import json; d=json.load(open('/tmp/hil_build_result.json')); print('  reason:', d.get('message','?'))" 2>/dev/null || true
                echo "  Falling back to manual GCC..."
                BUILD_FALLBACK=1
            fi
        else
            echo "  build_result.json not found, falling back..."
            BUILD_FALLBACK=1
        fi
    else
        if [ -z "$MATLAB_BIN" ]; then
            echo -e "${YELLOW}  MATLAB not found (searched /usr/local/MATLAB, /opt/matlab, $HOME/MATLAB, PATH)${NC}"
        fi
        if [ ! -f "$SLX_PATH" ]; then
            echo -e "${YELLOW}  SLX not found: $SLX_PATH${NC}"
        fi
        BUILD_FALLBACK=1
    fi

    if [ "${BUILD_FALLBACK:-0}" = "1" ]; then
        echo ""
        echo -e "${YELLOW}  >>> FALLBACK MODE: manual GCC (NO MATLAB / NO ERT) <<<${NC}"
        echo "  Using hand-written C model (my_uav_model.c) + model_config_stub.h"
        echo ""
        PROD_MODE="GCC_FALLBACK"
        mkdir -p "$ROOT/models/executables"

        # Write a stub model_config.h so main_rt.c compiles
        cat > /tmp/model_config_stub.h << 'STUBEOF'
#ifndef MODEL_CONFIG_H
#define MODEL_CONFIG_H
#define MODEL_NAME "gcc_fallback"
#define MODEL_SLX ""
#define MODEL_ADAPTED 0
#define MODEL_U_TUNABLE_COUNT 0
#include <stddef.h>
struct _tunable_entry { const char* name; size_t offset; };
static const struct _tunable_entry MODEL_U_TUNABLE_TABLE[] = {};
#define MODEL_DEFAULT_POS_X 0.0
#define MODEL_DEFAULT_POS_Y 0.0
#define MODEL_DEFAULT_POS_Z 10.0
#define MODEL_DEFAULT_ROLL  0.0f
#define MODEL_DEFAULT_PITCH 0.0f
#define MODEL_DEFAULT_YAW   0.0f
#define HAS_Y_pos_x 1
#define MODEL_Y_pos_x pos_x
#define HAS_Y_pos_y 1
#define MODEL_Y_pos_y pos_y
#define HAS_Y_pos_z 1
#define MODEL_Y_pos_z pos_z
#define HAS_Y_roll 1
#define MODEL_Y_roll roll
#define HAS_Y_pitch 1
#define MODEL_Y_pitch pitch
#define HAS_Y_yaw 1
#define MODEL_Y_yaw yaw
#define HAS_Y_vel_x 1
#define MODEL_Y_vel_x vel_x
#define HAS_Y_vel_y 1
#define MODEL_Y_vel_y vel_y
#define HAS_Y_vel_z 1
#define MODEL_Y_vel_z vel_z
#define HAS_Y_lat 1
#define MODEL_Y_lat lat
#define HAS_Y_lon 1
#define MODEL_Y_lon lon
#define HAS_Y_alt 1
#define MODEL_Y_alt alt
#define HAS_Y_acc_x 1
#define MODEL_Y_acc_x acc_x
#define HAS_Y_acc_y 1
#define MODEL_Y_acc_y acc_y
#define HAS_Y_acc_z 1
#define MODEL_Y_acc_z acc_z
#define HAS_Y_airborne 1
#define MODEL_Y_airborne airborne
#define HAS_U_cmd_x 1
#define MODEL_U_cmd_x cmd_x
#define HAS_U_cmd_y 1
#define MODEL_U_cmd_y cmd_y
#define HAS_U_cmd_z 1
#define MODEL_U_cmd_z cmd_z
#define HAS_U_cmd_speed 1
#define MODEL_U_cmd_speed cmd_speed
#define HAS_U_cmd_mode 1
#define MODEL_U_cmd_mode cmd_mode
#define HAS_U_cmd_duration 1
#define MODEL_U_cmd_duration cmd_duration
#define HAS_U_target_alt 1
#define MODEL_U_target_alt target_alt
#define HAS_U_throttle 1
#define MODEL_U_throttle throttle
#define HAS_U_pitch_cmd 1
#define MODEL_U_pitch_cmd pitch_cmd
#define HAS_U_roll_cmd 1
#define MODEL_U_roll_cmd roll_cmd
#define HAS_U_yaw_cmd 1
#define MODEL_U_yaw_cmd yaw_cmd
#define HAS_U_flight_mode 1
#define MODEL_U_flight_mode flight_mode
#define HAS_U_experiment_mode 1
#define MODEL_U_experiment_mode experiment_mode
#define HAS_U_lat_init 1
#define MODEL_U_lat_init lat_init
#define HAS_U_lon_init 1
#define MODEL_U_lon_init lon_init
#define HAS_U_alt_init 1
#define MODEL_U_alt_init alt_init
#define HAS_U_roll_init 1
#define MODEL_U_roll_init roll_init
#define HAS_U_pitch_init 1
#define MODEL_U_pitch_init pitch_init
#define HAS_U_yaw_init 1
#define MODEL_U_yaw_init yaw_init
#define HAS_U_init_x 1
#define MODEL_U_init_x init_x
#define HAS_U_init_y 1
#define MODEL_U_init_y init_y
#define HAS_U_min_speed 1
#define MODEL_U_min_speed min_speed
#define HAS_U_max_speed 1
#define MODEL_U_max_speed max_speed
#define HAS_U_min_height 1
#define MODEL_U_min_height min_height
#define HAS_U_max_height 1
#define MODEL_U_max_height max_height
#define HAS_U_pid_kp_roll 1
#define MODEL_U_pid_kp_roll pid_kp_roll
#define HAS_U_pid_ki_roll 1
#define MODEL_U_pid_ki_roll pid_ki_roll
#define HAS_U_pid_kd_roll 1
#define MODEL_U_pid_kd_roll pid_kd_roll
#define HAS_U_pid_kp_pitch 1
#define MODEL_U_pid_kp_pitch pid_kp_pitch
#define HAS_U_pid_ki_pitch 1
#define MODEL_U_pid_ki_pitch pid_ki_pitch
#define HAS_U_pid_kd_pitch 1
#define MODEL_U_pid_kd_pitch pid_kd_pitch
#define HAS_U_pid_kp_yaw 1
#define MODEL_U_pid_kp_yaw pid_kp_yaw
#define HAS_U_pid_ki_yaw 1
#define MODEL_U_pid_ki_yaw pid_ki_yaw
#define HAS_U_pid_kd_yaw 1
#define MODEL_U_pid_kd_yaw pid_kd_yaw
#endif
STUBEOF

        gcc -O2 -Wall -pthread \
            -I"$ROOT/c_core/src" -I"$ROOT/model" \
            -include /tmp/model_config_stub.h \
            -DMODEL_RT_BRIDGE_H='"my_uav_model.h"' \
            "$ROOT/model/my_uav_model.c" \
            "$ROOT/model/my_uav_model_data.c" \
            "$ROOT/model/rt_nonfinite.c" \
            "$ROOT/model/rtGetInf.c" \
            "$ROOT/model/rtGetNaN.c" \
            "$ROOT/c_core/src/main_rt.c" \
            "$ROOT/c_core/src/model_rt_wrapper.c" \
            "$ROOT/c_core/src/local_udp.c" \
            "$ROOT/c_core/src/hal_stub.c" \
            -lm -ljson-c -lpthread \
            -o "$EXE_PATH" 2>&1
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}  GCC build OK → $EXE_PATH${NC}"
        else
            echo -e "${RED}  GCC build FAILED${NC}"
            echo "  Make sure libjson-c-dev is installed: sudo apt install -y libjson-c-dev"
            exit 1
        fi
    fi
else
    echo "  Executable exists: $EXE_PATH"
    echo "  (set BUILD_ALWAYS=1 to force rebuild)"
    # Determine mode from existing binary
    if strings "$EXE_PATH" | grep -q "_ert_rtw"; then
        PROD_MODE="MATLAB_ERT"
    else
        PROD_MODE="GCC_FALLBACK"
    fi
fi

# ============================================================
#  Phase 1: Start services
# ============================================================
echo ""
echo -e "${CYAN}=== Phase 1: Start Services ===${NC}"

# 1a. UE4 Bridge Simulator
echo "  Starting UE4 simulator (TCP :5000)..."
python3 "$ROOT/tests/test_ue4_client.py" &
PIDS+=($!)
sleep 0.5

# 1b. Python services
echo "  Starting Python services (bridge V2.0 + UDP forwarder)..."
cd "$ROOT/python_services"
python3 main.py &
PIDS+=($!)
sleep 2.0
cd "$ROOT"

# 1c. C Core — try without sudo first
echo "  Starting C core..."
if [ "$SKIP_RT" = "1" ]; then
    echo -e "${YELLOW}  SKIP_RT=1 → mock_core (Python simulation, NOT production)${NC}"
    PROD_MODE="MOCK_CORE"
    python3 "$ROOT/tests/mock_core.py" &
    PIDS+=($!)
else
    # Try without sudo — if scheduler/mlock fails, the binary still runs
    "$EXE_PATH" &
    CORE_PID=$!
    PIDS+=($CORE_PID)
    sleep 1.0
    if ! kill -0 "$CORE_PID" 2>/dev/null; then
        echo -e "${YELLOW}  C core died without sudo (expected for RT ops), retrying with sudo...${NC}"
        sudo "$EXE_PATH" &
        CORE_PID=$!
        PIDS+=($CORE_PID)
        sleep 1.0
    fi
fi
sleep 1.0

echo ""
echo "────────────────────────────────────────────"
echo -e "  PRODUCTION MODE: ${MAGENTA}${PROD_MODE}${NC}"
echo "────────────────────────────────────────────"
case "$PROD_MODE" in
    MATLAB_ERT)
        echo "  ✓ analyze_model.m → adapt_model.m → build_script.m"
        echo "  ✓ ERT C code generated from .slx"
        echo "  ✓ All model parameters available via tune"
        echo "  ✓ Real C core binary (hard RT if sudo)"
        ;;
    GCC_FALLBACK)
        echo "  ⚠  MATLAB not found or SLX missing"
        echo "  ⚠  Using hand-written C model (NOT from .slx)"
        echo "  ✓ C core binary (hard RT if sudo)"
        echo "  ⚠  Model params limited to hand-written Inports only"
        ;;
    MOCK_CORE)
        echo "  ✗  NOT PRODUCTION — Python simulation"
        echo "  ✗  No C core, no real-time scheduling"
        echo "  ✗  Test data is synthetic, not from real model"
        ;;
esac
echo "────────────────────────────────────────────"
echo ""

echo -e "${GREEN}  All services started${NC}"

# ============================================================
#  Phase 2: Run tests
# ============================================================
echo ""
echo -e "${CYAN}=== Phase 2: Run Tests ===${NC}"

echo "  Running full_integration_test.py (reads UDP 9999)..."
echo ""

# Pipe a newline so the test doesn't wait for manual Enter
python3 -u "$ROOT/tests/full_integration_test.py" <<< "" 2>&1
TEST_EXIT=$?

echo ""
if [ "$TEST_EXIT" -eq 0 ]; then
    echo -e "${GREEN}  All tests passed${NC}"
else
    echo -e "${RED}  Tests completed with failures (exit=$TEST_EXIT)${NC}"
fi

# ============================================================
#  Phase 3: Report
# ============================================================
echo ""
echo "============================================================"
echo "  Test Complete"
echo "  Mode: ${PROD_MODE}"
echo "============================================================"

exit $TEST_EXIT
