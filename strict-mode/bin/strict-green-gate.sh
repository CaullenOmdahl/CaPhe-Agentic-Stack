#!/usr/bin/env bash
# Strict Mode v2 gate. See ADR-0001.
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MARKER_REL=.agent/.strict-mode
MARKER="$ROOT/$MARKER_REL"
MARKER_TRACKED=0
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 &&
   git -C "$ROOT" ls-files --error-unmatch -- "$MARKER_REL" >/dev/null 2>&1; then
  MARKER_TRACKED=1
fi
if [ -f "$MARKER" ] && [ "$MARKER_TRACKED" -eq 0 ] && head -1 "$MARKER" | grep -qx 'off'; then
  echo "STRICT MODE: OFF (user-disabled)"
  exit 0
fi
if [ -f "$MARKER" ] && [ "$MARKER_TRACKED" -eq 1 ] && head -1 "$MARKER" | grep -qx 'off'; then
  echo "STRICT MODE: ignoring tracked disable marker; remove $MARKER_REL from the Git index" >&2
fi

MODE=affected
if [ "${1:-}" = "--mode" ]; then
  MODE="${2:-}"
  shift 2
fi
case "$MODE" in
  affected|completion|full|plan) ;;
  *) echo "usage: strict-green-gate.sh [--mode affected|completion|full|plan]" >&2; exit 2 ;;
esac

if [ "${STRICT_MODE:-}" = "prototype" ] && [ "$MODE" != "completion" ]; then
  echo "STRICT MODE prototype: affected failures are advisory and logged"
  python3 "$SCRIPT_DIR/strict_gate.py" --mode "$MODE" "$@" || true
  exit 0
fi

exec python3 "$SCRIPT_DIR/strict_gate.py" --mode "$MODE" "$@"
