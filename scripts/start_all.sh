#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== HIL System (Standalone RT Executable) ==="

# ---------- 1. compile standalone RT executable ----------
echo "[1/2] Compiling standalone RT executable..."
mkdir -p models/executables
gcc -O2 -Wall -pthread \
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
    -o models/executables/my_uav_model_rt
echo "  -> models/executables/my_uav_model_rt"

# ---------- 2. start services ----------
echo "[2/2] Starting services..."

sudo ./models/executables/my_uav_model_rt &
RT_PID=$!
echo "  RT executable PID: $RT_PID"

sleep 1

cd python_services
python3 main.py &
PY_PID=$!
echo "  Python PID: $PY_PID"
cd ..

echo ""
echo "=== All started ==="
echo "  RT executable PID: $RT_PID"
echo "  Python PID:        $PY_PID"
echo "  V2.0 Bridge:     -> Python Bridge 192.168.100.172:5000"
echo "  WebSocket client: -> Spring Boot (see config.yaml)"
echo "  Ctrl+C to stop"
echo ""

trap "kill $RT_PID $PY_PID 2>/dev/null; exit" INT TERM
wait
