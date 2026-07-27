#!/usr/bin/env bash
set -eu
echo "Hot reload and rollback are intentionally unsupported by the HIL runtime." >&2
echo "Submit a fully verified deploy_package request; the supervisor stops the old core before starting one new core." >&2
exit 2
