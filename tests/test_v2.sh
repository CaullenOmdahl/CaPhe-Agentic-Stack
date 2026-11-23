#!/usr/bin/env bash
# CaPhe Agentic Stack v2 verification suite:
# 1) Shell syntax, JSON & TOML validity
# 2) Context-budget checks (always-loaded canon stays tiny)
# 3) Sandboxed installer idempotency, non-destructive merge & collision-safety tests
# 4) Pre-push hook execution test
# 5) Public-safety scan (no secrets, private paths, or sensitive filenames)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "1. Checking shell syntax..."
bash -n install.sh hooks/pre-push-check.sh hooks/cve-check.sh tests/test_v2.sh

echo "2. Validating JSON, TOML, and skill frontmatter..."
python3 - <<'PY'
import json, pathlib, tomllib

for jp in pathlib.Path(".").rglob("*.json"):
    json.loads(jp.read_text(encoding="utf-8"))

for tp in list(pathlib.Path(".").rglob("*.toml")) + [pathlib.Path(".caphe.toml")]:
    if tp.is_file():
        tomllib.loads(tp.read_text(encoding="utf-8"))

skills = sorted(pathlib.Path("skills").glob("*/SKILL.md"))
assert len(skills) == 6, f"expected 6 skills, got {len(skills)}"
for sp in skills:
    txt = sp.read_text(encoding="utf-8")
    assert txt.startswith("---\n"), f"missing frontmatter in {sp}"
    head = txt.split("---\n", 2)[1]
    assert "name:" in head and "description:" in head, f"missing name/description in {sp}"
    lines = len(txt.splitlines())
    assert lines <= 60, f"{sp} too bloated ({lines} lines > 60)"

canon_lines = len(pathlib.Path("docs/canon.md").read_text(encoding="utf-8").splitlines())
assert canon_lines <= 70, f"docs/canon.md exceeds 70-line budget ({canon_lines})"
for ep in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
    n = len(pathlib.Path(ep).read_text(encoding="utf-8").splitlines())
    assert n <= 15, f"{ep} exceeds 15-line budget ({n})"
print(f"OK: canon={canon_lines} lines, {len(skills)} concise skills, all JSON/TOML valid")
PY

echo "3. Testing sandboxed installer & idempotency..."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/.claude" "$TMP/.codex"
printf '# Existing personal rule\nKeep me intact.\n' > "$TMP/.claude/CLAUDE.md"
printf '{"voice": {"enabled": true}, "env": {"EXISTING": "1"}}\n' > "$TMP/.claude/settings.json"
printf '[mcp_servers.demo]\ncommand = "demo"\n' > "$TMP/.codex/config.toml"

HOME="$TMP" bash "$ROOT/install.sh" --apply-settings >/dev/null
HOME="$TMP" bash "$ROOT/install.sh" --apply-settings >/dev/null

grep -q "Keep me intact." "$TMP/.claude/CLAUDE.md"
test "$(grep -c 'CAPHE:V2:BEGIN' "$TMP/.claude/CLAUDE.md")" -eq 1
test -f "$TMP/AGENTS_GLOBAL.md"
test -f "$TMP/.claude/skills/repo-init/SKILL.md"
test -f "$TMP/.claude/skills/git-github/SKILL.md"
test -f "$TMP/.claude/agents/worker.md"
test -f "$TMP/.codex/agents/explorer.toml"
test -f "$TMP/.gemini/config/skills/ponytail/SKILL.md"
test -x "$TMP/.local/bin/caphe-cve-check"

python3 - "$TMP/.claude/settings.json" "$TMP/.codex/config.toml" <<'PY'
import json, pathlib, tomllib, sys
cs = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert cs["voice"]["enabled"] is True
assert cs["env"]["EXISTING"] == "1"
assert cs["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "sonnet"
assert cs["effortLevel"] == "medium"
assert cs["enableWorkflows"] is False
ct = tomllib.loads(pathlib.Path(sys.argv[2]).read_text())
assert ct["mcp_servers"]["demo"]["command"] == "demo"
assert ct["agents"]["max_concurrent_threads_per_session"] == 6
print("OK: sandbox install + idempotency + non-destructive merge verified")
PY

# Collision safety (#29): pre-existing customized skill, agent profile, and canon are preserved by default,
# backed up then replaced with --force, while untouched stack-managed files still receive upgrades.
CUST="$TMP/cust"
mkdir -p "$CUST/.claude/skills/ponytail" "$CUST/.claude/agents"
printf 'my own ponytail\n' > "$CUST/.claude/skills/ponytail/SKILL.md"
printf 'my own worker\n' > "$CUST/.claude/agents/worker.md"
printf 'my own canon\n' > "$CUST/AGENTS_GLOBAL.md"
OUT="$(HOME="$CUST" XDG_STATE_HOME="$CUST/state" bash "$ROOT/install.sh")"
grep -qx 'my own ponytail' "$CUST/.claude/skills/ponytail/SKILL.md"
grep -qx 'my own worker' "$CUST/.claude/agents/worker.md"
grep -qx 'my own canon' "$CUST/AGENTS_GLOBAL.md"
echo "$OUT" | grep -q "$CUST/.claude/skills/ponytail"
cmp -s "$ROOT/skills/git-github/SKILL.md" "$CUST/.claude/skills/git-github/SKILL.md"

HOME="$CUST" XDG_STATE_HOME="$CUST/state" bash "$ROOT/install.sh" --force >/dev/null
cmp -s "$ROOT/skills/ponytail/SKILL.md" "$CUST/.claude/skills/ponytail/SKILL.md"
cmp -s "$ROOT/docs/canon.md" "$CUST/AGENTS_GLOBAL.md"
grep -qx 'my own ponytail' "$CUST"/state/caphe/backups/*/.claude/skills/ponytail/SKILL.md
grep -qx 'my own worker' "$CUST"/state/caphe/backups/*/.claude/agents/worker.md
grep -qx 'my own canon' "$CUST"/state/caphe/backups/*/AGENTS_GLOBAL.md

# Upgrade path: an unmodified stack-managed skill updates silently; a user-edited one is preserved.
UPSRC="$TMP/upsrc"
mkdir -p "$UPSRC"
cp -R "$ROOT/install.sh" "$ROOT/docs" "$ROOT/skills" "$ROOT/templates" "$ROOT/hooks" "$UPSRC/"
UP="$TMP/up"
mkdir -p "$UP"
HOME="$UP" XDG_STATE_HOME="$UP/state" bash "$UPSRC/install.sh" >/dev/null
printf '\nupgraded line\n' >> "$UPSRC/skills/ponytail/SKILL.md"
printf '\nupgraded line\n' >> "$UPSRC/skills/git-github/SKILL.md"
printf '\nuser edit\n' >> "$UP/.claude/skills/git-github/SKILL.md"
HOME="$UP" XDG_STATE_HOME="$UP/state" bash "$UPSRC/install.sh" >/dev/null
grep -q 'upgraded line' "$UP/.claude/skills/ponytail/SKILL.md"
grep -q 'user edit' "$UP/.claude/skills/git-github/SKILL.md"
if grep -q 'upgraded line' "$UP/.claude/skills/git-github/SKILL.md"; then
  echo "user-edited skill was overwritten" >&2; exit 1
fi
test ! -d "$UP/state/caphe/backups"
echo "OK: installer preserves customizations, backs up on --force, upgrades untouched stack files"

echo "4. Testing pre-push hook & non-discretionary CVE check..."
REPO_TMP="$TMP/repo"
mkdir -p "$REPO_TMP" "$TMP/mockbin"
git -C "$REPO_TMP" init -q
cat > "$REPO_TMP/.caphe.toml" <<'EOF'
[verify]
test = "echo pre-push-ran-ok"
EOF
OUT="$(cd "$REPO_TMP" && bash "$ROOT/hooks/pre-push-check.sh")"
echo "$OUT" | grep -q "pre-push-ran-ok"

# CVE checker (#28) with a hermetic PATH: only core utilities plus a mocked osv-scanner, so host scanners never run.
MINBIN="$TMP/minbin"
mkdir -p "$MINBIN"
for tool in bash git sha256sum cut date mkdir cat tail rm dirname pwd; do
  ln -s "$(command -v "$tool")" "$MINBIN/$tool"
done
cat > "$TMP/mockbin/osv-scanner" <<'EOF'
#!/usr/bin/env bash
case "${MOCK_OSV:-clean}" in
  vuln) echo "CVE-2026-99999 CRITICAL example-pkg 1.0.0 -> fix 1.0.1"; exit 1 ;;
  error) echo "osv-scanner: failed to query OSV API"; exit 2 ;;
esac
exit 0
EOF
chmod +x "$TMP/mockbin/osv-scanner"
printf '{"lockfileVersion": 3}\n' > "$REPO_TMP/package-lock.json"

expect_cve() {  # expect_cve WANT_EXIT MODE [args...]; output lands in $TMP/cve.out
  local want="$1" mode="$2" rc=0
  shift 2
  PATH="$TMP/mockbin:$MINBIN" XDG_CACHE_HOME="$TMP/cache" MOCK_OSV="$mode" \
    bash "$ROOT/hooks/cve-check.sh" --repo "$REPO_TMP" "$@" > "$TMP/cve.out" 2>&1 || rc=$?
  if [ "$rc" -ne "$want" ]; then
    echo "cve-check ($mode $*): expected exit $want, got $rc" >&2
    cat "$TMP/cve.out" >&2
    exit 1
  fi
}
not_in_out() { if grep -q "$1" "$TMP/cve.out"; then echo "unexpected '$1' in cve output" >&2; cat "$TMP/cve.out" >&2; exit 1; fi; }

# Clean scan -> cached on repeat
expect_cve 0 clean --if-stale 24; grep -q "OK" "$TMP/cve.out"
expect_cve 0 clean --if-stale 24; grep -q "cached" "$TMP/cve.out"

# Lockfile change invalidates the cache
printf '{"lockfileVersion": 3, "name": "changed"}\n' > "$REPO_TMP/package-lock.json"
expect_cve 0 clean --if-stale 24; not_in_out "cached"

# Scanner error -> exit 2, no OK, clean cache dropped, next --if-stale run retries instead of trusting it
printf '{"lockfileVersion": 3, "name": "changed-again"}\n' > "$REPO_TMP/package-lock.json"
expect_cve 2 error --if-stale 24; grep -q "SCAN INCOMPLETE" "$TMP/cve.out"; not_in_out "OK"
expect_cve 2 error --if-stale 24
expect_cve 0 clean --if-stale 24; not_in_out "cached"

# Findings -> exit 1, reported distinctly from scan errors, never cached as clean
expect_cve 1 vuln; grep -q "CVE ALERT" "$TMP/cve.out"; not_in_out "scan error"
expect_cve 0 clean --if-stale 24; not_in_out "cached"

# No scanner available at all -> exit 2, then a later clean scan re-runs
printf '{"lockfileVersion": 3, "name": "changed-third"}\n' > "$REPO_TMP/package-lock.json"
rc=0
PATH="$MINBIN" XDG_CACHE_HOME="$TMP/cache" bash "$ROOT/hooks/cve-check.sh" --repo "$REPO_TMP" --if-stale 24 > "$TMP/cve.out" 2>&1 || rc=$?
test "$rc" -eq 2; grep -q "no CVE scanner installed" "$TMP/cve.out"
expect_cve 0 clean --if-stale 24; not_in_out "cached"
echo "OK: pre-push hook & CVE check verified"

echo "5. Running public-safety scan..."
failed=0
content_pattern='/Users/|/home/[^<]|github_pat_|gh[pousr]_[A-Za-z0-9]{20,}|sk-((proj|svcacct)-)?[A-Za-z0-9_-]{20,}|BEGIN [A-Z ]*PRIVATE KEY|Bearer [A-Za-z0-9._~+/=-]{16,}'
while IFS= read -r -d '' file; do
  [ "$file" = "tests/test_v2.sh" ] && continue
  base="$(basename "$file")"
  case "$base" in
    .env|.env.*|.npmrc|*credential*|*secret*|.caphe.local.toml)
      echo "sensitive filename: $file" >&2
      failed=1
      ;;
  esac
  if [ ! -L "$file" ] && [ -f "$file" ] && grep -qE "$content_pattern" "$file"; then
    echo "public-safety content finding: $file" >&2
    failed=1
  fi
done < <(git ls-files --cached --others --exclude-standard -z)

[ "$failed" -eq 0 ]
echo "ALL V2 CHECKS PASSED."
