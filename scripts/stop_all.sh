#!/bin/bash
# Stop only the processes recorded by scripts/start_all.sh; never use broad
# name-pattern termination that could affect an unrelated production service.
set -euo pipefail

MODEL_NAME="${MODEL_NAME:-}"
if [ -n "${HIL_DEV_RUN_DIR:-}" ]; then
    RUN_DIR="$HIL_DEV_RUN_DIR"
elif [ -n "$MODEL_NAME" ]; then
    RUN_DIR="/tmp/hil_dev_${MODEL_NAME}"
else
    echo "ERROR: set MODEL_NAME or HIL_DEV_RUN_DIR."
    exit 2
fi

PID_FILE="$RUN_DIR/pids"
if [ ! -f "$PID_FILE" ]; then
    echo "No recorded development run at $RUN_DIR"
    exit 0
fi

while read -r pid role; do
    case "$pid" in
        ''|*[!0-9]*) echo "Ignoring invalid PID entry for $role" ;;
        *)
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid"
                echo "Stopped $role (PID $pid)"
            fi
            ;;
    esac
done < "$PID_FILE"
rm -f "$PID_FILE"
