#!/bin/bash
# Development launcher.  Production uses deploy/systemd/ and never runs this
# foreground helper as root.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_NAME="${MODEL_NAME:-}"
SLX_PATH="${SLX_PATH:-}"

if [ -z "$MODEL_NAME" ]; then
    echo "ERROR: MODEL_NAME is required (for example: MODEL_NAME=my_uav)"
    exit 2
fi

RUN_DIR="${HIL_DEV_RUN_DIR:-/tmp/hil_dev_${MODEL_NAME}}"
PID_FILE="$RUN_DIR/pids"
SIGNAL_FILE="$RUN_DIR/${MODEL_NAME}.signal"

if [ -f "$PID_FILE" ]; then
    while read -r pid _; do
        if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
            echo "ERROR: an existing development run is recorded in $RUN_DIR"
            echo "Run scripts/stop_all.sh with HIL_DEV_RUN_DIR=$RUN_DIR first."
            exit 1
        fi
    done < "$PID_FILE"
fi
mkdir -p "$RUN_DIR"

if [ "${HIL_SKIP_BUILD:-0}" != "1" ]; then
    if [ -z "$SLX_PATH" ] || [ ! -f "$SLX_PATH" ]; then
        echo "ERROR: SLX_PATH must name an existing .slx file (or set HIL_SKIP_BUILD=1)."
        exit 2
    fi
    echo "Building immutable archive for $MODEL_NAME ..."
    HIL_MODEL_READY_SIGNAL="$SIGNAL_FILE" \
        "$ROOT/scripts/build_model.py" "$SLX_PATH" "$MODEL_NAME"
fi

EXE="$ROOT/models/active/$MODEL_NAME/executable/${MODEL_NAME}_rt"
if [ ! -x "$EXE" ]; then
    echo "ERROR: active archived executable is missing: $EXE"
    exit 1
fi

CORE_PID=''
PY_PID=''
cleanup() {
    local status=$?
    trap - EXIT INT TERM
    [ -n "$CORE_PID" ] && kill "$CORE_PID" 2>/dev/null || true
    [ -n "$PY_PID" ] && kill "$PY_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    rm -f "$PID_FILE"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

(
    cd "$ROOT/python_services"
    HIL_MODEL_READY_SIGNAL="$SIGNAL_FILE" HIL_MODEL_NAME="$MODEL_NAME" exec python3 main.py
) >"$RUN_DIR/python_services.log" 2>&1 &
PY_PID=$!

HIL_MODEL_READY_SIGNAL="$SIGNAL_FILE" HIL_MODEL_NAME="$MODEL_NAME" \
    "$EXE" >"$RUN_DIR/core.log" 2>&1 &
CORE_PID=$!

printf '%s core\n%s python\n' "$CORE_PID" "$PY_PID" > "$PID_FILE"
sleep 1
if ! kill -0 "$CORE_PID" 2>/dev/null || ! kill -0 "$PY_PID" 2>/dev/null; then
    echo "ERROR: development services exited during startup; inspect $RUN_DIR/*.log"
    exit 1
fi

echo "HIL development services started"
echo "  model:  $MODEL_NAME"
echo "  core:   $CORE_PID"
echo "  python: $PY_PID"
echo "  logs:   $RUN_DIR"
echo "Use Ctrl+C or HIL_DEV_RUN_DIR=$RUN_DIR ./scripts/stop_all.sh to stop."

while kill -0 "$CORE_PID" 2>/dev/null && kill -0 "$PY_PID" 2>/dev/null; do
    sleep 1
done
echo "ERROR: a development service exited; inspect $RUN_DIR/*.log"
exit 1
