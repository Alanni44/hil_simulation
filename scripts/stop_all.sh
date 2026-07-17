#!/bin/bash
echo "=== Stopping HIL Services ==="
pkill -f "python3 main.py"
pkill -f "hil_core"
rm -f /tmp/model_*.json /tmp/model_*.signal
echo "=== Stopped ==="