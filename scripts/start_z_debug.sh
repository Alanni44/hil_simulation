#!/usr/bin/env bash
# Ubuntu 18.04 RT operator entry point for the real UE4 Z-mission debug path.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/runtime/z_debug"
RUN_LOCK="$RUN_DIR/run.lock"
DEBUG_MAIN="$ROOT/python_services/debug_main.py"
CONFIG_FILE="$ROOT/config.yaml"
MISSION_FILE="$ROOT/missions/z_mission.json"
STOP_SCRIPT="$ROOT/scripts/stop_z_debug.sh"
EXPECTED_TARGET="192.168.100.172:5000"

usage() {
    echo "Usage: $0 /absolute/path/to/verified_model_rt" >&2
    echo "   or: HIL_Z_MODEL_EXECUTABLE=/absolute/path/to/verified_model_rt $0" >&2
}

if [ "$#" -gt 1 ]; then
    usage
    exit 2
fi

MODEL_EXECUTABLE="${1:-${HIL_Z_MODEL_EXECUTABLE:-}}"
if [ -z "$MODEL_EXECUTABLE" ]; then
    usage
    exit 2
fi
case "$MODEL_EXECUTABLE" in
    /*) ;;
    *) echo "ERROR: model executable path must be absolute" >&2; exit 2 ;;
esac
[ -f "$MODEL_EXECUTABLE" ] || {
    echo "ERROR: model executable does not exist: $MODEL_EXECUTABLE" >&2
    exit 2
}
[ -x "$MODEL_EXECUTABLE" ] || {
    echo "ERROR: model executable is not executable: $MODEL_EXECUTABLE" >&2
    exit 2
}
MODEL_EXECUTABLE="$(readlink -f -- "$MODEL_EXECUTABLE")"

PYTHON_COMMAND="${HIL_Z_PYTHON:-python3}"
command -v "$PYTHON_COMMAND" >/dev/null 2>&1 || {
    echo "ERROR: Python command not found: $PYTHON_COMMAND" >&2
    exit 2
}
PYTHON_EXECUTABLE="$(readlink -f -- "$(command -v "$PYTHON_COMMAND")")"
if ! "$PYTHON_EXECUTABLE" -c \
        'import sys; raise SystemExit(0 if sys.version_info[:3] == (3, 6, 9) else 1)'; then
    echo "ERROR: target Python must be exactly 3.6.9" >&2
    exit 2
fi

for required_file in "$DEBUG_MAIN" "$CONFIG_FILE" "$MISSION_FILE" "$STOP_SCRIPT"; do
    [ -f "$required_file" ] || {
        echo "ERROR: required file is missing: $required_file" >&2
        exit 2
    }
done

TARGET="$(cd "$ROOT/python_services" && "$PYTHON_EXECUTABLE" -c \
    'import sys, debug_main; config = debug_main.load_config(); h, p = debug_main.get_debug_target(config); mission = debug_main.load_mission(sys.argv[1]); debug_main._bridge_waypoints(mission); debug_main._Runtime(); print("{}:{}".format(h, p))' \
    "$MISSION_FILE")"
if [ "$TARGET" != "$EXPECTED_TARGET" ]; then
    echo "ERROR: debug target must be $EXPECTED_TARGET; config resolved to $TARGET" >&2
    exit 2
fi

mkdir -p "$RUN_DIR"
if ! mkdir "$RUN_LOCK" 2>/dev/null; then
    echo "ERROR: another Z debug start/run owns $RUN_LOCK" >&2
    exit 2
fi

for pid_file in "$RUN_DIR/model.pid" "$RUN_DIR/debug.pid"; do
    if [ -f "$pid_file" ]; then
        rmdir "$RUN_LOCK"
        echo "ERROR: a recorded Z debug run exists; use scripts/stop_z_debug.sh first" >&2
        exit 2
    fi
done

MODEL_PID=""
DEBUG_PID=""

pid_executable_is() {
    pid="$1"
    expected="$2"
    [ -e "/proc/$pid/exe" ] &&
        [ "$(readlink -f -- "/proc/$pid/exe")" = "$expected" ]
}

pid_has_argument() {
    pid="$1"
    expected="$2"
    [ -r "/proc/$pid/cmdline" ] &&
        tr '\000' '\n' <"/proc/$pid/cmdline" | grep -Fqx -- "$expected"
}

process_start_token() {
    pid="$1"
    [ -r "/proc/$pid/stat" ] || return 1
    stat_line="$(sed -n '1p' "/proc/$pid/stat")"
    stat_fields="${stat_line##*) }"
    printf '%s\n' "$stat_fields" | awk '{print $20}'
}

cleanup_partial_start() {
    status="$?"
    trap - EXIT INT TERM
    if "$STOP_SCRIPT"; then
        echo "ERROR: Z debug startup failed; owned partial processes were stopped" >&2
    else
        echo "ERROR: partial cleanup could not stop every owned process; PID records retained" >&2
    fi
    [ "$status" -ne 0 ] || status=1
    exit "$status"
}
trap cleanup_partial_start EXIT INT TERM

printf '%s\n' "$MODEL_EXECUTABLE" >"$RUN_DIR/model.path"
printf '%s\n' "$PYTHON_EXECUTABLE" >"$RUN_DIR/python.path"

echo "UE4 target: $EXPECTED_TARGET"
"$MODEL_EXECUTABLE" >"$RUN_DIR/model.log" 2>&1 &
MODEL_PID="$!"
MODEL_START="$(process_start_token "$MODEL_PID")" || {
    echo "ERROR: cannot record model process identity" >&2
    exit 1
}
printf '%s %s\n' "$MODEL_PID" "$MODEL_START" >"$RUN_DIR/model.pid"
sleep 1
kill -0 "$MODEL_PID" 2>/dev/null || {
    echo "ERROR: model exited during startup; inspect $RUN_DIR/model.log" >&2
    exit 1
}

"$PYTHON_EXECUTABLE" "$ROOT/python_services/debug_main.py" \
    >"$RUN_DIR/debug.log" 2>&1 &
DEBUG_PID="$!"
DEBUG_START="$(process_start_token "$DEBUG_PID")" || {
    echo "ERROR: cannot record debug process identity" >&2
    exit 1
}
printf '%s %s\n' "$DEBUG_PID" "$DEBUG_START" >"$RUN_DIR/debug.pid"
sleep 1
kill -0 "$DEBUG_PID" 2>/dev/null || {
    echo "ERROR: debug service exited during startup; inspect $RUN_DIR/debug.log" >&2
    exit 1
}

trap - EXIT INT TERM
echo "Started model PID $MODEL_PID, then no-WebSocket debug PID $DEBUG_PID."
echo "Logs and PID records: $RUN_DIR"
echo "Stop with: $ROOT/scripts/stop_z_debug.sh"
