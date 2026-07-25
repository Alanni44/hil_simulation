#!/bin/bash
# HIL Full Pipeline Integration Test
#   generate_test_model.m → analyze → adapt → ERT → C core + Python + UE4 sim → UDP tests
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
G='\033[0;32m'; R='\033[0;31m'; C='\033[0;36m'; N='\033[0m'
MATLAB="/usr/local/MATLAB/R2018b/bin/matlab"
BUILD_DIR="$ROOT/test_output"
SLX="$BUILD_DIR/hil_test_model.slx"
EXE="$ROOT/executables/hil_test_model_rt"
PASS=0; FAIL=0
CORE_PID=''; PY_PID=''; UE4_PID=''
RUN_DIR="${HIL_TEST_LOG_DIR:-/tmp/hil_integration_$$}"
UE4_LOG="$RUN_DIR/mini_ue4.log"
PY_LOG="$RUN_DIR/python_services.log"
CORE_LOG="$RUN_DIR/core.log"

check() { if [ "$2" = "0" ]; then PASS=$((PASS+1)); echo -e "  ${G}PASS${N} $1"; else FAIL=$((FAIL+1)); echo -e "  ${R}FAIL${N} $1"; fi; }

check_file() { if [ -f "$2" ]; then check "$1" 0; else check "$1" 1; fi; }
cleanup() {
    local status=$?
    trap - EXIT
    for pid in "$CORE_PID" "$PY_PID" "$UE4_PID"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    if [ "$status" -ne 0 ]; then
        echo "--- failure diagnostics (logs: $RUN_DIR) ---"
        for log in "$CORE_LOG" "$PY_LOG" "$UE4_LOG"; do
            [ -f "$log" ] || continue
            echo "--- $log ---"
            tail -n 80 "$log" || true
        done
    fi
    echo "cleanup"
    exit "$status"
}
trap cleanup EXIT

echo "============================================================"
echo "  HIL Full Pipeline Integration Test"
echo "============================================================"
if [ "${HIL_SKIP_BUILD:-0}" = "1" ]; then
    echo "Using existing build artifacts (HIL_SKIP_BUILD=1)"
    check_file "existing SLX" "$SLX"
    check_file "existing ERT build" "$EXE"
    [ -f "$SLX" ] && [ -x "$EXE" ] || { echo "ABORT: required build artifacts are missing"; exit 1; }
else
    rm -rf "$BUILD_DIR"; mkdir -p "$BUILD_DIR" "$ROOT/executables"
    # Never accept a previous executable as evidence for this build.
    rm -f "$EXE"
    rm -f /tmp/hil_test_task.json /tmp/hil_test_result.json

    # ---- Phase 0a: Generate .slx ----
    echo ""; echo -e "${C}=== Phase 0a: Generate Model ===${N}"
    "$MATLAB" -nodisplay -nosplash -nodesktop -r \
        "addpath('$ROOT/matlab_scripts'); generate_test_model('$BUILD_DIR'); exit;" 2>&1 || true
    check_file "generate_test_model" "$SLX"
    [ -f "$SLX" ] || { echo "ABORT: SLX not created"; exit 1; }

    cat > /tmp/hil_test_task.json << 'JSONEOF'
{"model_name":"hil_test_model","slx_path":"SLX_PATH_PLACEHOLDER","output_dir":"BUILD_DIR_PLACEHOLDER","lib_name":"libhil_test_model"}
JSONEOF
    sed -i "s|SLX_PATH_PLACEHOLDER|$SLX|g; s|BUILD_DIR_PLACEHOLDER|$BUILD_DIR|g" /tmp/hil_test_task.json

    # ---- Phase 0b: ERT build ----
    echo ""; echo -e "${C}=== Phase 0b: ERT Build (MATLAB + GCC, ~2-3 min) ===${N}"
    "$MATLAB" -nodisplay -nosplash -nodesktop -r \
        "addpath('$ROOT/matlab_scripts'); build_script('/tmp/hil_test_task.json','/tmp/hil_test_result.json'); exit;" 2>&1 || true
    if [ ! -f "$EXE" ] && [ -f /tmp/hil_test_result.json ]; then
        python3 -c "import json; d=json.load(open('/tmp/hil_test_result.json')); print('ERT failure: %s' % d.get('message', 'no diagnostic message'))" || true
    fi
    check_file "ERT build" "$EXE"
    [ -f "$EXE" ] || { echo "ABORT: executable not built"; exit 1; }
fi

# ---- Phase 1: Start services ----
echo ""; echo -e "${C}=== Phase 1: Start Services ===${N}"
mkdir -p "$RUN_DIR"
stdbuf -oL -eL python3 "$ROOT/scripts/mini_ue4_sim.py" >"$UE4_LOG" 2>&1 &
UE4_PID=$!
(
    cd "$ROOT/python_services"
    exec stdbuf -oL -eL python3 main.py
) >"$PY_LOG" 2>&1 &
PY_PID=$!

# Integration tests do not require real-time privileges.  Avoid interactive
# sudo by default; production obtains these capabilities from systemd.  Set
# HIL_USE_SUDO=1 only when testing the privileged local launch path.
if [ "${HIL_USE_SUDO:-0}" = "1" ] && [ "${HIL_NO_SUDO:-0}" != "1" ]; then
    [ -t 0 ] || { echo "ABORT: HIL_USE_SUDO=1 requires an interactive terminal; use HIL_NO_SUDO=1 for CI"; exit 1; }
    echo "Requesting sudo authorization for the real-time core..."
    sudo -v
    echo "sudo authorization succeeded; starting core."
    stdbuf -oL -eL sudo -n "$EXE" >"$CORE_LOG" 2>&1 &
else
    echo "Starting core without real-time privileges (set HIL_USE_SUDO=1 to test sudo launch)."
    stdbuf -oL -eL "$EXE" >"$CORE_LOG" 2>&1 &
fi
CORE_PID=$!
echo "PIDs: ue4=$UE4_PID py=$PY_PID core=$CORE_PID"

# ---- Phase 2: UDP tests ----
echo ""; echo -e "${C}=== Phase 2: Test ===${N}"

send() {
    local cmd="$1"
    local params="${2:-}"
    [ -n "$params" ] || params='{}'
    python3 -c "import json,socket,sys; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.sendto(json.dumps({'cmd':sys.argv[1],'params':json.loads(sys.argv[2])}).encode(),('127.0.0.1',9997))" "$cmd" "$params"
}

poll() { python3 - "$1" <<'PY'
import struct, socket, sys, time

F = '=I Q ddd ddd fff fff fff fff f ffff I I I B B 2x'
S = struct.calcsize(F)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    timeout = float(sys.argv[1])
    s.settimeout(min(timeout, 0.5))
    s.bind(('127.0.0.1', 9999))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            datagram, _ = s.recvfrom(4096)
        except socket.timeout:
            continue
        if len(datagram) != S:
            print('UDP monitor packet has invalid size {} (expected {})'.format(len(datagram), S), file=sys.stderr)
            continue
        state = struct.unpack(F, datagram)
        print('%.2f %.2f %.2f %d %d %d' % (state[2], state[3], state[4], state[27], state[29], state[28]))
        sys.exit(0)
    raise RuntimeError('no valid UDP monitor packet on 127.0.0.1:9999 within {:.1f}s'.format(timeout))
except Exception as exc:
    print('poll failed: {}'.format(exc), file=sys.stderr)
    sys.exit(1)
finally:
    s.close()
PY
}

read_status() {
    local label="$1"
    local timeout="${2:-2}"
    if ! STATUS="$(poll "$timeout")"; then
        check "$label telemetry unavailable" 1
        return 1
    fi
    read -r STATE_X STATE_Y STATE_Z STATE_WP STATE_FS STATE_FLAGS <<< "$STATUS"
    if [ -z "$STATE_Z" ] || [ -z "$STATE_FS" ]; then
        check "$label malformed telemetry: $STATUS" 1
        return 1
    fi
    return 0
}

show_service_diagnostics() {
    echo "Service startup failed; logs retained in $RUN_DIR"
    for log in "$CORE_LOG" "$PY_LOG" "$UE4_LOG"; do
        [ -f "$log" ] || continue
        echo "--- $log ---"
        tail -n 80 "$log" || true
    done
}

# A launcher PID does not prove the core has bound UDP or emits telemetry.
if kill -0 "$UE4_PID" 2>/dev/null && kill -0 "$PY_PID" 2>/dev/null && \
   kill -0 "$CORE_PID" 2>/dev/null && STARTUP_STATUS="$(poll 10)"; then
    check "services_started (telemetry: $STARTUP_STATUS)" 0
else
    check "services_started" 1
    show_service_diagnostics
    exit 1
fi

echo -n "T1: "
if ! send "init_sim" '{"initial_lat":39.9,"initial_lon":116.4}'; then check "T1-init command" 1; fi
sleep 0.5
if ! send "takeoff" '{"height":20}'; then check "T1-takeoff command" 1; fi
sleep 8
if read_status "T1"; then
    if awk -v z="$STATE_Z" 'BEGIN { exit !(z > 5) }'; then t1ok=0; else t1ok=1; fi
    check "T1-takeoff z=$(printf "%.1f" "$STATE_Z") >5" "$t1ok"
fi

echo -n "T2: "
if ! send "move_position" '{"x":10,"y":10,"height":25}'; then check "T2-move command" 1; fi
sleep 8
if read_status "T2"; then
    if awk -v x="$STATE_X" -v y="$STATE_Y" 'BEGIN { exit !(sqrt((x-10)^2) < 5 && sqrt((y-10)^2) < 5) }'; then t2ok=0; else t2ok=1; fi
    check "T2-move ($(printf "%.1f" "$STATE_X"),$(printf "%.1f" "$STATE_Y")) near(10,10)" "$t2ok"
fi

echo -n "T3: "
if ! send "land"; then check "T3-land command" 1; fi
sleep 6
if read_status "T3"; then
    if awk -v z="$STATE_Z" -v fs="$STATE_FS" 'BEGIN { exit !(z < 1 && fs == 5) }'; then t3ok=0; else t3ok=1; fi
    check "T3-land z=$(printf "%.1f" "$STATE_Z") fs=$STATE_FS" "$t3ok"
fi

echo -n "T4: "
if ! send "takeoff" '{"height":10}'; then check "T4-takeoff command" 1; fi
sleep 3
if ! send "load_mission" '{"mission_id":"m1","waypoints":[{"lat":39.9001,"lon":116.4,"height":15,"speed":5},{"lat":39.9001,"lon":116.4001,"height":20,"speed":5},{"lat":39.9,"lon":116.4001,"height":10,"speed":3}]}'; then check "T4-mission command" 1; fi
sleep 8
if read_status "T4"; then
    if awk -v wp="$STATE_WP" 'BEGIN { exit !(wp >= 1) }'; then t4ok=0; else t4ok=1; fi
    check "T4-wp idx=$STATE_WP >=1" "$t4ok"
fi

echo -n "T5: "
if ! send "tune" '{"u_mass":1.3}'; then check "T5-tune command" 1; fi
sleep 2
if read_status "T5"; then check "T5-tune_no_crash" 0; fi

echo -n "T6: "
if ! send "land"; then check "T6-land command" 1; fi
sleep 3
if ! send "tune" '{"u_mass":-0.1}'; then check "T6-tune command" 1; fi
sleep 1
if read_status "T6"; then check "T6-neg_mass_no_crash" 0; fi

echo ""; echo "============================================================"
printf "  %s%d passed, %s%d failed%s (total %d)\n" "$G" $PASS "$R" $FAIL "$N" $((PASS+FAIL))
echo "============================================================"
[ $FAIL -gt 0 ] && exit 1 || exit 0
