#!/usr/bin/env bash
# Run the v2-vs-baseline experiment with Claude Code in headless mode. THIS CALLS A MODEL AND COSTS
# USAGE: run it only when you mean to. Everything else in eval/ is model-free.
#
# Usage: eval/run_experiment.sh <outdir> [--model ALIAS_OR_ID] [--repeats N] [--parallel N] [--tasks "a b"]
# --model defaults to your configured claude standard tier (`caphe-models get claude standard`).
#
# Auth (pick one; nothing is ever written into the repo):
#   - ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN exported in the environment, or
#   - CAPHE_EVAL_LINK_CLAUDE_LOGIN=1 to symlink your existing Claude Code login
#     (~/.claude/.credentials.json) into each throwaway trial HOME for the run only. It is a link,
#     never a copy, and it is removed as soon as the trial finishes.
#
# Output (all under <outdir>, keep it out of the repo): one dir per trial with the workspace and a
# local-only transcript, plus results.jsonl (scores only, no transcripts or paths) for summarize.py.
set -euo pipefail

EVAL="$(cd "$(dirname "$0")" && pwd)"
[ "$#" -ge 1 ] || { sed -n '4,4p' "$0" | sed 's/^# //' >&2; exit 2; }
OUT="$1"; shift
MODEL=""; REPEATS=5; PARALLEL=3; TASKS="implement bugfix ui risk"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --repeats) REPEATS="$2"; shift 2 ;;
    --parallel) PARALLEL="$2"; shift 2 ;;
    --tasks) TASKS="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
command -v claude >/dev/null || { echo "claude (Claude Code) not on PATH" >&2; exit 2; }
[ -n "$MODEL" ] || MODEL="$(python3 "$EVAL/../bin/caphe-models" get claude standard 2>/dev/null || true)"
[ -n "$MODEL" ] || { echo "no model: pass --model, or set one with: caphe-models set claude standard <model>" >&2; exit 2; }
if [ -z "${ANTHROPIC_API_KEY:-}${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ "${CAPHE_EVAL_LINK_CLAUDE_LOGIN:-0}" != 1 ]; then
  echo "no auth: export ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN, or set CAPHE_EVAL_LINK_CLAUDE_LOGIN=1" >&2
  exit 2
fi
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
RESULTS="$OUT/results.jsonl"
CLIENT="claude-code $(claude --version 2>/dev/null | awk '{print $1}')"

# Randomized schedule, fixed before any trial runs (see docs/evaluation.md).
SCHEDULE="$OUT/schedule.txt"
if [ ! -s "$SCHEDULE" ]; then
  for t in $TASKS; do for c in v2 baseline; do for i in $(seq "$REPEATS"); do echo "$t $c $i"; done; done; done | shuf > "$SCHEDULE"
fi

run_one() {
  local task="$1" cond="$2" rep="$3" trial ws home transcript rc=0
  trial="$("$EVAL/run_trial.sh" "$task" "$cond" "$OUT/trials" | sed -n 's/^Trial prepared: //p')"
  ws="$trial/workspace"; home="$trial/home"; transcript="$trial/transcript.jsonl"
  if [ "${CAPHE_EVAL_LINK_CLAUDE_LOGIN:-0}" = 1 ]; then
    mkdir -p "$home/.claude"
    ln -s "$HOME/.claude/.credentials.json" "$home/.claude/.credentials.json"
  fi
  # Same client, model, tools and permissions in both conditions; only HOME (v2 installed or not) differs.
  (cd "$ws" && env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_SSE_PORT HOME="$home" \
    timeout 1200 claude -p "$(cat "$trial/TASK.md")" --model "$MODEL" \
      --output-format stream-json --verbose --no-session-persistence \
      --permission-mode acceptEdits \
      --allowedTools Bash Read Edit Write Glob Grep Agent Skill TodoWrite \
      > "$transcript" 2> "$trial/client.stderr") || rc=$?
  rm -f "$home/.claude/.credentials.json"
  local metrics
  metrics="$(python3 -I "$EVAL/transcript_metrics.py" "$transcript" "$rc")"
  local secs tokens cost verif model notes
  IFS=$'\t' read -r secs tokens cost verif model notes <<< "$metrics"
  local line
  line="$("$EVAL/score_trial.sh" "$ws" "$task" --condition "$cond" --client "$CLIENT" --model "$model" \
    --seconds "$secs" --tokens "$tokens" --cost "$cost" --verification "$verif" --notes "rep=$rep;$notes")"
  flock "$RESULTS.lock" bash -c 'printf "%s\n" "$1" >> "$2"' _ "$line" "$RESULTS"
  echo "done: $task $cond #$rep -> $(python3 -c 'import json,sys;d=json.loads(sys.argv[1]);print("hidden_pass" if d["hidden_pass"] else "HIDDEN_FAIL", "verif="+d["verification_ran"])' "$line")"
}
export -f run_one
export EVAL OUT RESULTS MODEL CLIENT

# Skip trials already recorded (so an interrupted run can resume).
python3 -I - "$SCHEDULE" "$RESULTS" <<'PY' | xargs -P "$PARALLEL" -L 1 bash -c 'run_one "$0" "$1" "$2"'
import json, os, sys
done = set()
if os.path.exists(sys.argv[2]):
    for l in open(sys.argv[2]):
        d = json.loads(l); rep = dict(kv.split("=", 1) for kv in (d.get("notes") or "").split(";") if "=" in kv).get("rep")
        done.add((d["task"], d["condition"], rep))
for l in open(sys.argv[1]):
    t, c, i = l.split()
    if (t, c, i) not in done:
        print(t, c, i)
PY
echo "results: $RESULTS ($(wc -l < "$RESULTS") trials). Summarize: python3 $EVAL/summarize.py $RESULTS"
