#!/bin/bash
# ============================================================
# HIL Demo — 只连 UE4，不连 Spring Boot
# 配合 mock_core CSV 回放使用
# ============================================================
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== HIL Demo (UE4 only) ==="
echo ""

cd python_services
python3 -c "
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath('main.py')))
from udp_forwarder import start_udp_forwarder
from bridge_tcp_client import start_bridge
import threading, time

t1 = threading.Thread(target=start_udp_forwarder, daemon=True)
t2 = threading.Thread(target=start_bridge, daemon=True)
t1.start()
t2.start()
print('[Demo] UDP forwarder + Bridge started')
print('[Demo] Ctrl+C to stop')
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print('Stopped')
" &
PID=$!
cd ..

echo ""
echo "=== Started ==="
echo "  Bridge:     -> 192.168.100.172:5000 (V2.0)"
echo "  UDP 9998:   <- mock_core"
echo ""
echo "现在在另一个终端运行:"
echo "  python3 tests/mock_core.py --csv uav_circle_test_50hz_60s.csv"
echo ""
echo "  Ctrl+C to stop"

trap "kill $PID 2>/dev/null; exit" INT TERM
wait
