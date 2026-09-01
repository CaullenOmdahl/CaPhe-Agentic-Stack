#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/strict-confer-test.XXXXXX")"
cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

process_is_running() {
  local pid="$1" state
  kill -0 "$pid" 2>/dev/null || return 1
  state=$(ps -o stat= -p "$pid" 2>/dev/null | tr -d '[:space:]')
  case "$state" in Z*|"") return 1 ;; *) return 0 ;; esac
}

make_mock_boundaries() {
  local mockbin="$1"
  if [ ! -x "$mockbin/sandbox-exec" ]; then
    cat > "$mockbin/sandbox-exec" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' sandbox-exec >> "${STRICT_CONFER_BOUNDARY_LOG:-/dev/null}"
[ "${1:-}" = "-f" ] || exit 2
shift 2
exec "$@"
MOCK
    chmod +x "$mockbin/sandbox-exec"
  fi
  if [ ! -x "$mockbin/bwrap" ]; then
    cat > "$mockbin/bwrap" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' bwrap >> "${STRICT_CONFER_BOUNDARY_LOG:-/dev/null}"
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ "${1:-}" = "--" ] || exit 2
shift
exec "$@"
MOCK
    chmod +x "$mockbin/bwrap"
  fi
}

make_mock_peer() {
  local path="$1" name="$2"
  local mockbin
  mockbin=$(dirname "$path")
  make_mock_boundaries "$mockbin"
  cat > "$path" <<MOCK
#!/usr/bin/env bash
set -euo pipefail
echo "$name review: run=\${STRICT_CONFER_RUN_ID:-} peer=\${STRICT_CONFER_PEER:-} cwd=\$(pwd)"
if [ -f review-target.txt ]; then
  echo "$name snapshot: \$(cat review-target.txt)"
fi
if [ -f .env ]; then
  echo "$name secret snapshot: \$(cat .env)"
fi
if [ -f untracked-sensitive.txt ]; then
  echo "$name untracked snapshot: \$(cat untracked-sensitive.txt)"
fi
if [ -e review-link ]; then
  echo "$name symlink snapshot: \$(cat review-link)"
fi
if [ -f review-gitlink ]; then
  echo "$name gitlink snapshot: \$(cat review-gitlink)"
fi
if [ -n "\${STRICT_CONFER_SOURCE_ROOT:-}" ] && [ -f "\${STRICT_CONFER_SOURCE_ROOT}/untracked-sensitive.txt" ]; then
  echo "$name source-root snapshot: \$(cat "\${STRICT_CONFER_SOURCE_ROOT}/untracked-sensitive.txt")"
fi
printf '%s\\n' "$name:\${STRICT_CONFER_RUN_ID:-}:\${STRICT_CONFER_RUN_ROOT:-}:\${STRICT_CONFER_PEER:-}:\$(pwd)" >> "\$STRICT_CONFER_TEST_LOG"
MOCK
  chmod +x "$path"
}

make_arg_logging_peer() {
  local path="$1" name="$2"
  cat > "$path" <<MOCK
#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$name args: \$*"
MOCK
  chmod +x "$path"
}

test_parallel_runs_are_ephemeral_and_unique() {
  local project="$TMP/project"
  local mockbin="$TMP/bin"
  local log="$TMP/peer.log"
  mkdir -p "$project" "$mockbin"
  git -C "$project" init -q
  git -C "$project" config user.name strict-confer-test
  git -C "$project" config user.email strict-confer-test@example.invalid
  printf '%s\n' ".env" > "$project/.gitignore"
  printf '%s\n' "tracked workspace is visible" > "$project/review-target.txt"
  printf '%s\n' "must not escape through symlink" > "$TMP/external-sensitive.txt"
  ln -s "$TMP/external-sensitive.txt" "$project/review-link"
  git -C "$project" add .gitignore review-target.txt review-link
  git -C "$project" commit -qm initial
  printf '%s\n' "unstaged tracked secret must stay local" > "$project/review-target.txt"
  rm "$project/review-link"
  printf '%s\n' "must not replace indexed symlink" > "$project/review-link"
  gitlink_oid=$(git -C "$project" rev-parse HEAD)
  git -C "$project" update-index --add --cacheinfo "160000,$gitlink_oid,review-gitlink"
  printf '%s\n' "must not replace indexed gitlink" > "$project/review-gitlink"
  printf '%s\n' "must stay local" > "$project/untracked-sensitive.txt"
  printf '%s\n' "must stay private" > "$project/.env"
  make_mock_peer "$mockbin/claude" "claude"
  make_mock_peer "$mockbin/agy" "agy"
  make_mock_peer "$mockbin/codex" "codex"

  (
    cd "$project"
    PATH="$mockbin:$PATH" STRICT_CONFER_TEST_LOG="$log" STRICT_CONFER_BOUNDARY_LOG="$TMP/boundary.log" \
      "$ROOT/bin/strict-confer.sh" codex --save same-label "first prompt" \
      > "$TMP/out-1" 2> "$TMP/err-1"
  ) &
  local p1=$!
  (
    cd "$project"
    PATH="$mockbin:$PATH" STRICT_CONFER_TEST_LOG="$log" STRICT_CONFER_BOUNDARY_LOG="$TMP/boundary.log" \
      "$ROOT/bin/strict-confer.sh" codex --save same-label "second prompt" \
      > "$TMP/out-2" 2> "$TMP/err-2"
  ) &
  local p2=$!

  wait "$p1"
  wait "$p2"

  [ -s "$log" ] || fail "mock peers did not record any invocations"

  local run_count root_count cwd_count evidence_count
  run_count="$(awk -F: '{print $2}' "$log" | sort -u | sed '/^$/d' | wc -l | tr -d ' ')"
  root_count="$(awk -F: '{print $3}' "$log" | sort -u | sed '/^$/d' | wc -l | tr -d ' ')"
  cwd_count="$(awk -F: '{print $5}' "$log" | sort -u | sed '/^$/d' | wc -l | tr -d ' ')"
  evidence_count="$(find "$project/.agent/reviews" -type f -name '*same-label.md' | wc -l | tr -d ' ')"

  [ "$run_count" -eq 2 ] || fail "expected 2 unique run IDs, got $run_count"
  [ "$root_count" -eq 2 ] || fail "expected 2 unique run roots, got $root_count"
  [ "$cwd_count" -eq 4 ] || fail "expected 4 isolated peer working directories, got $cwd_count"
  [ "$evidence_count" -eq 2 ] || fail "expected 2 non-clobbered evidence files, got $evidence_count"
  [ "$(wc -l < "$TMP/boundary.log" | tr -d ' ')" -eq 4 ] || fail "every peer must run inside the OS boundary"
  grep -q "snapshot: tracked workspace is visible" "$TMP/out-1" || fail "first run peer could not read tracked snapshot"
  grep -q "snapshot: tracked workspace is visible" "$TMP/out-2" || fail "second run peer could not read tracked snapshot"
  ! grep -q "must stay local" "$TMP/out-1" || fail "first run copied an untracked local file"
  ! grep -q "must stay local" "$TMP/out-2" || fail "second run copied an untracked local file"
  ! grep -q "unstaged tracked secret" "$TMP/out-1" || fail "first run copied unstaged tracked bytes"
  ! grep -q "unstaged tracked secret" "$TMP/out-2" || fail "second run copied unstaged tracked bytes"
  ! grep -q "must not escape through symlink" "$TMP/out-1" || fail "first run preserved an escaping tracked symlink"
  ! grep -q "must not escape through symlink" "$TMP/out-2" || fail "second run preserved an escaping tracked symlink"
  ! grep -q "must not replace indexed symlink" "$TMP/out-1" || fail "first run trusted a replaced indexed symlink"
  ! grep -q "must not replace indexed symlink" "$TMP/out-2" || fail "second run trusted a replaced indexed symlink"
  ! grep -q "must not replace indexed gitlink" "$TMP/out-1" || fail "first run trusted a replaced indexed gitlink"
  ! grep -q "must not replace indexed gitlink" "$TMP/out-2" || fail "second run trusted a replaced indexed gitlink"
  ! grep -q "source-root snapshot" "$TMP/out-1" || fail "first run exposed the live source root"
  ! grep -q "source-root snapshot" "$TMP/out-2" || fail "second run exposed the live source root"
  ! grep -q "must stay private" "$TMP/out-1" || fail "first run copied an ignored secret-bearing file"
  ! grep -q "must stay private" "$TMP/out-2" || fail "second run copied an ignored secret-bearing file"

  while IFS= read -r root; do
    [ -n "$root" ] || continue
    [ ! -e "$root" ] || fail "ephemeral run root was not cleaned: $root"
  done < <(awk -F: '{print $3}' "$log" | sort -u)
}

test_current_peer_cli_invocations() {
  local project="$TMP/args-project"
  local mockbin="$TMP/args-bin"
  mkdir -p "$project" "$mockbin"
  git -C "$project" init -q
  make_arg_logging_peer "$mockbin/claude" "claude"
  make_arg_logging_peer "$mockbin/agy" "agy"
  make_arg_logging_peer "$mockbin/codex" "codex"
  make_mock_boundaries "$mockbin"

  (
    cd "$project"
    PATH="$mockbin:$PATH" \
    STRICT_CONFER_AGY_MODEL="test-gemini" \
    STRICT_CONFER_CODEX_MODEL="test-codex" \
      "$ROOT/bin/strict-confer.sh" claude "review prompt" \
      > "$TMP/args-out" 2> "$TMP/args-err"
  )

  grep -q -- "agy args: --sandbox --mode plan --dangerously-skip-permissions --model test-gemini --effort high --print=review prompt" "$TMP/args-out" || \
    fail "agy was not invoked with the verified headless read-only command"
  grep -q -- "codex args: exec -m test-codex --ephemeral --skip-git-repo-check --sandbox read-only review prompt" "$TMP/args-out" || \
    fail "codex model override was not honored"
}

test_snapshot_tolerates_tracked_deletions() {
  local project="$TMP/deletion-project"
  local mockbin="$TMP/deletion-bin"
  mkdir -p "$project" "$mockbin"
  git -C "$project" init -q
  git -C "$project" config user.name strict-confer-test
  git -C "$project" config user.email strict-confer-test@example.invalid
  printf '%s\n' present > "$project/keep.txt"
  printf '%s\n' deleted > "$project/delete.txt"
  git -C "$project" add keep.txt delete.txt
  git -C "$project" commit -qm initial
  rm "$project/delete.txt"
  make_mock_peer "$mockbin/claude" "claude"
  make_mock_peer "$mockbin/agy" "agy"
  make_mock_peer "$mockbin/codex" "codex"
  (
    cd "$project"
    PATH="$mockbin:$PATH" STRICT_CONFER_TEST_LOG="$TMP/deletion-peer.log" \
      "$ROOT/bin/strict-confer.sh" codex "review deletion" \
      > "$TMP/deletion-out" 2> "$TMP/deletion-err"
  )
  ! grep -q 'UNAVAILABLE' "$TMP/deletion-out" || fail "tracked deletion broke the peer snapshot"
}

test_live_workspace_bypass_is_refused() {
  local project="$TMP/live-bypass-project"
  local mockbin="$TMP/live-bypass-bin"
  mkdir -p "$project" "$mockbin"
  git -C "$project" init -q
  printf '%s\n' "must never reach a peer" > "$project/untracked-sensitive.txt"
  make_mock_peer "$mockbin/claude" "claude"
  make_mock_peer "$mockbin/agy" "agy"
  make_mock_peer "$mockbin/codex" "codex"
  set +e
  (
    cd "$project"
    PATH="$mockbin:$PATH" STRICT_CONFER_NO_SNAPSHOT=1 \
      STRICT_CONFER_TEST_LOG="$TMP/live-bypass.log" \
      "$ROOT/bin/strict-confer.sh" codex "reject live workspace" \
      > "$TMP/live-bypass-out" 2> "$TMP/live-bypass-err"
  )
  local status=$?
  set -e
  [ "$status" -eq 2 ] || fail "live workspace bypass was not rejected with exit 2: $status"
  [ ! -e "$TMP/live-bypass.log" ] || fail "a peer ran after the live workspace bypass request"
}

test_non_git_snapshot_is_refused() {
  local project="$TMP/non-git-project"
  mkdir -p "$project"
  set +e
  (cd "$project" && "$ROOT/bin/strict-confer.sh" codex "reject non-git" >/dev/null 2>&1)
  local status=$?
  set -e
  [ "$status" -eq 2 ] || fail "non-Git snapshot was not rejected with exit 2: $status"
}

test_timeout_kills_peer_child_process_group() {
  local project="$TMP/timeout-project"
  local mockbin="$TMP/timeout-bin"
  local child_pid_file="$TMP/child.pid"
  mkdir -p "$project" "$mockbin"
  git -C "$project" init -q

  cat > "$mockbin/claude" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
(sleep 30) &
echo "$!" > "$STRICT_CONFER_CHILD_PID_FILE"
wait "$!"
MOCK
  chmod +x "$mockbin/claude"
  make_mock_peer "$mockbin/agy" "agy"
  make_mock_peer "$mockbin/codex" "codex"

  set +e
  (
    cd "$project"
    PATH="$mockbin:$PATH" \
    STRICT_CONFER_TEST_LOG="$TMP/timeout-peer.log" \
    STRICT_CONFER_CHILD_PID_FILE="$child_pid_file" \
    STRICT_CONFER_TIMEOUT_SECONDS=1 \
      "$ROOT/bin/strict-confer.sh" codex "timeout prompt" \
      > "$TMP/timeout-out" 2> "$TMP/timeout-err"
  )
  local status=$?
  set -e

  [ "$status" -eq 3 ] || fail "expected unavailable-peer exit 3 after timeout, got $status"
  [ -s "$child_pid_file" ] || return 0

  local child_pid
  child_pid="$(cat "$child_pid_file")"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! process_is_running "$child_pid"; then
      return 0
    fi
    sleep 0.2
  done
  fail "timed-out peer child process is still alive: $child_pid"
}

test_parallel_runs_are_ephemeral_and_unique
test_current_peer_cli_invocations
test_snapshot_tolerates_tracked_deletions
test_live_workspace_bypass_is_refused
test_non_git_snapshot_is_refused
test_timeout_kills_peer_child_process_group
echo "strict-confer isolation tests passed"
