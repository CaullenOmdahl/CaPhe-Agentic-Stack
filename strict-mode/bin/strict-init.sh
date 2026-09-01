#!/usr/bin/env bash
# Initialize or refresh a repository with Strict Mode v2 (ADR-0001).
set -uo pipefail

CANON="$HOME/strict-mode"
TEMPLATE="$CANON/templates/instruction-section.md"
BEGIN_MARKER='<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->'
END_MARKER='<!-- STRICT-MODE:END -->'
ACTIVE_TMP=""

cleanup_active_tmp() {
  if [ -n "$ACTIVE_TMP" ] && [ -e "$ACTIVE_TMP" ]; then rm -f -- "$ACTIVE_TMP"; fi
}
handle_signal() { cleanup_active_tmp; trap - EXIT; exit 130; }
trap cleanup_active_tmp EXIT
trap handle_signal HUP INT TERM

for required_source in \
  "$TEMPLATE" \
  "$CANON/templates/adr-template.md" \
  "$CANON/templates/OWNERS.md" \
  "$CANON/templates/dod-checklist.md" \
  "$CANON/templates/abstraction-template.md" \
  "$CANON/bin/pre-commit" \
  "$CANON/bin/strict-green-gate.sh" \
  "$CANON/bin/strict_gate.py" \
  "$CANON/bin/strict_evidence.py"; do
  if [ ! -r "$required_source" ] || [ ! -s "$required_source" ]; then
    echo "strict-mode init: missing or unreadable required source: $required_source" >&2
    exit 1
  fi
done

marker_state() {
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin {begins++; if (begins == 1) begin_line=NR}
    $0 == end   {ends++; if (ends == 1) end_line=NR}
    END {
      if (begins == 0 && ends == 0) {print "none"; exit 0}
      if (begins == 1 && ends == 1 && begin_line < end_line) {print "managed"; exit 0}
      exit 2
    }
  ' "$1"
}

if [ "$(marker_state "$TEMPLATE" 2>/dev/null)" != managed ]; then
  echo "strict-mode init: instruction template has malformed managed markers: $TEMPLATE" >&2
  exit 1
fi

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$ROOT" || exit 1
echo "strict-mode init → $ROOT"

# Preflight before any repository write. Symlink aliases are managed through their canonical target.
for f in CLAUDE.md AGENTS.md GEMINI.md; do
  if [ ! -L "$f" ] && [ -f "$f" ] && ! marker_state "$f" >/dev/null; then
    echo "strict-mode init: $f has malformed or duplicate strict-mode markers; repository left unchanged" >&2
    exit 1
  fi
done

mkdir -p .agent/decisions .agent/abstraction .agent/evidence .claude || exit 1
cp_if_absent() { [ -f "$2" ] || { cp "$1" "$2" && echo "  + $2"; }; }
cp_if_absent "$CANON/templates/adr-template.md" .agent/decisions/0000-adr-template.md || exit 1
cp_if_absent "$CANON/templates/OWNERS.md" .agent/OWNERS.md || exit 1
cp_if_absent "$CANON/templates/dod-checklist.md" .agent/dod-checklist.md || exit 1
cp_if_absent "$CANON/templates/abstraction-template.md" .agent/abstraction/TEMPLATE.md || exit 1
if [ ! -f .agent/traceability.md ]; then
  printf '# Traceability\n\n> Generated from `.agent/evidence/*.json`.\n' > .agent/traceability.md || exit 1
  echo "  + .agent/traceability.md"
fi
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && [ ! -f .agent/strict-gate.json ]; then
  python3 "$CANON/bin/strict_gate.py" --write-default-manifest || exit 1
fi
printf '%s\n' '2' > .agent/.strict-version || exit 1

inject() {
  local f="$1" state tmp
  if [ -L "$f" ]; then
    echo "  . $f is a symlink — target managed through its canonical file"
    return 0
  fi
  state=none
  if [ -f "$f" ]; then state=$(marker_state "$f") || return 1; fi
  tmp=$(mktemp "${f}.strict-mode.XXXXXX") || return 1
  ACTIVE_TMP="$tmp"
  if [ -f "$f" ]; then cp -p "$f" "$tmp" || return 1; else chmod 644 "$tmp" || return 1; fi
  if [ "$state" = managed ]; then
    if ! awk -v repl_file="$TEMPLATE" -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
      function replacement(line, result) {
        while ((result = getline line < repl_file) > 0) print line
        close(repl_file); if (result < 0) exit 3
      }
      $0 == begin {replacement(); skip=1; next}
      $0 == end {skip=0; next}
      !skip
    ' "$f" > "$tmp"; then
      echo "  ! $f (strict section refresh failed)" >&2; return 1
    fi
  else
    if [ -f "$f" ]; then printf '\n' >> "$tmp" || return 1; fi
    cat "$TEMPLATE" >> "$tmp" || return 1
    printf '\n' >> "$tmp" || return 1
  fi
  mv "$tmp" "$f" || return 1
  ACTIVE_TMP=""
  if [ "$state" = managed ]; then echo "  ~ $f (strict section refreshed)"; else echo "  + $f (strict section added)"; fi
}

for f in CLAUDE.md AGENTS.md GEMINI.md; do inject "$f" || exit 1; done

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  exclude=$(git rev-parse --git-path info/exclude) || exit 1
  case "$exclude" in /*) ;; *) exclude="$ROOT/$exclude" ;; esac
  mkdir -p "$(dirname "$exclude")" || exit 1
  touch "$exclude" || exit 1
  grep -qxF '.agent/.strict-mode' "$exclude" 2>/dev/null || printf '%s\n' '.agent/.strict-mode' >> "$exclude"
  hook=$(git rev-parse --git-path hooks/pre-commit) || exit 1
  mkdir -p "$(dirname "$hook")" || exit 1
  if [ -f "$hook" ] && ! grep -qx '# STRICT-MODE:MANAGED-HOOK v2' "$hook"; then
    echo "  ! $hook exists and is not ours — left intact"
  else
    cp "$CANON/bin/pre-commit" "$hook" && chmod +x "$hook" || exit 1
    echo "  + $hook (focused green-gate)"
  fi
fi

if [ ! -f .claude/settings.json ]; then
  cat > .claude/settings.json <<'JSON'
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "$HOME/strict-mode/bin/strict-green-gate.sh --mode completion || true" } ] }
    ]
  }
}
JSON
  echo "  + .claude/settings.json (advisory completion report)"
fi

echo "done. STRICT MODE active. Pre-commit gives FAST GREEN; completion requires --mode completion."
