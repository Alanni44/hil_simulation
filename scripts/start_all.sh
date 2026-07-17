#!/bin/bash
cd "$(dirname "$0")/.."

echo "=== Starting HIL Services ==="

sudo ./c_core/build/hil_core &
C_PID=$!
echo "C core PID: $C_PID"

sleep 1

cd python_services
python3 main.py &
PYTHON_PID=$!
echo "Python services PID: $PYTHON_PID"

cd ..
echo "=== All started ==="
echo "C: $C_PID, Python: $PYTHON_PID"
echo "Press Ctrl+C to stop"

trap "kill $C_PID $PYTHON_PID 2>/dev/null; exit" INT TERM
wait