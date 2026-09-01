#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

failed=0
while IFS= read -r -d '' file; do
  case "$file" in
    docs/public-safety.md|test/public-safety-test.sh|memory/mempalace_adapter.py|tests/test_memory_adapter.py) continue ;;
  esac
  base=$(basename "$file")
  case "$base" in
    .env|.env.*|.npmrc|*credential*|*secret*)
      echo "sensitive filename: $file" >&2
      failed=1
      ;;
  esac
  if grep -nE '/Users/|/home/[^<]|github_pat_|gh[pousr]_[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY|Bearer [A-Za-z0-9._~+/=-]{16,}' "$file"; then
    echo "public-safety content finding: $file" >&2
    failed=1
  fi
done < <(git ls-files --cached --others --exclude-standard -z)

[ "$failed" -eq 0 ]
