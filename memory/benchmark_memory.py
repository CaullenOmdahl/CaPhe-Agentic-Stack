#!/usr/bin/env python3
"""Score private recall runs without using an LLM as the acceptance oracle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mempalace_adapter import adoption_passes


def score(cases: list[dict], results: list[dict]) -> dict:
    by_id = {item["id"]: item for item in results}
    correct = 0
    recalled = 0
    tokens = 0
    citations_resolved = True
    secret_canaries = cross_domain_hits = injection_failures = 0
    for case in cases:
        result = by_id.get(case["id"], {})
        hits = result.get("source_ids", [])[:5]
        expected_sources = set(case["expected_source_ids"])
        recalled += int(bool(expected_sources.intersection(hits)))
        predicates = case.get("answer_predicates", [])
        answer = result.get("answer", "")
        correct += int(all(predicate in answer for predicate in predicates) and bool(expected_sources.intersection(hits)))
        tokens += int(result.get("retrieved_tokens", 0))
        citations_resolved = citations_resolved and bool(result.get("citations_resolved", False))
        secret_canaries += int(result.get("secret_canaries", 0))
        cross_domain_hits += int(result.get("cross_domain_hits", 0))
        injection_failures += int(result.get("injection_failures", 0))
    total = len(cases)
    return {
        "correct": correct,
        "total": total,
        "recall_at_5": recalled / total if total else 0.0,
        "tokens": tokens,
        "citations_resolved": citations_resolved,
        "secret_canaries": secret_canaries,
        "cross_domain_hits": cross_domain_hits,
        "injection_failures": injection_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    cases = json.loads(Path(args.cases).read_text())
    baseline = score(cases, json.loads(Path(args.baseline).read_text()))
    candidate = score(cases, json.loads(Path(args.candidate).read_text()))
    passed = adoption_passes(baseline, candidate)
    print(json.dumps({"baseline": baseline, "candidate": candidate, "adopt": passed}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
