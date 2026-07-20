#!/bin/bash
echo "=== Stopping HIL Services ==="
pkill -f "python3 main.py"
pkill -f "_rt"
echo "=== Stopped ==="
