#!/bin/bash
echo "=== Stopping HIL Services ==="
pkill -f "python3 main.py"
pkill -f "hil_core"
echo "=== Stopped ==="
