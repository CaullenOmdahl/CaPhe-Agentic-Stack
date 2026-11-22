#!/usr/bin/env bash
# CaPhe Agentic Stack v2 — idempotent, non-destructive machine installer.
# Installs lean global canon, managed entrypoint blocks, on-demand skills, and tiered subagent profiles.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APPLY_SETTINGS=0

for arg in "$@"; do
  case "$arg" in
    --apply-settings) APPLY_SETTINGS=1 ;;
    -h|--help)
      echo "Usage: ./install.sh [--apply-settings]"
      echo "  Installs ~/AGENTS_GLOBAL.md, managed entrypoint pointers, on-demand skills, and tiered agent profiles."
      echo "  --apply-settings  Also merge non-destructive tiered subagent defaults into Claude & Codex settings."
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

MARKER_BEGIN="<!-- CAPHE:V2:BEGIN -->"
MARKER_END="<!-- CAPHE:V2:END -->"

upsert_managed_block() {
  local target="$1"
  local block="$2"
  mkdir -p "$(dirname "$target")"
  python3 - "$target" "$MARKER_BEGIN" "$MARKER_END" "$block" <<'PY'
import pathlib, re, sys
target = pathlib.Path(sys.argv[1])
begin, end, body = sys.argv[2], sys.argv[3], sys.argv[4].strip()
managed = f"{begin}\n{body}\n{end}\n"
if target.exists():
    text = target.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.S)
    if pattern.search(text):
        new_text = pattern.sub(managed, text, count=1)
    else:
        sep = "\n\n" if text and not text.endswith("\n\n") else ("\n" if text and not text.endswith("\n") else "")
        new_text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + managed
else:
    new_text = managed
target.write_text(new_text, encoding="utf-8")
PY
}

# 1. Global canon (~55 lines, static & cache-friendly)
cp "$SRC/docs/canon.md" "$HOME/AGENTS_GLOBAL.md"

# 2. Managed pointer blocks (preserves existing personal machine instructions)
CLAUDE_BLOCK="## CaPhe Agentic Stack (v2)
Read \`~/AGENTS_GLOBAL.md\` and treat it as binding unless overridden by the user or a repo's \`.caphe.toml\`.
Use Plan Mode for non-trivial changes, route exploration to \`explorer\` (haiku) and scoped coding to \`worker\` (sonnet), and load skills on demand only when relevant."

CODEX_BLOCK="## CaPhe Agentic Stack (v2)
Read \`~/AGENTS_GLOBAL.md\` and treat it as binding unless overridden by the user or a repo's \`.caphe.toml\`.
Delegate exploration to \`explorer\` (low effort), scoped coding to \`worker\` (medium effort), and load skills on demand only when relevant."

GEMINI_BLOCK="## CaPhe Agentic Stack (v2)
Read \`~/AGENTS_GLOBAL.md\` and treat it as binding unless overridden by the user or a repo's \`.caphe.toml\`.
Delegate read-only lookups to \`flash\` subagents, reserve frontier models for planning/review, and load skills on demand only when relevant."

upsert_managed_block "$HOME/.claude/CLAUDE.md" "$CLAUDE_BLOCK"
upsert_managed_block "$HOME/.codex/AGENTS.md" "$CODEX_BLOCK"
upsert_managed_block "$HOME/.gemini/GEMINI.md" "$GEMINI_BLOCK"

# 3. Install bite-sized, on-demand skills to standard agent skill directories
SKILL_DIRS=(
  "$HOME/.claude/skills"
  "$HOME/.codex/skills"
  "$HOME/.gemini/config/skills"
  "$HOME/.agents/skills"
)

for sdir in "${SKILL_DIRS[@]}"; do
  mkdir -p "$sdir"
  for skill in "$SRC"/skills/*; do
    [ -d "$skill" ] || continue
    name="$(basename "$skill")"
    rm -rf "$sdir/$name"
    cp -R "$skill" "$sdir/$name"
  done
done

# 4. Install tiered subagent definitions (explorer / worker / reviewer)
mkdir -p "$HOME/.claude/agents" "$HOME/.codex/agents"
cp "$SRC"/templates/claude/agents/*.md "$HOME/.claude/agents/"
cp "$SRC"/templates/codex/agents/*.toml "$HOME/.codex/agents/"

# 5. Optional: merge non-destructive tiered settings into Claude & Codex configs
if [ "$APPLY_SETTINGS" -eq 1 ]; then
  TS="$(date +%Y%m%dT%H%M%S)"

  # Claude settings.json merge (preserves plugins, voice, statusLine, existing env keys)
  CLAUDE_SETTINGS="$HOME/.claude/settings.json"
  mkdir -p "$HOME/.claude"
  if [ -f "$CLAUDE_SETTINGS" ]; then
    cp "$CLAUDE_SETTINGS" "${CLAUDE_SETTINGS}.bak-${TS}"
  fi
  python3 - "$CLAUDE_SETTINGS" "$SRC/templates/claude/settings.json" <<'PY'
import json, pathlib, sys
target = pathlib.Path(sys.argv[1])
tmpl = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
cur = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
env = dict(cur.get("env") or {})
for k, v in (tmpl.get("env") or {}).items():
    env[k] = v
cur["env"] = env
cur["effortLevel"] = tmpl["effortLevel"]
cur["enableWorkflows"] = tmpl["enableWorkflows"]
target.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")
PY

  # Codex config.toml managed block (preserves MCPs, projects, and custom settings)
  CODEX_CFG="$HOME/.codex/config.toml"
  mkdir -p "$HOME/.codex"
  if [ -f "$CODEX_CFG" ]; then
    cp "$CODEX_CFG" "${CODEX_CFG}.bak-${TS}"
  fi
  python3 - "$CODEX_CFG" <<'PY'
import pathlib, re, sys
target = pathlib.Path(sys.argv[1])
begin = "# CAPHE:V2:BEGIN"
end = "# CAPHE:V2:END"
block = f"""{begin}
[agents]
enabled = true
max_concurrent_threads_per_session = 6
default_subagent_reasoning_effort = "low"
{end}
"""
text = target.read_text(encoding="utf-8") if target.exists() else ""
pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.S)
if pattern.search(text):
    new_text = pattern.sub(block, text, count=1)
elif re.search(r"(?m)^\[agents\]\s*$", text):
    # Preserve existing [agents] table rather than duplicating TOML section headers
    new_text = text
else:
    new_text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + block
target.write_text(new_text, encoding="utf-8")
PY
fi

echo "CaPhe Agentic Stack v2 installed."
echo "  Canon:   $HOME/AGENTS_GLOBAL.md"
echo "  Skills:  $(ls -1 "$SRC/skills" | tr '\n' ' ')"
echo "  Agents:  explorer, worker, reviewer (Claude & Codex)"
if [ "$APPLY_SETTINGS" -eq 1 ]; then
  echo "  Config:  merged tiered subagent defaults into ~/.claude/settings.json & ~/.codex/config.toml"
fi
