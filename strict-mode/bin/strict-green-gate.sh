#!/usr/bin/env bash
# Strict Mode v3 gate. See ADR-0004.
set -euo pipefail

# Clear calling-hook repository state before selecting the root or its disable marker.
# Keep global Git configuration and transport settings available to declared checks.
unset GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_CONFIG GIT_CONFIG_COUNT \
  GIT_CONFIG_PARAMETERS GIT_DIR GIT_GRAFT_FILE GIT_IMPLICIT_WORK_TREE GIT_INDEX_FILE \
  GIT_NO_REPLACE_OBJECTS GIT_OBJECT_DIRECTORY GIT_PREFIX GIT_REPLACE_REF_BASE \
  GIT_SHALLOW_FILE GIT_WORK_TREE
while IFS= read -r CAPHE_GATE_GIT_ENV_NAME; do
  if [[ "$CAPHE_GATE_GIT_ENV_NAME" =~ ^GIT_[A-Z0-9_]+$ ]]; then
    unset "$CAPHE_GATE_GIT_ENV_NAME"
  fi
done < <(git rev-parse --local-env-vars 2>/dev/null || true)
unset CAPHE_GATE_GIT_ENV_NAME

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
MODE_SEEN=0
ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode|--mode=*)
      if [ "$MODE_SEEN" -eq 1 ]; then
        echo "strict gate: --mode may be supplied only once" >&2; exit 2
      fi
      MODE_SEEN=1
      if [ "$1" = --mode ]; then
        if [ "$#" -lt 2 ]; then echo "strict gate: --mode needs a value" >&2; exit 2; fi
        MODE="$2"; shift 2
      else
        MODE="${1#--mode=}"; shift
      fi
      ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
case "$MODE" in
  affected|completion|full|plan) ;;
  *) echo "usage: strict-green-gate.sh [--mode affected|completion|full|plan]" >&2; exit 2 ;;
esac

if [ "${STRICT_MODE:-}" = "prototype" ] && [ "$MODE" = "affected" ]; then
  echo "STRICT MODE prototype: affected failures are advisory and logged"
  RESULT=0
  python3 "$SCRIPT_DIR/strict_gate.py" --mode "$MODE" ${ARGS[@]+"${ARGS[@]}"} || RESULT=$?
  # The planner reserves 1 for failed checks and 2 for invalid configuration.
  case "$RESULT" in 0|1) exit 0 ;; *) exit "$RESULT" ;; esac
fi

exec python3 "$SCRIPT_DIR/strict_gate.py" --mode "$MODE" ${ARGS[@]+"${ARGS[@]}"}
