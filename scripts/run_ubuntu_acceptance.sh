#!/usr/bin/env bash
# Canonical one-command entry for the week-one Ubuntu HIL baseline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"
exec python3 scripts/run_week1_acceptance.py "$@"
