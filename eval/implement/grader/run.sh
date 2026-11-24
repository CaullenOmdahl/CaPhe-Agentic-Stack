#!/usr/bin/env bash
# Hidden grader entry point: run.sh <workspace>. Exit 0 = pass.
set -euo pipefail
WORKSPACE="$(cd "$1" && pwd)" exec python3 -B -m unittest discover -s "$(dirname "$0")" -p "test_hidden.py"
