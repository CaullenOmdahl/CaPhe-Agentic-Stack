#!/usr/bin/env bash
# Initialize or refresh Strict Mode through the transactional implementation.
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -B "$SCRIPT_DIR/strict_init.py" "$@"
