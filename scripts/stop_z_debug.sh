#!/usr/bin/env bash
# Stop only processes whose PID and command still match start_z_debug.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/runtime/z_debug"
RUN_LOCK="$RUN_DIR/run.lock"
LOCK_OWNER_FILE="$RUN_LOCK/owner.token"
LOCK_PHASE_FILE="$RUN_LOCK/phase"
DEBUG_MAIN="$ROOT/python_services/debug_main.py"
MODEL_PATH_FILE="$RUN_DIR/model.path"
PYTHON_PATH_FILE="$RUN_DIR/python.path"
MODEL_PID_FILE="$RUN_DIR/model.pid"
DEBUG_PID_FILE="$RUN_DIR/debug.pid"
STOP_FAILED=0
REQUESTED_OWNER_TOKEN="${HIL_Z_LOCK_OWNER_TOKEN:-}"
LOCK_OWNER_TOKEN=""
LOCK_PHASE=""

if [ -f "$LOCK_OWNER_FILE" ]; then
    LOCK_OWNER_TOKEN="$(sed -n '1p' "$LOCK_OWNER_FILE")"
fi
if [ -f "$LOCK_PHASE_FILE" ]; then
    LOCK_PHASE="$(sed -n '1p' "$LOCK_PHASE_FILE")"
fi

STARTUP_CLEANUP_AUTHORIZED=0
if [ -n "$REQUESTED_OWNER_TOKEN" ] &&
        { [ -z "$LOCK_OWNER_TOKEN" ] ||
          [ "$REQUESTED_OWNER_TOKEN" = "$LOCK_OWNER_TOKEN" ]; }; then
    STARTUP_CLEANUP_AUTHORIZED=1
fi

if [ -d "$RUN_LOCK" ] && [ "$LOCK_PHASE" != "running" ] &&
        [ "$STARTUP_CLEANUP_AUTHORIZED" -ne 1 ]; then
    echo "ERROR: an active Z debug startup owns $RUN_LOCK; lock not released" >&2
    exit 1
fi

release_run_lock() {
    [ -d "$RUN_LOCK" ] || return 0
    if [ "$LOCK_PHASE" != "running" ] &&
            [ "$STARTUP_CLEANUP_AUTHORIZED" -ne 1 ]; then
        echo "ERROR: refusing to release startup-owned lock $RUN_LOCK" >&2
        STOP_FAILED=1
        return 0
    fi
    rm -f "$LOCK_PHASE_FILE" "$LOCK_OWNER_FILE"
    rmdir "$RUN_LOCK" 2>/dev/null || {
        echo "ERROR: could not release scoped run lock $RUN_LOCK" >&2
        STOP_FAILED=1
    }
}

if [ ! -f "$MODEL_PID_FILE" ] && [ ! -f "$DEBUG_PID_FILE" ]; then
    rm -f "$MODEL_PATH_FILE" "$PYTHON_PATH_FILE"
    release_run_lock
    echo "No recorded Z debug run at $RUN_DIR"
    exit "$STOP_FAILED"
fi

MODEL_EXECUTABLE=""
PYTHON_EXECUTABLE=""
[ ! -f "$MODEL_PATH_FILE" ] || MODEL_EXECUTABLE="$(sed -n '1p' "$MODEL_PATH_FILE")"
[ ! -f "$PYTHON_PATH_FILE" ] || PYTHON_EXECUTABLE="$(sed -n '1p' "$PYTHON_PATH_FILE")"

pid_executable_is() {
    pid="$1"
    expected="$2"
    [ -n "$expected" ] && [ -e "/proc/$pid/exe" ] &&
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
    stat_line="$(sed -n '1p' "/proc/$pid/stat")" || return 1
    stat_fields="${stat_line##*) }"
    start_token="$(printf '%s\n' "$stat_fields" | awk '{print $20}')" || return 1
    case "$start_token" in
        ''|*[!0-9]*) return 1 ;;
    esac
    printf '%s\n' "$start_token"
}

pid_is_owned() {
    role="$1"
    pid="$2"
    if [ "$role" = "debug" ]; then
        pid_executable_is "$pid" "$PYTHON_EXECUTABLE" &&
            pid_has_argument "$pid" "$DEBUG_MAIN"
    else
        pid_executable_is "$pid" "$MODEL_EXECUTABLE" ||
            pid_has_argument "$pid" "$MODEL_EXECUTABLE"
    fi
}

recorded_process_is_alive() {
    pid="$1"
    recorded_start="$2"
    kill -0 "$pid" 2>/dev/null &&
        [ "$(process_start_token "$pid" 2>/dev/null)" = "$recorded_start" ]
}

stop_recorded() {
    role="$1"
    pid_file="$2"
    [ -f "$pid_file" ] || return 0
    pid=""
    recorded_start=""
    extra=""
    read -r pid recorded_start extra <"$pid_file" || true
    case "$pid" in
        ''|*[!0-9]*)
            echo "ERROR: invalid $role PID record; left in place: $pid_file" >&2
            STOP_FAILED=1
            return 0
            ;;
    esac
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$pid_file"
        echo "Removed exited $role PID record ($pid)"
        return 0
    fi
    case "$recorded_start" in
        ''|*[!0-9]*)
            echo "ERROR: invalid $role start token; left in place: $pid_file" >&2
            STOP_FAILED=1
            return 0
            ;;
    esac
    if [ -n "$extra" ]; then
        echo "ERROR: unexpected data in $role PID record; left in place: $pid_file" >&2
        STOP_FAILED=1
        return 0
    fi
    current_start="$(process_start_token "$pid" 2>/dev/null || true)"
    if [ "$current_start" != "$recorded_start" ]; then
        rm -f "$pid_file"
        echo "Removed stale $role PID record after PID reuse ($pid); replacement not signaled"
        return 0
    fi
    if ! pid_is_owned "$role" "$pid"; then
        echo "ERROR: PID $pid no longer matches owned $role command; not signaled" >&2
        STOP_FAILED=1
        return 0
    fi
    if ! kill "$pid" 2>/dev/null; then
        if ! recorded_process_is_alive "$pid" "$recorded_start"; then
            rm -f "$pid_file"
            echo "Removed exited $role PID record after signal race ($pid)"
            return 0
        fi
        echo "ERROR: could not signal owned $role PID $pid; record retained" >&2
        STOP_FAILED=1
        return 0
    fi
    attempts=0
    while recorded_process_is_alive "$pid" "$recorded_start" &&
            [ "$attempts" -lt 100 ]; do
        sleep 0.1
        attempts=$((attempts + 1))
    done
    if recorded_process_is_alive "$pid" "$recorded_start"; then
        echo "ERROR: owned $role PID $pid did not exit after SIGTERM; record retained" >&2
        STOP_FAILED=1
        return 0
    fi
    rm -f "$pid_file"
    echo "Stopped owned $role PID $pid"
}

stop_recorded debug "$DEBUG_PID_FILE"
stop_recorded model "$MODEL_PID_FILE"

if [ ! -f "$DEBUG_PID_FILE" ] && [ ! -f "$MODEL_PID_FILE" ]; then
    rm -f "$MODEL_PATH_FILE" "$PYTHON_PATH_FILE"
    release_run_lock
fi
exit "$STOP_FAILED"
