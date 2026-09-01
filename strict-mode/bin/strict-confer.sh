#!/usr/bin/env bash
# strict-mode · cross-agent second opinion — confer with the OTHER two agents (never self).
#   strict-confer.sh <host: claude|codex|agy> [--adversarial] [--save <label>] "<task/prompt>"
# Neutrality: pass the task/design, not your own conclusion. --adversarial frames a review
# ("find the strongest objection; recommend reject if it doesn't hold"). --save persists the
# peers' verbatim transcript to .agent/reviews/<utc>-<label>.md so the recorded verdict is
# AUDITABLE peer output — not a self-written checklist line (review of this very rule:
# self-attested compliance is theater). Stronger upgrade: a CI-isolated reviewer the primary
# agent can't reach 'done' without — see methodology.md.
#
# Concurrency: every invocation gets a unique run ID, an ephemeral run root, and per-peer
# working directories. Peer CLIs run in separate process sessions so timeouts kill their
# child processes. Set STRICT_CONFER_KEEP_RUN_DIR=1 to preserve the run root for debugging.
# Git snapshots contain only tracked regular files and staged regular additions; symlinks,
# gitlinks, and arbitrary untracked local files are not copied. Override reviewer models with
# STRICT_CONFER_CODEX_MODEL after verifying the requested models with the installed CLIs.
set -uo pipefail

HOST="${1:-}"; shift || true
ADV="" SAVE=""
while [ "${1:-}" ] && [ "${1:0:2}" = "--" ]; do
  case "$1" in
    --adversarial) ADV=$'You are an ADVERSARIAL reviewer. Find the STRONGEST objection to the following; if it does not hold up, recommend REJECT. Do not validate — try to break it. Cite specifics.\n\n'; shift ;;
    --save) SAVE="${2:-review}"; shift 2 ;;
    *) echo "unknown flag $1" >&2; exit 2 ;;
  esac
done
PROMPT="${ADV}${*:-}"
{ [ -z "$HOST" ] || [ -z "${*:-}" ]; } && { echo "usage: strict-confer.sh <claude|codex|agy> [--adversarial] [--save <label>] \"<task>\"" >&2; exit 2; }
PEER_TIMEOUT_SECONDS="${STRICT_CONFER_TIMEOUT_SECONDS:-600}"
AGY_MODEL="${STRICT_CONFER_AGY_MODEL:-gemini-3.7-flash-high}"
CODEX_MODEL="${STRICT_CONFER_CODEX_MODEL:-gpt-5.4}"
RUN_ID="${STRICT_CONFER_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM}"
SOURCE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ "${STRICT_CONFER_NO_SNAPSHOT:-0}" = "1" ]; then
  echo "strict-confer refuses live-workspace review; stage deliberate inputs for a bounded snapshot" >&2
  exit 2
fi
if ! git -C "$SOURCE_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "strict-confer snapshot mode requires a Git worktree" >&2
  exit 2
fi
RUN_ROOT_CREATED=0
if [ -n "${STRICT_CONFER_RUN_ROOT:-}" ]; then
  RUN_ROOT="$STRICT_CONFER_RUN_ROOT"
  mkdir -p "$RUN_ROOT" || exit 1
else
  RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/strict-confer.${RUN_ID}.XXXXXX")" || exit 1
  RUN_ROOT_CREATED=1
fi

cleanup_run_root() {
  if [ "$RUN_ROOT_CREATED" -eq 1 ] && [ "${STRICT_CONFER_KEEP_RUN_DIR:-0}" != "1" ]; then
    rm -rf "$RUN_ROOT"
  elif [ "${STRICT_CONFER_KEEP_RUN_DIR:-0}" = "1" ]; then
    echo "debug: kept strict-confer run dir: $RUN_ROOT" >&2
  fi
}
trap cleanup_run_root EXIT

# Each returns non-zero if the peer can't be reached or returns nothing — a review that did
# NOT happen must be LOUD, never silently treated as obtained.
run_isolated() {
  local peer
  peer="${1:-}"
  [ -n "$peer" ] || return 2
  shift
  local peer_dir
  peer_dir="$RUN_ROOT/$peer"
  mkdir -p "$peer_dir/tmp" || return 1
  local peer_cwd
  peer_cwd="$peer_dir/workspace"
  mkdir -p "$peer_cwd" || return 1
  local file_list
  file_list="$peer_dir/files.txt"
  git -C "$SOURCE_ROOT" ls-files --stage -z |
    while IFS= read -r -d '' index_entry; do
      index_meta=${index_entry%%$'\t'*}
      tracked_path=${index_entry#*$'\t'}
      index_mode=${index_meta%% *}
      case "$index_mode" in 100644|100755) ;; *) continue ;; esac
      if [ ! -L "$SOURCE_ROOT/$tracked_path" ] && [ -f "$SOURCE_ROOT/$tracked_path" ]; then
        printf '%s\0' "$tracked_path"
      fi
    done > "$file_list" || return 1
  rsync -a --from0 --files-from="$file_list" "$SOURCE_ROOT"/ "$peer_cwd"/ || return 1
  STRICT_CONFER_PEER="$peer" \
  STRICT_CONFER_RUN_ID="$RUN_ID" \
  STRICT_CONFER_RUN_ROOT="$RUN_ROOT" \
  STRICT_CONFER_CWD="$peer_cwd" \
  STRICT_CONFER_TIMEOUT_SECONDS="$PEER_TIMEOUT_SECONDS" \
  TMPDIR="$peer_dir/tmp" \
    python3 - "$@" <<'PY'
import os
import signal
import subprocess
import sys

args = sys.argv[1:]
cwd = os.environ["STRICT_CONFER_CWD"]
timeout = float(os.environ["STRICT_CONFER_TIMEOUT_SECONDS"])
child_env = os.environ.copy()
child_env.pop("STRICT_CONFER_SOURCE_ROOT", None)
child_env.pop("OLDPWD", None)
child_env["PWD"] = cwd

try:
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
except FileNotFoundError:
    sys.exit(127)

try:
    stdout, stderr = proc.communicate(timeout=timeout)
    if stderr:
        sys.stderr.write(stderr)
    if stdout:
        sys.stdout.write(stdout)
    sys.exit(proc.returncode)
except subprocess.TimeoutExpired:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        stdout, stderr = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
    if stderr:
        sys.stderr.write(stderr)
    if stdout:
        sys.stdout.write(stdout)
    sys.exit(124)
PY
}

run_claude() { command -v claude >/dev/null 2>&1 || return 1; mkdir -p "$RUN_ROOT/claude" || return 1; local o; o=$(run_isolated claude claude --safe-mode -p --no-session-persistence "$1" 2>"$RUN_ROOT/claude/stderr.txt") || return 1; [ -n "$o" ] && printf '%s\n' "$o" || return 1; }
run_codex()  { command -v codex  >/dev/null 2>&1 || return 1; mkdir -p "$RUN_ROOT/codex" || return 1; local o; o=$(run_isolated codex codex exec -m "$CODEX_MODEL" --ephemeral --skip-git-repo-check --sandbox read-only "$1" 2>"$RUN_ROOT/codex/stderr.txt") || return 1; [ -n "$o" ] && printf '%s\n' "$o" || return 1; }
# agy headless mode cannot prompt for repository-mandated reads. Auto-approval is bounded by
# both plan mode and the bounded tracked-file snapshot above.
run_agy()    { command -v agy    >/dev/null 2>&1 || return 1; mkdir -p "$RUN_ROOT/agy" || return 1; local o; o=$(run_isolated agy agy --sandbox --mode plan --dangerously-skip-permissions --model "$AGY_MODEL" --effort high --print="$1" 2>"$RUN_ROOT/agy/stderr.txt") || return 1; [ -n "$o" ] && printf '%s\n' "$o" || return 1; }

case "$HOST" in
  claude) peers="agy codex" ;;
  codex)  peers="claude agy" ;;
  agy)    peers="claude codex" ;;
  *) echo "unknown host '$HOST' (expected claude|codex|agy)" >&2; exit 2 ;;
esac

out=""; missing=0
pid_file="$RUN_ROOT/peer-pids.txt"
: > "$pid_file"
for p in $peers; do
  mkdir -p "$RUN_ROOT/$p" || exit 1
  (
    body=$("run_$p" "$PROMPT") || exit 1
    [ -n "$body" ] || exit 1
    printf '%s\n' "$body"
  ) > "$RUN_ROOT/$p/stdout.txt" 2> "$RUN_ROOT/$p/review-stderr.txt" &
  printf '%s:%s\n' "$p" "$!" >> "$pid_file"
done

while IFS=: read -r p pid; do
  [ -n "$p" ] || continue
  hdr="===== second opinion: $p ====="
  if wait "$pid"; then
    body="$(cat "$RUN_ROOT/$p/stdout.txt")"
  else
    body="(!! $p UNAVAILABLE — independent review NOT obtained)"
    missing=1
  fi
  printf '%s\n%s\n\n' "$hdr" "$body"
  out+="$hdr"$'\n'"$body"$'\n\n'
done < "$pid_file"

if [ -n "$SAVE" ]; then
  root="$SOURCE_ROOT"; dir="$root/.agent/reviews"; mkdir -p "$dir"
  ts=$(date -u +%Y%m%dT%H%M%SZ); f="$dir/${ts}-${RUN_ID}-${SAVE//[^A-Za-z0-9_-]/_}.md"
  adversarial=no; [ -n "$ADV" ] && adversarial=yes
  {
    printf '# strict-mode review — host=%s adversarial=%s — %s\n\n' "$HOST" "$adversarial" "$ts"
    printf 'Run ID: %s\n\n' "$RUN_ID"
    printf '## Prompt\n%s\n\n' "$*"
    printf '## Peer responses\n%s' "$out"
  } > "$f"
  printf '%s\n' "evidence: $f   (link this in the ADR/commit; verify it later — don't self-attest)"
fi

if [ "$missing" -ne 0 ]; then
  echo "ERROR: a required peer review was not obtained — review requirement NOT satisfied. Fix the peer CLI(s) and re-run, or record the gap + get human sign-off." >&2
  exit 3
fi
