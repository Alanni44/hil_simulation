#!/bin/bash
# Verify the C core's archive-to-archive execv handoff.  This intentionally
# changes the active pointer briefly, so it is disabled unless explicitly
# enabled by an operator.
set -euo pipefail

if [ "${HIL_HOT_RELOAD_TEST:-0}" != "1" ]; then
    echo "Refusing to run: set HIL_HOT_RELOAD_TEST=1 explicitly."
    exit 2
fi

MODEL_NAME="${1:?usage: test_hot_reload.sh <model_name> <current_build_id> <target_build_id>}"
CURRENT_BUILD_ID="${2:?usage: test_hot_reload.sh <model_name> <current_build_id> <target_build_id>}"
TARGET_BUILD_ID="${3:?usage: test_hot_reload.sh <model_name> <current_build_id> <target_build_id>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
READY_DIR="${HIL_MODEL_READY_DIR:-/tmp}"
ACTIVE_LINK="$ROOT/models/active/$MODEL_NAME"
CURRENT_EXE="$ROOT/models/registry/$MODEL_NAME/$CURRENT_BUILD_ID/executable/${MODEL_NAME}_rt"
TARGET_EXE="$ROOT/models/registry/$MODEL_NAME/$TARGET_BUILD_ID/executable/${MODEL_NAME}_rt"
LOG_FILE="${HIL_HOT_RELOAD_LOG:-/tmp/hil_hot_reload_${MODEL_NAME}_$$.log}"

if [[ ! "$MODEL_NAME" =~ ^[A-Za-z][A-Za-z0-9_]{0,63}$ ]]; then
    echo "Invalid model name"
    exit 2
fi
case "$CURRENT_BUILD_ID:$TARGET_BUILD_ID" in
    *[!A-Za-z0-9_:]* ) echo "Invalid build ID"; exit 2 ;;
esac
if [ "$CURRENT_BUILD_ID" = "$TARGET_BUILD_ID" ]; then
    echo "Current and target build IDs must differ"
    exit 2
fi
test -x "$CURRENT_EXE"
test -x "$TARGET_EXE"
test -L "$ACTIVE_LINK"

ORIGINAL_BUILD_ID="$(basename "$(readlink -f "$ACTIVE_LINK")")"
CORE_PID=''
RESTORE_NEEDED=0

activate() {
    PYTHONPATH="$ROOT/python_services" HIL_MODEL_READY_DIR="$READY_DIR" \
        python3 -c "import ws_server; print(ws_server._activate_archived_build('$MODEL_NAME', '$1'))"
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [ -n "$CORE_PID" ]; then
        kill "$CORE_PID" 2>/dev/null || true
        wait "$CORE_PID" 2>/dev/null || true
    fi
    if [ "$RESTORE_NEEDED" = "1" ]; then
        activate "$ORIGINAL_BUILD_ID" || status=1
    fi
    echo "Hot-reload log: $LOG_FILE"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Publishing the target signal before starting the current executable ensures
# its one-second update tick must perform a real execv, not just consume a
# self-signal.  The wrapper's FD_CLOEXEC support lets the target bind UDP.
activate "$TARGET_BUILD_ID"
RESTORE_NEEDED=1
HIL_MODEL_READY_SIGNAL="$READY_DIR/${MODEL_NAME}.signal" HIL_MODEL_NAME="$MODEL_NAME" \
    stdbuf -oL -eL "$CURRENT_EXE" >"$LOG_FILE" 2>&1 &
CORE_PID=$!

deadline=$((SECONDS + 10))
while [ "$SECONDS" -lt "$deadline" ]; do
    if [ "$(readlink -f "/proc/$CORE_PID/exe" 2>/dev/null || true)" = "$(readlink -f "$TARGET_EXE")" ]; then
        grep -F "[ModelRT] Hot-reload: execv" "$LOG_FILE"
        echo "PASS: hot reload switched PID $CORE_PID to $TARGET_EXE"
        exit 0
    fi
    if ! kill -0 "$CORE_PID" 2>/dev/null; then
        echo "Core exited before hot reload" >&2
        exit 1
    fi
    sleep 1
done

echo "Timed out waiting for hot reload" >&2
exit 1
