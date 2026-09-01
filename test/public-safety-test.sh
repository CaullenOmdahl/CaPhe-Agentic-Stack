#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

failed=0
content_pattern='/Users/|/home/[^<]|github_pat_|gh[pousr]_[A-Za-z0-9]{20,}|sk-((proj|svcacct)-)?[A-Za-z0-9_-]{20,}|BEGIN [A-Z ]*PRIVATE KEY|Bearer [A-Za-z0-9._~+/=-]{16,}'

excluded_file() {
  case "$1" in
    docs/public-safety.md|test/public-safety-test.sh|memory/mempalace_adapter.py|tests/test_memory_adapter.py) return 0 ;;
  esac
  return 1
}

check_filename() {
  local file=$1
  local base
  base=$(basename "$file")
  case "$base" in
    .env|.env.*|.npmrc|*credential*|*secret*)
      echo "sensitive filename: $file" >&2
      failed=1
      ;;
  esac
}

while IFS= read -r -d '' entry; do
  metadata=${entry%%$'\t'*}
  file=${entry#*$'\t'}
  read -r mode object_id stage <<< "$metadata"
  case "$mode:$stage" in
    100644:0|100755:0) ;;
    *) continue ;;
  esac
  excluded_file "$file" && continue
  check_filename "$file"
  if git cat-file blob "$object_id" | grep -E "$content_pattern" >/dev/null; then
    echo "public-safety staged content finding: $file" >&2
    failed=1
  fi
done < <(git ls-files --stage -z)

while IFS= read -r -d '' file; do
  excluded_file "$file" && continue
  check_filename "$file"
  if [ ! -L "$file" ] && [ -f "$file" ] && grep -qE "$content_pattern" "$file"; then
    echo "public-safety content finding: $file" >&2
    failed=1
  fi
done < <(git ls-files --cached --others --exclude-standard -z)

[ "$failed" -eq 0 ]
