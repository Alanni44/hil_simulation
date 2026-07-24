#!/bin/bash
# HIL Full Pipeline Integration Test
#   generate_test_model.m → analyze → adapt → ERT → C core + Python + UE4 sim → UDP tests
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
G='\033[0;32m'; R='\033[0;31m'; C='\033[0;36m'; N='\033[0m'
MATLAB="/usr/local/MATLAB/R2018b/bin/matlab"
BUILD_DIR="$ROOT/test_output"
SLX="$BUILD_DIR/hil_test_model.slx"
EXE="$ROOT/models/executables/hil_test_model_rt"
PASS=0; FAIL=0
CORE_PID=''; PY_PID=''; UE4_PID=''

check() { if [ "$2" = "0" ]; then PASS=$((PASS+1)); echo -e "  ${G}PASS${N} $1"; else FAIL=$((FAIL+1)); echo -e "  ${R}FAIL${N} $1"; fi; }

check_file() { if [ -f "$2" ]; then check "$1" 0; else check "$1" 1; fi; }
cleanup() {
    for pid in "$CORE_PID" "$PY_PID" "$UE4_PID"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "cleanup"
}
trap cleanup EXIT

echo "============================================================"
echo "  HIL Full Pipeline Integration Test"
echo "============================================================"
rm -rf "$BUILD_DIR"; mkdir -p "$BUILD_DIR" "$ROOT/models/executables"

# ---- Phase 0a: Generate .slx ----
echo ""; echo -e "${C}=== Phase 0a: Generate Model ===${N}"
"$MATLAB" -nodisplay -nosplash -nodesktop -r \
    "addpath('$ROOT/matlab_scripts'); generate_test_model('$BUILD_DIR'); exit;" 2>&1 || true
check_file "generate_test_model" "$SLX"
[ -f "$SLX" ] || { echo "ABORT: SLX not created"; exit 1; }

cat > /tmp/hil_test_task.json << 'JSONEOF'
{"model_name":"hil_test_model","slx_path":"BUILD_DIR_PLACEHOLDER","output_dir":"BUILD_DIR_PLACEHOLDER","lib_name":"libhil_test_model"}
JSONEOF
sed -i "s|BUILD_DIR_PLACEHOLDER|$BUILD_DIR|g" /tmp/hil_test_task.json

# ---- Phase 0b: ERT build ----
echo ""; echo -e "${C}=== Phase 0b: ERT Build (MATLAB + GCC, ~2-3 min) ===${N}"
"$MATLAB" -nodisplay -nosplash -nodesktop -r \
    "addpath('$ROOT/matlab_scripts'); build_script('/tmp/hil_test_task.json','/tmp/hil_test_result.json'); exit;" 2>&1 || true
check_file "ERT build" "$EXE"
[ -f "$EXE" ] || { echo "ABORT: executable not built"; exit 1; }

# ---- Phase 1: Start services ----
echo ""; echo -e "${C}=== Phase 1: Start Services ===${N}"
python3 "$ROOT/scripts/mini_ue4_sim.py" &
UE4_PID=$!; sleep 0.5
cd "$ROOT/python_services"; python3 main.py &
PY_PID=$!; cd "$ROOT"; sleep 2
sudo "$EXE" &
CORE_PID=$!; sleep 1
echo "PIDs: ue4=$UE4_PID py=$PY_PID core=$CORE_PID"
if kill -0 "$UE4_PID" 2>/dev/null && kill -0 "$PY_PID" 2>/dev/null && kill -0 "$CORE_PID" 2>/dev/null; then
    check "services_started" 0
else
    check "services_started" 1
fi

# ---- Phase 2: UDP tests ----
echo ""; echo -e "${C}=== Phase 2: Test ===${N}"

send() { python3 -c "import json,socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(json.dumps({'cmd':'$1','params':$2}).encode(),('127.0.0.1',9997))"; }

poll() { python3 -c "
import struct,socket
F='=I Q ddd ddd fff fff fff fff f ffff I I I B B 2x'; S=struct.calcsize(F)
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.settimeout(2); s.bind(('127.0.0.1',9999))
d,_=s.recvfrom(4096)
if len(d)==S:
    v=struct.unpack(F,d)
    print('%.2f %.2f %.2f %d %d %d'%(v[2],v[3],v[4],v[27],v[29],v[28]))
s.close()
" 2>/dev/null; }

sleep 4

echo -n "T1: "; send "init_sim" '{"initial_lat":39.9,"initial_lon":116.4}'; sleep 0.5
send "takeoff" '{"height":20}'; sleep 8
o=$(poll); z=$(echo "$o" | awk '{print $3}')
check "T1-takeoff z=$(printf "%.1f" "$z") >5" $(python3 -c "print(0 if float($z)>5 else 1)")

echo -n "T2: "; send "move_position" '{"x":10,"y":10,"height":25}'; sleep 8
o=$(poll); x=$(echo "$o" | awk '{print $1}'); y=$(echo "$o" | awk '{print $2}')
check "T2-move ($(printf "%.1f" "$x"),$(printf "%.1f" "$y")) near(10,10)" $(python3 -c "print(0 if abs($x-10)<5 and abs($y-10)<5 else 1)")

echo -n "T3: "; send "land"; sleep 6
o=$(poll); z=$(echo "$o" | awk '{print $3}'); fs=$(echo "$o" | awk '{print $5}')
check "T3-land z=$(printf "%.1f" "$z") fs=$fs" $(python3 -c "print(0 if float($z)<1 and int($fs)==5 else 1)")

echo -n "T4: "; send "takeoff" '{"height":10}'; sleep 3
send "load_mission" '{"mission_id":"m1","waypoints":[{"lat":39.9001,"lon":116.4,"height":15,"speed":5},{"lat":39.9001,"lon":116.4001,"height":20,"speed":5},{"lat":39.9,"lon":116.4001,"height":10,"speed":3}]}'; sleep 8
o=$(poll); wi=$(echo "$o" | awk '{print $4}')
check "T4-wp idx=$wi >=1" $(python3 -c "print(0 if $wi>=1 else 1)")

echo -n "T5: "; send "tune" '{"u_mass":1.3}'; sleep 2
t5ok=1; [ -n "$(poll)" ] && t5ok=0; check "T5-tune_no_crash" $t5ok

echo -n "T6: "; send "land"; sleep 3; send "tune" '{"u_mass":-0.1}'; sleep 1
t6ok=1; [ -n "$(poll)" ] && t6ok=0; check "T6-neg_mass_no_crash" $t6ok

echo ""; echo "============================================================"
printf "  %s%d passed, %s%d failed%s (total %d)\n" "$G" $PASS "$R" $FAIL "$N" $((PASS+FAIL))
echo "============================================================"
[ $FAIL -gt 0 ] && exit 1 || exit 0
