#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
while IFS= read -r script; do bash -n "$script"; done < <(find "$ROOT/strict-mode/bin" "$ROOT/strict-mode/test" -type f -name '*.sh' -print)
python3 -m py_compile "$ROOT/strict-mode/bin/strict_gate.py" "$ROOT/strict-mode/bin/strict_evidence.py"
python3 -m py_compile "$ROOT/memory/mempalace_adapter.py" "$ROOT/memory/export_codex_memory.py" "$ROOT/memory/benchmark_memory.py" "$ROOT/memory/sync_mempalace.py" "$ROOT/memory/resolve_codex_memory.py"
