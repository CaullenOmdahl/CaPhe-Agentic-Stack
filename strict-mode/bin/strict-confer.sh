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
# Git snapshots materialize only stage-0 regular blobs from the index; unstaged worktree bytes,
# symlinks, gitlinks, and arbitrary untracked files are not copied. The peer additionally runs behind
# a fail-closed OS filesystem boundary that hides the source worktree. Override reviewer models with
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
ORIGINAL_HOME="${HOME:?strict-confer requires HOME}"
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
  local peer_home
  peer_home="$peer_dir/home"
  mkdir -p "$peer_home/.config" "$peer_home/.cache" "$peer_home/.local/share" || return 1
  git -C "$SOURCE_ROOT" ls-files --stage -z |
    while IFS= read -r -d '' index_entry; do
      index_meta=${index_entry%%$'\t'*}
      tracked_path=${index_entry#*$'\t'}
      read -r index_mode object_id index_stage <<EOF
$index_meta
EOF
      if [ "$index_stage" != "0" ]; then
        echo "strict-confer refuses an unmerged index entry: $tracked_path" >&2
        exit 1
      fi
      case "$index_mode" in 100644|100755) ;; *) continue ;; esac
      destination="$peer_cwd/$tracked_path"
      mkdir -p -- "$(dirname -- "$destination")" || exit 1
      git -C "$SOURCE_ROOT" cat-file blob "$object_id" > "$destination" || exit 1
      case "$index_mode" in 100755) chmod 755 "$destination" ;; *) chmod 644 "$destination" ;; esac
    done || return 1
  local peer_executable
  peer_executable="$(command -v "${1:-}")" || return 1
  peer_executable="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$peer_executable")" || return 1
  [ -f "$peer_executable" ] || {
    echo "strict-confer peer executable is not a regular file: $peer_executable" >&2
    return 1
  }
  shift
  set -- "$peer_executable" "$@"

  # Give each peer a throwaway home. Authentication files are never copied into the
  # model-readable boundary; a CLI that cannot authenticate without them is unavailable.
  # Only non-secret onboarding identity state may be seeded.
  case "$peer" in
    codex)
      mkdir -p "$peer_home/.codex" || return 1
      ;;
    claude)
      mkdir -p "$peer_home/.claude" || return 1
      if [ -f "$ORIGINAL_HOME/.claude.json" ] && [ ! -L "$ORIGINAL_HOME/.claude.json" ]; then
        python3 - "$ORIGINAL_HOME/.claude.json" "$peer_home/.claude.json" <<'PY' || return 1
import json
import os
import sys

source, destination = sys.argv[1:]
with open(source, encoding="utf-8") as handle:
    value = json.load(handle)
allowed = {
    key: value[key]
    for key in ("hasCompletedOnboarding", "installMethod")
    if key in value
}
with open(destination, "w", encoding="utf-8") as handle:
    json.dump(allowed, handle, separators=(",", ":"))
    handle.write("\n")
os.chmod(destination, 0o600)
PY
      fi
      ;;
    agy)
      mkdir -p "$peer_home/.gemini/antigravity-cli" || return 1
      ;;
  esac
  chmod -R go-rwx "$peer_home" || return 1

  local peer_path
  peer_path="$(dirname "$peer_executable"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  local -a boundary_command
  case "$(uname -s)" in
    Darwin)
      local sandbox_executable
      sandbox_executable="$(command -v sandbox-exec)" || {
        echo "strict-confer requires sandbox-exec on macOS" >&2; return 1;
      }
      local sandbox_profile escaped_peer_dir escaped_peer_executable escaped_source escaped_home
      sandbox_profile="$peer_dir/source-boundary.sb"
      escaped_peer_dir=$(python3 -c 'import json, os, sys; print(json.dumps(os.path.realpath(sys.argv[1])))' "$peer_dir") || return 1
      escaped_peer_executable=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$peer_executable") || return 1
      escaped_source=$(python3 -c 'import json, os, sys; print(json.dumps(os.path.realpath(sys.argv[1])))' "$SOURCE_ROOT") || return 1
      escaped_home=$(python3 -c 'import json, os, sys; print(json.dumps(os.path.realpath(sys.argv[1])))' "$ORIGINAL_HOME") || return 1
      {
        printf '%s\n' \
          '(version 1)' \
          '(deny default)' \
          '(allow process*)' \
          '(allow network*)' \
          '(allow sysctl-read)' \
          '(allow mach-lookup)' \
          '(allow ipc-posix*)' \
          '(allow signal)' \
          '(allow file-read-metadata)'
        # macOS runtime loaders consult several sealed/Cryptex paths. Permit reads first,
        # then mask every host data root and re-open only selected runtime and peer paths.
        printf '%s\n' '(allow file-read*)'
        printf '(deny file-read* (subpath "/Users") (subpath "/Volumes") (subpath "/Network") (subpath "/System/Volumes/Data") (subpath "/private/tmp") (subpath "/private/etc") (subpath "/private/var") (subpath "/Library") (subpath "/opt") (subpath %s) (subpath %s))\n' "$escaped_source" "$escaped_home"
        printf '(allow file-read* (subpath %s) (literal %s)' "$escaped_peer_dir" "$escaped_peer_executable"
        for runtime_path in \
          /Library/Apple /Library/Frameworks /opt/homebrew \
          /private/etc/ssl /private/etc/resolv.conf /private/etc/hosts \
          /private/var/db/timezone /private/var/run
        do
          if [ -e "$runtime_path" ]; then
            escaped_runtime=$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$runtime_path") || return 1
            if [ -d "$runtime_path" ]; then
              printf ' (subpath %s)' "$escaped_runtime"
            else
              printf ' (literal %s)' "$escaped_runtime"
            fi
          fi
        done
        printf ')\n'
        printf '(allow file-write* (subpath %s) (literal "/dev/null"))\n' "$escaped_peer_dir"
      } > "$sandbox_profile" || return 1
      boundary_command=("$sandbox_executable" -f "$sandbox_profile")
      ;;
    Linux)
      local bwrap_executable
      bwrap_executable="$(command -v bwrap)" || {
        echo "strict-confer requires bubblewrap on Linux" >&2; return 1;
      }
      boundary_command=("$bwrap_executable" --die-with-parent --unshare-pid --ro-bind /usr /usr)
      for runtime_path in /bin /sbin /lib /lib64; do
        if [ -L "$runtime_path" ]; then
          boundary_command+=(--symlink "$(readlink "$runtime_path")" "$runtime_path")
        elif [ -e "$runtime_path" ]; then
          boundary_command+=(--ro-bind "$runtime_path" "$runtime_path")
        fi
      done
      if [ -e /opt ]; then
        boundary_command+=(--ro-bind /opt /opt)
      fi
      for runtime_path in \
        /etc/ssl /etc/pki /etc/resolv.conf /etc/hosts /etc/nsswitch.conf \
        /etc/gai.conf /etc/passwd /etc/group /etc/localtime
      do
        if [ -e "$runtime_path" ]; then
          boundary_command+=(--ro-bind "$runtime_path" "$runtime_path")
        fi
      done
      boundary_command+=(
        --tmpfs /tmp --ro-bind "$peer_executable" "$peer_executable"
        --bind "$peer_dir" "$peer_dir" --proc /proc --dev /dev
        --chdir "$peer_cwd" --
      )
      ;;
    *) echo "strict-confer has no filesystem boundary for $(uname -s)" >&2; return 1 ;;
  esac
  STRICT_CONFER_PEER="$peer" \
  STRICT_CONFER_RUN_ID="$RUN_ID" \
  STRICT_CONFER_RUN_ROOT="$RUN_ROOT" \
  STRICT_CONFER_CWD="$peer_cwd" \
  STRICT_CONFER_TIMEOUT_SECONDS="$PEER_TIMEOUT_SECONDS" \
  HOME="$peer_home" \
  CODEX_HOME="$peer_home/.codex" \
  CLAUDE_CONFIG_DIR="$peer_home/.claude" \
  XDG_CONFIG_HOME="$peer_home/.config" \
  XDG_CACHE_HOME="$peer_home/.cache" \
  XDG_DATA_HOME="$peer_home/.local/share" \
  PATH="$peer_path" \
  TMPDIR="$peer_dir/tmp" \
    python3 - "${boundary_command[@]}" "$@" <<'PY'
import os
import signal
import subprocess
import sys

args = sys.argv[1:]
cwd = os.environ["STRICT_CONFER_CWD"]
timeout = float(os.environ["STRICT_CONFER_TIMEOUT_SECONDS"])
allowed_names = {
    "PATH",
    "HOME",
    "CODEX_HOME",
    "CLAUDE_CONFIG_DIR",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "COLORTERM",
    "NO_COLOR",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "STRICT_CONFER_PEER",
    "STRICT_CONFER_RUN_ID",
    "STRICT_CONFER_RUN_ROOT",
    "STRICT_CONFER_CWD",
    "STRICT_CONFER_TIMEOUT_SECONDS",
    "STRICT_CONFER_BOUNDARY_LOG",
    "STRICT_CONFER_TEST_LOG",
    "STRICT_CONFER_CHILD_PID_FILE",
}
child_env = {name: value for name, value in os.environ.items() if name in allowed_names}
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

run_claude() {
  command -v claude >/dev/null 2>&1 || return 1
  mkdir -p "$RUN_ROOT/claude" || return 1
  local o status
  o=$(run_isolated claude claude --safe-mode -p --no-session-persistence "$1" 2>"$RUN_ROOT/claude/stderr.txt")
  status=$?
  if [ "$status" -ne 0 ]; then
    cat "$RUN_ROOT/claude/stderr.txt" >&2
    echo "strict-confer claude boundary exit: $status" >&2
    return 1
  fi
  [ -n "$o" ] && printf '%s\n' "$o" || return 1
}
run_codex() {
  command -v codex >/dev/null 2>&1 || return 1
  mkdir -p "$RUN_ROOT/codex" || return 1
  local o status
  # The outer default-deny OS boundary is authoritative. Avoid nesting Codex's own
  # Seatbelt inside it; nested macOS sandboxes can block even read-only inspection.
  o=$(run_isolated codex codex exec -m "$CODEX_MODEL" --ephemeral --skip-git-repo-check --sandbox danger-full-access "$1" 2>"$RUN_ROOT/codex/stderr.txt")
  status=$?
  if [ "$status" -ne 0 ]; then
    cat "$RUN_ROOT/codex/stderr.txt" >&2
    echo "strict-confer codex boundary exit: $status" >&2
    return 1
  fi
  [ -n "$o" ] && printf '%s\n' "$o" || return 1
}
# agy headless mode cannot prompt for repository-mandated reads. Auto-approval is bounded by
# both plan mode and the bounded tracked-file snapshot above.
run_agy() {
  command -v agy >/dev/null 2>&1 || return 1
  mkdir -p "$RUN_ROOT/agy" || return 1
  local o status
  o=$(run_isolated agy agy --sandbox --mode plan --dangerously-skip-permissions --model "$AGY_MODEL" --effort high --print="$1" 2>"$RUN_ROOT/agy/stderr.txt")
  status=$?
  if [ "$status" -ne 0 ]; then
    cat "$RUN_ROOT/agy/stderr.txt" >&2
    echo "strict-confer agy boundary exit: $status" >&2
    return 1
  fi
  [ -n "$o" ] && printf '%s\n' "$o" || return 1
}

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
    if [ -s "$RUN_ROOT/$p/review-stderr.txt" ]; then
      sed "s/^/$p: /" "$RUN_ROOT/$p/review-stderr.txt" >&2
    fi
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
