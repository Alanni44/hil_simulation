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
from bridge_tcp_client import send_mission_plan
import threading, time

MISSION_ID = 'mission_001'
CIRCLE_WAYPOINTS = [
    {'x': 30.0, 'y': 15.0, 'height': 10.0, 'speed': 5.0},
    {'x': 28.8, 'y': 22.8, 'height': 10.0, 'speed': 5.0},
    {'x': 22.8, 'y': 28.8, 'height': 10.0, 'speed': 5.0},
    {'x': 15.0, 'y': 30.0, 'height': 10.0, 'speed': 5.0},
    {'x': 7.2, 'y': 22.8, 'height': 10.0, 'speed': 5.0},
    {'x': 1.2, 'y': 15.0, 'height': 10.0, 'speed': 5.0},
    {'x': 7.2, 'y': 7.2, 'height': 10.0, 'speed': 5.0},
    {'x': 15.0, 'y': 0.0, 'height': 10.0, 'speed': 5.0},
    {'x': 22.8, 'y': 7.2, 'height': 10.0, 'speed': 5.0},
    {'x': 30.0, 'y': 15.0, 'height': 10.0, 'speed': 5.0},
]

t1 = threading.Thread(target=start_udp_forwarder, daemon=True)
t2 = threading.Thread(target=start_bridge, daemon=True)
t1.start()
t2.start()
time.sleep(2)  # 等 bridge hello → ack 完成
send_mission_plan(MISSION_ID, CIRCLE_WAYPOINTS)
print('[Demo] UDP forwarder + Bridge started, mission_plan queued')
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
