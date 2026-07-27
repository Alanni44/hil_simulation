#!/usr/bin/env bash
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CORE="${1:?usage: start_all.sh /absolute/path/to/verified_model_rt}"
case "$CORE" in /*) ;; *) echo "Core path must be absolute" >&2; exit 2;; esac
[ -x "$CORE" ] || { echo "Verified core is not executable: $CORE" >&2; exit 2; }
mkdir -p "$ROOT/runtime"
"$CORE" >"$ROOT/runtime/core.log" 2>&1 & echo $! >"$ROOT/runtime/core.pid"
(cd "$ROOT/python_services" && python3 main.py) >"$ROOT/runtime/python.log" 2>&1 & echo $! >"$ROOT/runtime/python.pid"
echo "Started one core and Python services; use stop_all.sh to stop these PIDs."
