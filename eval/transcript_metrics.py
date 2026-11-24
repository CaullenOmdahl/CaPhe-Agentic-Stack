#!/usr/bin/env python3
"""Extract trial metrics from a Claude Code `--output-format stream-json --verbose` transcript.

Usage: python3 eval/transcript_metrics.py <transcript.jsonl> [client_exit_code]
Prints one tab-separated line: seconds, tokens, cost_usd, verification(yes|no), models, notes.

"Verification ran" means a Bash call actually invoked a test runner. Merely reading test files
(cat, sed, grep on test_*.py) does not count.
"""
import json
import re
import sys

TEST_RUNNER = re.compile(
    r"\bpython3?\s+(-\w+\s+)*-m\s+(unittest|pytest)\b"   # python -m unittest / python3 -B -m pytest
    r"|(^|[\s;&|(])pytest\b"                              # pytest ...
    r"|\bnode\s+(\S+\s+)*\S*test\S*"                      # node tests/check.js, node --test
    r"|\bnpm\s+(run\s+)?test\b"
)


def runs_tests(command: str) -> bool:
    return bool(TEST_RUNNER.search(command))


def main() -> int:
    path = sys.argv[1]
    client_exit = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    result, bash, agents = {}, [], 0
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            result = ev
        for block in (ev.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("name") == "Bash":
                    bash.append(str((block.get("input") or {}).get("command", "")))
                elif block.get("name") in ("Agent", "Task"):
                    agents += 1
    usage = result.get("usage") or {}
    tokens = sum(int(usage.get(k) or 0) for k in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    cost = result.get("total_cost_usd")
    print("\t".join([
        str(round((result.get("duration_ms") or 0) / 1000, 1)),
        str(tokens or "null"),
        "null" if cost is None else str(cost),
        "yes" if any(runs_tests(c) for c in bash) else "no",
        ",".join(sorted((result.get("modelUsage") or {}).keys())) or "unknown",
        f"turns={result.get('num_turns')};subagents={agents};client_exit={client_exit};is_error={result.get('is_error')}",
    ]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
