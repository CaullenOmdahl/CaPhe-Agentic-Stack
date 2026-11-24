#!/usr/bin/env bash
# Hidden grader entry point: run.sh <workspace>. Exit 0 = pass. Needs node (no packages).
set -euo pipefail
command -v node >/dev/null || { echo "node is required for the ui grader" >&2; exit 2; }
exec node "$(dirname "$0")/check_ui.js" "$1"
