#!/usr/bin/env bash
# CaPhe Agentic Stack v2 verification suite:
# 1) Shell syntax, JSON & TOML validity
# 2) Context-budget checks (always-loaded canon stays tiny)
# 3) Sandboxed installer idempotency, non-destructive merge & collision-safety tests
# 4) Pre-push hook execution test
# 5) Public-safety scan (no secrets, private paths, or sensitive filenames) + no hard-coded model names
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
unset XDG_CONFIG_HOME XDG_STATE_HOME XDG_CACHE_HOME ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY CAPHE_ANTHROPIC_BASE_URL CAPHE_OPENAI_BASE_URL CAPHE_GEMINI_BASE_URL

echo "1. Checking shell syntax..."
bash -n install.sh hooks/pre-push-check.sh hooks/cve-check.sh tests/test_v2.sh
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" bin/caphe-models

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
assert "CLAUDE_CODE_SUBAGENT_MODEL" not in cs["env"], "unset standard tier must not set a subagent model"
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
cp -R "$ROOT/install.sh" "$ROOT/bin" "$ROOT/docs" "$ROOT/skills" "$ROOT/templates" "$ROOT/hooks" "$UPSRC/"
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

echo "3b. Testing provider-neutral model tiers (caphe-models)..."
MT="$TMP/tiers"
mkdir -p "$MT"
cat > "$MT/mock_providers.py" <<'EOF'
import http.server, json, sys, urllib.parse

ANTHROPIC = [
    {"id": "anth-c", "display_name": "Anth C", "lifecycle": "active"},
    {"id": "anth-b", "display_name": "Anth B", "lifecycle": "active"},
    {"id": "anth-old", "display_name": "Anth Old", "lifecycle": "deprecated"},
    {"id": "anth-a", "display_name": "Anth A", "lifecycle": "active"},
]
GEMINI = [
    {"name": "models/gem-pro", "displayName": "Gem Pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gem-embed", "displayName": "Gem Embed", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gem-lite", "displayName": "Gem Lite", "supportedGenerationMethods": ["countTokens", "generateContent"]},
]

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        url = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(url.query)
        if url.path == "/anthropic/v1/models" and self.headers.get("x-api-key") == "test-loop":
            return self.reply(200, {"data": ANTHROPIC[:1], "has_more": True, "last_id": "same-cursor"})
        if url.path == "/anthropic/v1/models" and self.headers.get("x-api-key") == "test-redirect":
            self.send_response(302); self.send_header("Location", "http://example.invalid/steal"); self.end_headers(); return
        if url.path == "/anthropic/v1/models":
            if self.headers.get("x-api-key") != "test-anth" or not self.headers.get("anthropic-version"):
                return self.reply(401, {"error": "bad key"})
            if q.get("after_id") == ["anth-b"]:
                return self.reply(200, {"data": ANTHROPIC[2:], "has_more": False, "last_id": "anth-a"})
            return self.reply(200, {"data": ANTHROPIC[:2], "has_more": True, "last_id": "anth-b"})
        if url.path == "/openai/v1/models":
            if self.headers.get("Authorization") != "Bearer test-oai":
                return self.reply(401, {"error": "bad key"})
            return self.reply(200, {"object": "list", "data": [{"id": "oai-y", "object": "model"}, {"id": "oai-x", "object": "model"}]})
        if url.path == "/gemini/v1beta/models":
            if self.headers.get("x-goog-api-key") != "test-gem" or "key" in q:
                return self.reply(401, {"error": "bad key"})
            if q.get("pageToken") == ["p2"]:
                return self.reply(200, {"models": GEMINI[2:]})
            return self.reply(200, {"models": GEMINI[:2], "nextPageToken": "p2"})
        self.reply(404, {"error": "not found"})

srv = http.server.HTTPServer(("127.0.0.1", 0), H)
open(sys.argv[1], "w").write(str(srv.server_port))
srv.serve_forever()
EOF
python3 "$MT/mock_providers.py" "$MT/port" &
MOCK_PID=$!
trap 'kill "$MOCK_PID" 2>/dev/null || true; rm -rf "$TMP"' EXIT
for _ in $(seq 50); do [ -s "$MT/port" ] && break; read -r -t 0.1 <> <(:) || true; done
PORT="$(cat "$MT/port")"

export XDG_CONFIG_HOME="$MT/config" XDG_STATE_HOME="$MT/state"
export CAPHE_ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT/anthropic" CAPHE_OPENAI_BASE_URL="http://127.0.0.1:$PORT/openai" CAPHE_GEMINI_BASE_URL="http://127.0.0.1:$PORT/gemini"
CM=(python3 "$ROOT/bin/caphe-models")

# No keys -> every provider skipped, nothing stored, exit 0
OUT="$("${CM[@]}" fetch)"
test "$(grep -c 'skipped' <<<"$OUT")" -eq 3
test ! -e "$MT/state/caphe/models"

# Wrong key -> FAILED, exit 1, nothing stored
rc=0; ANTHROPIC_API_KEY=wrong "${CM[@]}" fetch claude > "$MT/out" 2>&1 || rc=$?
test "$rc" -eq 1; grep -q "claude: FAILED" "$MT/out"; test ! -e "$MT/state/caphe/models/claude.json"

# Real fetch: pagination followed, deprecated/non-generative filtered, Gemini prefix stripped, keys never stored
ANTHROPIC_API_KEY=test-anth OPENAI_API_KEY=test-oai GEMINI_API_KEY=test-gem "${CM[@]}" fetch > "$MT/out"
python3 - "$MT/state/caphe/models" <<'PY'
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])
ids = lambda c: [m["id"] for m in json.loads((d / f"{c}.json").read_text())["models"]]
assert ids("claude") == ["anth-a", "anth-b", "anth-c"], ids("claude")
assert ids("codex") == ["oai-x", "oai-y"], ids("codex")
assert ids("gemini") == ["gem-lite", "gem-pro"], ids("gemini")
blob = "".join(p.read_text() for p in d.glob("*.json"))
assert "test-anth" not in blob and "test-oai" not in blob and "test-gem" not in blob, "API key leaked into state"
PY
"${CM[@]}" list claude | grep -q "anth-b  (Anth B)"

# set: known ID saves cleanly; unknown value warns but saves (client aliases are legitimate)
"${CM[@]}" set claude fast anth-a 2> "$MT/err" >/dev/null; test ! -s "$MT/err"
"${CM[@]}" set claude standard my-alias 2> "$MT/err" >/dev/null; grep -q "not in the fetched claude list" "$MT/err"
"${CM[@]}" set claude frontier anth-c >/dev/null 2>&1
"${CM[@]}" set codex standard oai-x >/dev/null 2>&1
test "$("${CM[@]}" get claude fast)" = "anth-a"
test -z "$("${CM[@]}" get gemini fast)"

# Precedence: .caphe.local.toml > .caphe.toml > global
RP="$MT/repo"; mkdir -p "$RP"
printf '[models.claude]\nfast = "repo-fast"\nstandard = "repo-standard"\n' > "$RP/.caphe.toml"
printf '[models.claude]\nfast = "local-fast"\n' > "$RP/.caphe.local.toml"
test "$("${CM[@]}" get claude fast --repo "$RP")" = "local-fast"
test "$("${CM[@]}" get claude standard --repo "$RP")" = "repo-standard"
test "$("${CM[@]}" get claude frontier --repo "$RP")" = "anth-c"
"${CM[@]}" show --repo "$RP" | grep -E '^claude +fast +local-fast' | grep -q '.caphe.local.toml'

# Review hardening: repeated cursor terminates, redirects refused, bad values/types rejected cleanly
timeout 20 env ANTHROPIC_API_KEY=test-loop "${CM[@]}" fetch claude >/dev/null
rc=0; ANTHROPIC_API_KEY=test-redirect "${CM[@]}" fetch claude > "$MT/out" 2>&1 || rc=$?
test "$rc" -eq 1; grep -q "claude: FAILED" "$MT/out"
ANTHROPIC_API_KEY=test-anth "${CM[@]}" fetch claude >/dev/null   # restore the real list
rc=0; "${CM[@]}" set codex fast 'bad"value' > "$MT/out" 2>&1 || rc=$?
test "$rc" -eq 2; grep -q "invalid model value" "$MT/out"; test -z "$("${CM[@]}" get codex fast)"
BAD="$MT/badrepo"; mkdir -p "$BAD"
printf '[models.claude]\nfast = "x: [y]"\n' > "$BAD/.caphe.toml"
rc=0; "${CM[@]}" get claude fast --repo "$BAD" > "$MT/out" 2>&1 || rc=$?
test "$rc" -eq 2; grep -q "invalid model value" "$MT/out"
printf 'models = "oops"\n' > "$BAD/.caphe.toml"
rc=0; "${CM[@]}" show --repo "$BAD" > "$MT/out" 2>&1 || rc=$?
test "$rc" -eq 2; grep -q "must be a table" "$MT/out"; ! grep -q Traceback "$MT/out"

# Installer preflight: a broken tier config aborts before anything is written
TB="$MT/home-broken"; mkdir -p "$TB/.config/caphe"
printf 'claude = "not a table"\n' > "$TB/.config/caphe/models.toml"
rc=0; HOME="$TB" XDG_CONFIG_HOME="$TB/.config" XDG_STATE_HOME="$TB/state" bash "$ROOT/install.sh" > "$MT/out" 2>&1 || rc=$?
test "$rc" -eq 1; grep -q "nothing was installed" "$MT/out"
test ! -e "$TB/AGENTS_GLOBAL.md"; test ! -e "$TB/.claude/skills"

# Install with tiers unset -> no model lines anywhere, warning lists unset tiers, settings untouched
TU="$MT/home-unset"; mkdir -p "$TU"
OUT="$(HOME="$TU" XDG_CONFIG_HOME="$TU/.config" XDG_STATE_HOME="$TU/state" bash "$ROOT/install.sh" --apply-settings)"
echo "$OUT" | grep -q "tiers not configured (claude.fast claude.standard claude.frontier codex.fast"
if grep -qE '^model( =|:)' "$TU"/.claude/agents/*.md "$TU"/.codex/agents/*.toml; then echo "unset tier rendered a model line" >&2; exit 1; fi
if grep -q '{{tier' "$TU"/.claude/agents/*.md "$TU"/.codex/agents/*.toml; then echo "placeholder leaked into installed profile" >&2; exit 1; fi
test -x "$TU/.local/bin/caphe-models"

# Install with tiers set -> rendered models, standard tier becomes CLAUDE_CODE_SUBAGENT_MODEL
TS_HOME="$MT/home-set"; mkdir -p "$TS_HOME"
OUT="$(HOME="$TS_HOME" bash "$ROOT/install.sh" --apply-settings)"
grep -qx 'model: anth-a' "$TS_HOME/.claude/agents/explorer.md"
grep -qx 'model: my-alias' "$TS_HOME/.claude/agents/worker.md"
grep -qx 'model: anth-c' "$TS_HOME/.claude/agents/reviewer.md"
grep -qx 'model = "oai-x"' "$TS_HOME/.codex/agents/worker.toml"
if grep -qE '^model( =|:)' "$TS_HOME/.codex/agents/explorer.toml"; then echo "unset codex.fast rendered a model line" >&2; exit 1; fi
echo "$OUT" | grep -q "codex.fast codex.frontier"
python3 - "$TS_HOME" <<'PY'
import json, pathlib, sys, tomllib
home = pathlib.Path(sys.argv[1])
assert json.loads((home / ".claude/settings.json").read_text())["env"]["CLAUDE_CODE_SUBAGENT_MODEL"] == "my-alias"
for f in (home / ".codex/agents").glob("*.toml"):
    a = tomllib.loads(f.read_text())
    assert a["name"] and a["description"] and a["developer_instructions"].strip(), f
    assert "model_reasoning_effort" in a and "reasoning_effort" not in a and "sandbox_mode" not in a, f
PY

# Tier change -> untouched profiles re-render on the next install, with no backups
"${CM[@]}" set claude fast anth-b >/dev/null 2>&1
HOME="$TS_HOME" bash "$ROOT/install.sh" >/dev/null
grep -qx 'model: anth-b' "$TS_HOME/.claude/agents/explorer.md"
test ! -d "$MT/state/caphe/backups"

kill "$MOCK_PID" 2>/dev/null || true
trap 'rm -rf "$TMP"' EXIT
unset XDG_CONFIG_HOME XDG_STATE_HOME CAPHE_ANTHROPIC_BASE_URL CAPHE_OPENAI_BASE_URL CAPHE_GEMINI_BASE_URL
echo "OK: model lists fetched & filtered, tier precedence, rendering with tiers set/unset, re-render on change"

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

# Provider-neutral guard: no model names hard-coded outside tests/
model_pattern='\b(haiku|sonnet|opus|fable|mythos|flash|luna|terra|astra|gpt-[0-9][a-z0-9.-]*|gemini-[0-9][a-z0-9.-]*|claude-[a-z]+-[0-9][a-z0-9-]*)\b'
if git grep -n -i -E "$model_pattern" -- . ':!tests/' >&2; then
  echo "hard-coded model name(s) found above; use tier placeholders ({{tier:fast|standard|frontier}}) instead" >&2
  failed=1
fi

[ "$failed" -eq 0 ]
echo "ALL V2 CHECKS PASSED."
