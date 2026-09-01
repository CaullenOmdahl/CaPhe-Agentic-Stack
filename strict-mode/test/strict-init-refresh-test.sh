#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/strict-init-test.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT

file_mode() {
  case "$(uname -s)" in
    Darwin) stat -f '%Lp' "$1" ;;
    *) stat -c '%a' "$1" ;;
  esac
}
make_home() {
  mkdir -p "$1"
  ln -s "$ROOT" "$1/strict-mode"
}
managed_file() {
  cat > "$1" <<'DOC'
before-managed-section
<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->
stale policy
<!-- STRICT-MODE:END -->
after-managed-section
DOC
}

HOME_ROOT="$TEST_ROOT/home"
make_home "$HOME_ROOT"
REPO="$TEST_ROOT/repo"
mkdir -p "$REPO"
for file in CLAUDE.md AGENTS.md GEMINI.md; do managed_file "$REPO/$file"; done
chmod 640 "$REPO/CLAUDE.md"
MODE_BEFORE=$(file_mode "$REPO/CLAUDE.md")

(cd "$REPO" && HOME="$HOME_ROOT" "$ROOT/bin/strict-init.sh" >/dev/null)
for file in CLAUDE.md AGENTS.md GEMINI.md; do
  target="$REPO/$file"
  [ "$(grep -c '^<!-- STRICT-MODE:BEGIN ' "$target")" -eq 1 ]
  [ "$(grep -c '^<!-- STRICT-MODE:END -->$' "$target")" -eq 1 ]
  grep -q '^before-managed-section$' "$target"
  grep -q '^after-managed-section$' "$target"
  grep -q 'FAST GREEN' "$target"
  ! grep -q '^stale policy$' "$target"
done
[ "$(file_mode "$REPO/CLAUDE.md")" = "$MODE_BEFORE" ]

for file in CLAUDE.md AGENTS.md GEMINI.md; do cp "$REPO/$file" "$REPO/$file.once"; done
(cd "$REPO" && HOME="$HOME_ROOT" "$ROOT/bin/strict-init.sh" >/dev/null)
for file in CLAUDE.md AGENTS.md GEMINI.md; do cmp "$REPO/$file.once" "$REPO/$file"; done

SYMLINK_REPO="$TEST_ROOT/symlink-repo"
mkdir -p "$SYMLINK_REPO"
managed_file "$SYMLINK_REPO/CLAUDE.md"
ln -s CLAUDE.md "$SYMLINK_REPO/AGENTS.md"
ln -s CLAUDE.md "$SYMLINK_REPO/GEMINI.md"
(cd "$SYMLINK_REPO" && HOME="$HOME_ROOT" "$ROOT/bin/strict-init.sh" >/dev/null)
[ -L "$SYMLINK_REPO/AGENTS.md" ] && [ -L "$SYMLINK_REPO/GEMINI.md" ]
[ "$(grep -c '^<!-- STRICT-MODE:BEGIN ' "$SYMLINK_REPO/CLAUDE.md")" -eq 1 ]

PROSE_REPO="$TEST_ROOT/prose-repo"
mkdir -p "$PROSE_REPO"
cat > "$PROSE_REPO/CLAUDE.md" <<'DOC'
Keep this instruction.
Mention STRICT-MODE:BEGIN in prose without making it a marker.
Keep the trailing instruction.
DOC
(cd "$PROSE_REPO" && HOME="$HOME_ROOT" "$ROOT/bin/strict-init.sh" >/dev/null)
grep -q '^Mention STRICT-MODE:BEGIN in prose without making it a marker\.$' "$PROSE_REPO/CLAUDE.md"
[ "$(grep -c '^<!-- STRICT-MODE:BEGIN ' "$PROSE_REPO/CLAUDE.md")" -eq 1 ]

for kind in malformed duplicate reversed; do
  bad="$TEST_ROOT/$kind-repo"
  mkdir -p "$bad"
  case "$kind" in
    malformed)
      printf '%s\n' '<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->' broken > "$bad/CLAUDE.md" ;;
    duplicate)
      cat > "$bad/CLAUDE.md" <<'DOC'
<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->
one
<!-- STRICT-MODE:END -->
<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->
two
<!-- STRICT-MODE:END -->
DOC
      ;;
    reversed)
      printf '%s\n' '<!-- STRICT-MODE:END -->' '<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->' > "$bad/CLAUDE.md" ;;
  esac
  cp "$bad/CLAUDE.md" "$bad/before"
  if (cd "$bad" && HOME="$HOME_ROOT" "$ROOT/bin/strict-init.sh" >/dev/null 2>&1); then
    echo "$kind markers were accepted" >&2; exit 1
  fi
  cmp "$bad/before" "$bad/CLAUDE.md"
  [ ! -e "$bad/.agent" ]
done

MISSING_HOME="$TEST_ROOT/missing-home"
MISSING_REPO="$TEST_ROOT/missing-repo"
mkdir -p "$MISSING_HOME/strict-mode/templates" "$MISSING_REPO"
printf '%s\n' preserved > "$MISSING_REPO/CLAUDE.md"
if (cd "$MISSING_REPO" && HOME="$MISSING_HOME" "$ROOT/bin/strict-init.sh" >/dev/null 2>&1); then
  echo "missing canon was accepted" >&2; exit 1
fi
grep -q '^preserved$' "$MISSING_REPO/CLAUDE.md"

WORKTREE_MAIN="$TEST_ROOT/worktree-main"
WORKTREE_CHILD="$TEST_ROOT/worktree-child"
mkdir -p "$WORKTREE_MAIN"
git -C "$WORKTREE_MAIN" init -q
git -C "$WORKTREE_MAIN" config user.name strict-init-test
git -C "$WORKTREE_MAIN" config user.email strict-init-test@example.invalid
printf '%s\n' initial > "$WORKTREE_MAIN/README.md"
git -C "$WORKTREE_MAIN" add README.md
git -C "$WORKTREE_MAIN" commit -qm initial
git -C "$WORKTREE_MAIN" worktree add -q -b strict-init-test "$WORKTREE_CHILD"
(cd "$WORKTREE_CHILD" && HOME="$HOME_ROOT" "$ROOT/bin/strict-init.sh" >/dev/null)
HOOK=$(git -C "$WORKTREE_CHILD" rev-parse --git-path hooks/pre-commit)
[ -x "$WORKTREE_CHILD/$HOOK" ] || [ -x "$HOOK" ]
grep -q 'strict-green-gate' "$WORKTREE_CHILD/$HOOK" 2>/dev/null || grep -q 'strict-green-gate' "$HOOK"
(cd "$WORKTREE_CHILD" && HOME="$HOME_ROOT" "$HOOK" >/dev/null)

words=$(sed -n '/^## Strict Mode$/,/^<!-- STRICT-MODE:END -->$/p' "$ROOT/templates/instruction-section.md" | wc -w | tr -d ' ')
[ "$words" -le 180 ] || { echo "managed section exceeds 180 words: $words" >&2; exit 1; }

echo "strict-init regression tests passed"
