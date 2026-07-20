#!/bin/bash
# ============================================================
# HIL System Demo — Ubuntu 18.04 / GCC 7 / Python 3.6.9
# HIL connects to Spring Boot at 192.168.100.138:8080/ws/hil
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
echo "  Spring Boot: 192.168.100.138:8080/ws/hil"
echo "=============================================="

pkill -f "mock_core.py" 2>/dev/null || true
pkill -f "python3 main.py" 2>/dev/null || true
sleep 1

echo ""
echo -e "${YELLOW}[1/4] Compiling model .so...${NC}"
mkdir -p models/libs
if gcc -shared -fPIC -O2 -I./model \
    model/my_uav_model.c model/my_uav_model_data.c \
    model/rt_nonfinite.c model/rtGetInf.c model/rtGetNaN.c \
    -lm -o models/libs/libmodel_default.so 2>&1; then
    echo -e "${GREEN}  -> models/libs/libmodel_default.so OK${NC}"
else
    echo -e "${RED}  -> model .so FAILED${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[2/4] Compiling C core...${NC}"
mkdir -p c_core/build
if gcc -O2 -Wall -pthread -fPIC -I./c_core/src \
    c_core/src/main_rt.c \
    c_core/src/model_loader.c \
    c_core/src/hal_stub.c \
    c_core/src/local_udp.c \
    -lm -lrt -ljson-c -ldl \
    -o c_core/build/hil_core 2>&1; then
    echo -e "${GREEN}  -> c_core/build/hil_core OK${NC}"
else
    echo -e "${RED}  -> C core FAILED${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[3/4] Starting mock C-core...${NC}"
python3 tests/mock_core.py &
MOCK_PID=$!
echo "  Mock C-core PID: $MOCK_PID"
sleep 1

echo ""
echo -e "${YELLOW}[4/4] Starting HIL Python services...${NC}"
cd python_services
python3 main.py &
PY_PID=$!
echo "  HIL Python PID: $PY_PID"
cd ..
sleep 2

echo ""
echo "=============================================="
echo -e "${GREEN}  All services running${NC}"
echo "  HIL -> Spring Boot: ws://192.168.100.138:8080/ws/hil"
echo "  flight_data push:   10Hz"
echo "  sim_heartbeat push:  1Hz"
echo "  UE4 TCP push:       10Hz -> 192.168.100.172:5000"
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
