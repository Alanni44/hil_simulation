#!/bin/bash
# ============================================================
# HIL System Demo — Ubuntu 18.04 / GCC 7 / Python 3.6.9
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=============================================="
echo "  HIL Simulation Demo"
echo "=============================================="

pkill -f "mock_core.py" 2>/dev/null || true
pkill -f "python3 main.py" 2>/dev/null || true
sleep 1

echo ""
echo -e "${YELLOW}[1/3] Compiling standalone RT executable...${NC}"
mkdir -p models/executables
if gcc -O2 -Wall -pthread \
    -I./c_core/src -I./model \
    -DMODEL_RT_BRIDGE_H=my_uav_model.h \
    -DMODEL_INIT_FN=my_uav_model_initialize \
    -DMODEL_STEP_FN=my_uav_model_step \
    -DMODEL_TERM_FN=my_uav_model_terminate \
    -DMODEL_U_VAR=my_uav_model_U \
    -DMODEL_Y_VAR=my_uav_model_Y \
    c_core/src/main_rt.c \
    c_core/src/model_rt_wrapper.c \
    c_core/src/local_udp.c \
    c_core/src/hal_stub.c \
    model/my_uav_model.c model/my_uav_model_data.c \
    model/rt_nonfinite.c model/rtGetInf.c model/rtGetNaN.c \
    -lm -lrt -ljson-c -lpthread \
    -o models/executables/my_uav_model_rt 2>&1; then
    echo -e "${GREEN}  -> models/executables/my_uav_model_rt OK${NC}"
else
    echo -e "${RED}  -> RT executable FAILED${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[2/3] Starting mock C-core...${NC}"
python3 tests/mock_core.py &
MOCK_PID=$!
echo "  Mock C-core PID: $MOCK_PID"
sleep 1

echo ""
echo -e "${YELLOW}[3/3] Starting HIL Python services...${NC}"
cd python_services
python3 main.py &
PY_PID=$!
echo "  HIL Python PID: $PY_PID"
cd ..
sleep 2

echo ""
echo "=============================================="
echo -e "${GREEN}  All services running${NC}"
echo "  HIL -> Spring Boot:      ws://192.168.100.138:8080/ws/hil"
echo "  V2.0 Bridge -> UE4:      192.168.100.172:5000 (20Hz)"
echo "  Ctrl+C to stop"
echo "=============================================="

cleanup() {
    echo ""
    echo "Stopping..."
    kill $MOCK_PID 2>/dev/null || true
    kill $PY_PID 2>/dev/null || true
    sleep 1
    echo -e "${GREEN}=== Stopped ===${NC}"
}
trap cleanup INT TERM
wait
