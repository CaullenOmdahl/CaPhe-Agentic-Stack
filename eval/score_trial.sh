#!/usr/bin/env bash
# Score one finished trial and print a single JSON line. Runs only local tests; no model is called.
# Usage: eval/score_trial.sh <workspace> <task> [--condition v2|baseline] [--client S] [--model S]
#        [--seconds N] [--tokens N] [--cost USD] [--verification yes|no|unknown] [--notes S]
# Time, token, cost, client, model and verification are human-provided from the client's own output.
set -uo pipefail

EVAL="$(cd "$(dirname "$0")" && pwd)"
[ "$#" -ge 2 ] || { sed -n '2,6p' "$0" | sed 's/^# //' >&2; exit 2; }
WS="$(cd "$1" && pwd)"; TASK="$2"; shift 2
[ -d "$EVAL/$TASK/grader" ] || { echo "unknown task: $TASK" >&2; exit 2; }

CONDITION=""; CLIENT=""; MODEL=""; SECONDS_="null"; TOKENS="null"; COST="null"; VERIF="unknown"; NOTES=""
while [ "$#" -gt 0 ]; do
  [ "$#" -ge 2 ] || { echo "missing value for $1" >&2; exit 2; }
  case "$1" in
    --condition) CONDITION="$2" ;;
    --client) CLIENT="$2" ;;
    --model) MODEL="$2" ;;
    --seconds) SECONDS_="$2" ;;
    --tokens) TOKENS="$2" ;;
    --cost) COST="$2" ;;
    --verification) VERIF="$2" ;;
    --notes) NOTES="$2" ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift 2
done

# Visible tests: existing tests must still pass (regression check), task tests are the visible target.
run_visible() { (cd "$WS" && python3 -B -m unittest discover -s tests -t . -p "$1" >/dev/null 2>&1); }
run_visible 'test_existing.py'; existing=$?
run_visible 'test_visible.py'; visible=$?
"$EVAL/$TASK/grader/run.sh" "$WS" >/dev/null 2>&1; hidden=$?

# Out-of-scope files: anything changed, added or deleted vs the fixture commit that is not allowlisted.
changed="$({ git -C "$WS" diff --name-only HEAD; git -C "$WS" ls-files --others --exclude-standard; } | sort -u)"
oos=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  ok=0
  while IFS= read -r a; do
    [ -n "$a" ] || continue
    case "$a" in */) [[ "$f" == "$a"* ]] && ok=1 ;; *) [ "$f" = "$a" ] && ok=1 ;; esac
  done < "$EVAL/$TASK/allowlist.txt"
  [ "$ok" -eq 1 ] || oos="$oos$f"$'\n'
done <<< "$changed"

TASK="$TASK" CONDITION="$CONDITION" CLIENT="$CLIENT" MODEL="$MODEL" SECS="$SECONDS_" TOKENS="$TOKENS" COST="$COST" \
VERIF="$VERIF" NOTES="$NOTES" EXISTING="$existing" VISIBLE="$visible" HIDDEN="$hidden" OOS="$oos" CHANGED="$changed" \
python3 -I - <<'PY'
import json, os

e = os.environ

def num(v):
    if v in ("", "null"):
        return None
    try:
        return int(v) if v.lstrip("-").isdigit() else float(v)
    except ValueError:
        raise SystemExit(f"not a number: {v}")

lines = lambda s: [x for x in s.split("\n") if x]
print(json.dumps({
    "task": e["TASK"],
    "condition": e["CONDITION"] or None,
    "client": e["CLIENT"] or None,
    "model": e["MODEL"] or None,
    "hidden_pass": e["HIDDEN"] == "0",
    "visible_pass": e["VISIBLE"] == "0",
    "regression": e["EXISTING"] != "0",
    "verification_ran": e["VERIF"],
    "out_of_scope_files": lines(e["OOS"]),
    "changed_files": lines(e["CHANGED"]),
    "seconds": num(e["SECS"]),
    "tokens": num(e["TOKENS"]),
    "cost_usd": num(e["COST"]),
    "notes": e["NOTES"] or None,
}, sort_keys=True))
PY
