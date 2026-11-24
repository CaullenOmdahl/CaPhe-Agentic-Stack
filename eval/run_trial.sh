#!/usr/bin/env bash
# Prepare one trial. Never starts a model or a client: it only builds the workspace and HOME and
# prints the commands a human runs. Usage: eval/run_trial.sh <task> <v2|baseline> <outdir>
set -euo pipefail

EVAL="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$EVAL")"
[ "$#" -eq 3 ] || { sed -n '2,3p' "$0" | sed 's/^# //' >&2; exit 2; }
TASK="$1"; COND="$2"; OUT="$3"

[ -d "$EVAL/$TASK/fixture" ] || { echo "unknown task: $TASK" >&2; exit 2; }
case "$COND" in v2|baseline) ;; *) echo "condition must be v2 or baseline" >&2; exit 2 ;; esac

mkdir -p "$OUT"
TRIAL="$(cd "$OUT" && pwd)/$TASK-$COND-$(date +%Y%m%dT%H%M%S)-$$"
WS="$TRIAL/workspace"
FAKE_HOME="$TRIAL/home"
mkdir -p "$WS" "$FAKE_HOME"

# Fresh workspace from the fixture only. The hidden grader (eval/<task>/grader) and the reference
# solution never enter it; score_trial.sh reads the grader from the eval kit at scoring time.
cp -R "$EVAL/$TASK/fixture/." "$WS/"
git -C "$WS" init -q
printf '__pycache__/\n*.pyc\n' >> "$WS/.git/info/exclude"
git -C "$WS" add -A
git -C "$WS" -c user.name=eval -c user.email=eval@example.invalid commit -q -m "fixture: $TASK"
cp "$EVAL/$TASK/TASK.md" "$TRIAL/TASK.md"

if [ "$COND" = "v2" ]; then
  # Throwaway HOME: the installer writes only there. XDG overrides are cleared so nothing leaks to the real HOME.
  (cd "$REPO" && env -u XDG_CONFIG_HOME -u XDG_STATE_HOME -u XDG_CACHE_HOME HOME="$FAKE_HOME" ./install.sh) > "$TRIAL/install.log" 2>&1
fi

cat <<EOF
Trial prepared: $TRIAL
  task=$TASK condition=$COND
  workspace: $WS
  HOME:      $FAKE_HOME ($( [ "$COND" = v2 ] && echo "v2 installed, see install.log" || echo "clean, no v2" ))

1) Authenticate the client the same way in BOTH conditions (for example an exported API key
   environment variable). Never write credentials into the trial directory or the repo.
2) Run ONE of these (fix the same model and flags for every trial of the experiment; record the
   model the client reports):

   cd "$WS" && time env HOME="$FAKE_HOME" claude -p "\$(cat "$TRIAL/TASK.md")" --model <model>
   cd "$WS" && time env HOME="$FAKE_HOME" codex exec --model <model> "\$(cat "$TRIAL/TASK.md")"

3) Note wall time, total tokens and cost from the client's own usage output, whether the agent ran
   the required verification, then score:

   $EVAL/score_trial.sh "$WS" $TASK --condition $COND --client <name+version> --model "<model as reported by the client>" \\
     --seconds <s> --tokens <n> --cost <usd> --verification yes|no|unknown >> results.jsonl
EOF
