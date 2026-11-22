#!/usr/bin/env bash
# Opt-in git pre-push verification hook (NOT a post-turn Stop hook).
# Reads [verify] commands from .caphe.toml (with .caphe.local.toml overrides) if present.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if [ "${CAPHE_SKIP_PRE_PUSH:-0}" = "1" ]; then
  echo "caphe pre-push: skipped via CAPHE_SKIP_PRE_PUSH=1"
  exit 0
fi

if [ -f ".caphe.toml" ] || [ -f ".caphe.local.toml" ]; then
  if command -v python3 >/dev/null 2>&1; then
    mapfile -t CMDS < <(python3 - <<'PY'
import pathlib, tomllib
cfg = {}
for name in (".caphe.toml", ".caphe.local.toml"):
    p = pathlib.Path(name)
    if p.is_file():
        data = tomllib.loads(p.read_text(encoding="utf-8"))
        for k, v in (data.get("verify") or {}).items():
            if isinstance(v, str) and v.strip():
                cfg[k] = v.strip()
for key in ("typecheck", "lint", "test", "build"):
    if key in cfg:
        print(f"{key}\t{cfg[key]}")
PY
)
    if [ "${#CMDS[@]}" -gt 0 ]; then
      for entry in "${CMDS[@]}"; do
        stage="${entry%%$'\t'*}"
        cmd="${entry#*$'\t'}"
        echo "caphe pre-push [$stage]: $cmd"
        bash -c "$cmd"
      done
      exit 0
    fi
  fi
fi

echo "caphe pre-push: no [verify] commands declared in .caphe.toml; skipping."
