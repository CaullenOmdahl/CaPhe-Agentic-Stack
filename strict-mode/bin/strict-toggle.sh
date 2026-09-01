#!/usr/bin/env bash
# strict-mode · enable / disable strict mode for THIS repo.
#
#   strict-toggle.sh status      # show current state
#   strict-toggle.sh on          # (re)enable enforcement
#   strict-toggle.sh off         # DISABLE — USER-ONLY (interactive confirmation required)
#
# DISABLING IS A USER-ONLY ACTION. Agents must NEVER disable strict mode: `off` refuses to
# run without an interactive terminal + a typed confirmation, so a headless agent cannot
# flip it. If an agent thinks the gate should be relaxed, it must STOP and ask the user.
# (For a one-off throwaway spike, use STRICT_MODE=prototype on a single command instead.)
set -uo pipefail
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd); cd "$ROOT" || exit 1
mkdir -p .agent
MARK=.agent/.strict-mode

is_off() { [ -f "$MARK" ] && head -1 "$MARK" 2>/dev/null | grep -q '^off'; }

case "${1:-status}" in
  on|enable)
    printf 'on\n# re-enabled %s\n' "$(date)" > "$MARK"
    echo "STRICT MODE: ON (enforced) — $ROOT" ;;
  off|disable)
    if [ ! -t 0 ] || [ ! -t 1 ]; then
      echo "REFUSED: disabling strict mode is USER-ONLY and needs an interactive terminal." >&2
      echo "Agents must not disable strict mode — ask the user to run: strict-toggle.sh off" >&2
      exit 4
    fi
    printf 'This DISABLES strict-mode enforcement for %s.\nType DISABLE to confirm: ' "$ROOT" > /dev/tty
    read -r ans < /dev/tty
    [ "$ans" = "DISABLE" ] || { echo "aborted (no change)."; exit 1; }
    printf 'off\n# disabled by user %s\n' "$(date)" > "$MARK"
    echo "STRICT MODE: OFF — gates relaxed for $ROOT. Re-enable any time: strict-toggle.sh on" ;;
  status)
    if is_off; then echo "STRICT MODE: OFF (user-disabled — $MARK)"; else echo "STRICT MODE: ON (enforced)"; fi ;;
  *) echo "usage: strict-toggle.sh on|off|status" >&2; exit 2 ;;
esac
