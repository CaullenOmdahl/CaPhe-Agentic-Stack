#!/usr/bin/env bash
# CaPhe Agentic Stack v2 — idempotent, non-destructive machine installer.
# Installs lean global canon, managed entrypoint blocks, on-demand skills, and tiered subagent profiles.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APPLY_SETTINGS=0
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --apply-settings) APPLY_SETTINGS=1 ;;
    --force) FORCE=1 ;;
    -h|--help)
      echo "Usage: ./install.sh [--apply-settings] [--force]"
      echo "  Installs ~/AGENTS_GLOBAL.md, managed entrypoint pointers, on-demand skills, and tiered agent profiles."
      echo "  Locally customized or foreign same-named files are preserved and listed, never overwritten by default."
      echo "  --apply-settings  Also merge non-destructive tiered subagent defaults into Claude & Codex settings."
      echo "  --force           Replace preserved files with the stack version, backing them up first."
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Stack-managed content tracking: a file/dir is replaced silently only when it is missing, already identical,
# or byte-identical to what this installer last wrote (recorded in the manifest). Anything else is a local
# customization or unrelated same-named content: preserved by default, or backed up then replaced with --force.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/caphe"
MANIFEST="$STATE_DIR/install-manifest.tsv"
TS="$(date +%Y%m%dT%H%M%S)"
BACKUP_DIR="$STATE_DIR/backups/$TS"
PRESERVED=()
BACKED_UP=0
mkdir -p "$STATE_DIR"
touch "$MANIFEST"
# Lets `caphe-models mark-unavailable` print the exact re-render command.
printf '%s\n' "$SRC" > "$STATE_DIR/install-source"

tree_hash() {
  if [ -d "$1" ]; then
    (cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum) | sha256sum | cut -c1-64
  else
    sha256sum < "$1" | cut -c1-64
  fi
}

manifest_get() {
  awk -F '\t' -v p="$1" '$1 == p { h = $2 } END { print h }' "$MANIFEST"
}

manifest_set() {
  local tmp="$MANIFEST.tmp"
  awk -F '\t' -v p="$1" '$1 != p' "$MANIFEST" > "$tmp"
  printf '%s\t%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$MANIFEST"
}

install_item() {
  local src="$1" dest="$2" new cur
  new="$(tree_hash "$src")"
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    cur="$(tree_hash "$dest" 2>/dev/null || true)"
    if [ "$cur" = "$new" ]; then
      manifest_set "$dest" "$new"
      return 0
    fi
    if [ "$cur" != "$(manifest_get "$dest")" ]; then
      if [ "$FORCE" -ne 1 ]; then
        PRESERVED+=("$dest")
        return 0
      fi
      local rel="${dest#"$HOME"/}"
      mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
      cp -RP "$dest" "$BACKUP_DIR/$rel"
      BACKED_UP=1
    fi
    rm -rf "$dest"
  fi
  mkdir -p "$(dirname "$dest")"
  cp -R "$src" "$dest"
  manifest_set "$dest" "$new"
}

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

# 0. Preflight: model-tier rendering needs Python 3.11+ (tomllib) and a valid tier config. Fail before writing anything.
if ! python3 "$SRC/bin/caphe-models" show >/dev/null; then
  echo "install.sh: caphe-models is unusable (needs python3 >= 3.11 and a valid ~/.config/caphe/models.toml); nothing was installed." >&2
  exit 1
fi

# 1. Global canon (~40 lines, static & cache-friendly)
install_item "$SRC/docs/canon.md" "$HOME/AGENTS_GLOBAL.md"

# 2. Managed pointer blocks (preserves existing personal machine instructions)
CLAUDE_BLOCK="## CaPhe Agentic Stack (v2)
Read \`~/AGENTS_GLOBAL.md\` and treat it as binding unless overridden by the user or a repo's \`.caphe.toml\`.
Use Plan Mode for non-trivial changes, route exploration to \`explorer\` (fast tier), scoped coding to \`worker\` (standard tier), and production-risk review to \`reviewer\` (frontier tier); load skills on demand only when relevant."

CODEX_BLOCK="## CaPhe Agentic Stack (v2)
Read \`~/AGENTS_GLOBAL.md\` and treat it as binding unless overridden by the user or a repo's \`.caphe.toml\`.
Delegate exploration to \`explorer\` (fast tier), scoped coding to \`worker\` (standard tier), and production-risk review to \`reviewer\` (frontier tier); load skills on demand only when relevant."

GEMINI_BLOCK="## CaPhe Agentic Stack (v2)
Read \`~/AGENTS_GLOBAL.md\` and treat it as binding unless overridden by the user or a repo's \`.caphe.toml\`.
Delegate read-only lookups to fast-tier subagents, reserve the frontier tier for planning/review, and load skills on demand only when relevant. Resolve a tier to a model with \`caphe-models get gemini <tier>\`."

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
    install_item "$skill" "$sdir/$(basename "$skill")"
  done
done

# 4. Install tiered subagent definitions (explorer / worker / reviewer), rendered from provider-neutral
#    templates: {{tier:NAME}} resolves through caphe-models; unset tiers drop the model line (client default).
MODELS=(python3 "$SRC/bin/caphe-models")
RENDER_DIR="$(mktemp -d)"
trap 'rm -rf "$RENDER_DIR"' EXIT
UNSET_TIERS=()
for client in claude codex; do
  for tier in fast standard frontier; do
    [ -n "$("${MODELS[@]}" get "$client" "$tier")" ] || UNSET_TIERS+=("$client.$tier")
  done
done
for agent in "$SRC"/templates/claude/agents/*.md; do
  mkdir -p "$RENDER_DIR/claude"
  "${MODELS[@]}" render claude "$agent" > "$RENDER_DIR/claude/$(basename "$agent")"
  install_item "$RENDER_DIR/claude/$(basename "$agent")" "$HOME/.claude/agents/$(basename "$agent")"
done
for agent in "$SRC"/templates/codex/agents/*.toml; do
  mkdir -p "$RENDER_DIR/codex"
  "${MODELS[@]}" render codex "$agent" > "$RENDER_DIR/codex/$(basename "$agent")"
  install_item "$RENDER_DIR/codex/$(basename "$agent")" "$HOME/.codex/agents/$(basename "$agent")"
done

# CVE checker and the model-tier tool
install_item "$SRC/hooks/cve-check.sh" "$HOME/.local/bin/caphe-cve-check"
install_item "$SRC/bin/caphe-models" "$HOME/.local/bin/caphe-models"
for bin in caphe-cve-check caphe-models; do
  [ ! -f "$HOME/.local/bin/$bin" ] || chmod +x "$HOME/.local/bin/$bin"
done

# 5. Optional: merge non-destructive tiered settings into Claude & Codex configs
if [ "$APPLY_SETTINGS" -eq 1 ]; then

  # Claude settings.json merge (preserves plugins, voice, statusLine, existing env keys)
  CLAUDE_SETTINGS="$HOME/.claude/settings.json"
  mkdir -p "$HOME/.claude"
  if [ -f "$CLAUDE_SETTINGS" ]; then
    cp "$CLAUDE_SETTINGS" "${CLAUDE_SETTINGS}.bak-${TS}"
  fi
  python3 - "$CLAUDE_SETTINGS" "$SRC/templates/claude/settings.json" "$("${MODELS[@]}" get claude standard)" <<'PY'
import json, pathlib, sys
target = pathlib.Path(sys.argv[1])
tmpl = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
standard_tier = sys.argv[3]
cur = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
env = dict(cur.get("env") or {})
for k, v in (tmpl.get("env") or {}).items():
    env[k] = v
# Subagents without an explicit model default to the standard tier (only when it is configured).
if standard_tier:
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = standard_tier
cur["env"] = env
cur["effortLevel"] = tmpl["effortLevel"]
# Workflows (enableWorkflows / disableWorkflows) are the user's choice: never touched here.
target.write_text(json.dumps(cur, indent=2) + "\n", encoding="utf-8")
PY

  # Codex config.toml managed block (preserves MCPs, projects, and custom settings)
  CODEX_CFG="$HOME/.codex/config.toml"
  mkdir -p "$HOME/.codex"
  if [ -f "$CODEX_CFG" ]; then
    cp "$CODEX_CFG" "${CODEX_CFG}.bak-${TS}"
  fi
  python3 - "$CODEX_CFG" "$("${MODELS[@]}" get codex standard)" <<'PY'
import pathlib, re, sys
target = pathlib.Path(sys.argv[1])
standard_tier = sys.argv[2]  # already validated by caphe-models (plain token, safe inside TOML quotes)
begin = "# CAPHE:V2:BEGIN"
end = "# CAPHE:V2:END"
# Subagents without an explicit model default to the standard tier (only when it is configured).
model_line = f'default_subagent_model = "{standard_tier}"\n' if standard_tier else ""
block = f"""{begin}
[agents]
enabled = true
max_concurrent_threads_per_session = 6
default_subagent_reasoning_effort = "low"
{model_line}{end}
"""
text = target.read_text(encoding="utf-8") if target.exists() else ""
pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end) + r"\n?", re.S)
if pattern.search(text):
    new_text = pattern.sub(block, text, count=1)
elif re.search(r"(?m)^\[agents\]\s*$", text):
    # Preserve existing [agents] table rather than duplicating TOML section headers
    new_text = text
    print(f"  Note:    {target} already has its own [agents] table; left as is "
          "(add default_subagent_model there yourself if you want the standard tier as the subagent default)")
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
if [ "$BACKED_UP" -eq 1 ]; then
  echo "  Backups: replaced customizations saved under $BACKUP_DIR (copy back to restore)"
fi
if [ "${#UNSET_TIERS[@]}" -gt 0 ]; then
  echo "  Models:  tiers not configured (${UNSET_TIERS[*]}); those agents use the client's default model."
  echo "           Set them with: caphe-models set <client> <tier> <model-or-alias>"
  echo "           (no API key needed: use an alias or ID your client accepts; with a key, caphe-models fetch lists exact IDs)"
  echo "           then re-run ./install.sh to render the agent profiles."
fi
if [ "${#PRESERVED[@]}" -gt 0 ]; then
  echo "  Preserved (locally customized or not stack-managed; re-run with --force to back up and replace):"
  printf '    %s\n' "${PRESERVED[@]}"
fi
