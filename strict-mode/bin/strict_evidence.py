#!/usr/bin/env python3
"""Write compact per-change strict-mode evidence and regenerate its index (ADR-0001)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


class EvidenceError(ValueError):
    pass


REQUIRED = ("id", "decision", "lane", "status", "tests", "review")


def validate_record(record: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED if field not in record]
    if missing:
        raise EvidenceError(f"missing evidence fields: {', '.join(missing)}")
    if not isinstance(record["id"], str) or not re.fullmatch(r"[A-Za-z0-9._-]+", record["id"]):
        raise EvidenceError("id must contain only letters, numbers, dot, underscore, or hyphen")
    if not isinstance(record["tests"], list) or any(not isinstance(item, str) for item in record["tests"]):
        raise EvidenceError("tests must be a list of strings")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(content)
        tmp = Path(handle.name)
    os.replace(tmp, path)


def write_record(root: Path, record: dict[str, Any]) -> Path:
    validate_record(record)
    path = root / ".agent" / "evidence" / f"{record['id']}.json"
    _atomic_write(path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path


def generate_index(root: Path) -> Path:
    evidence_dir = root / ".agent" / "evidence"
    rows: list[tuple[str, str, str, str, str]] = []
    for path in sorted(evidence_dir.glob("*.json")) if evidence_dir.exists() else []:
        record = json.loads(path.read_text())
        validate_record(record)
        rows.append((record["id"], record["decision"], record["lane"], record["status"], record["review"]))
    lines = [
        "# Traceability",
        "",
        "> Generated from `.agent/evidence/*.json`; edit the records, not this index.",
        "",
        "| Change | Decision | Lane | Status | Review |",
        "|---|---|---|---|---|",
    ]
    lines.extend(f"| {change} | {decision} | {lane} | {status} | {review} |" for change, decision, lane, status, review in rows)
    path = root / ".agent" / "traceability.md"
    _atomic_write(path, "\n".join(lines) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", nargs="?", help="JSON evidence record to write")
    parser.add_argument("--root", default=".")
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not args.index_only:
        if not args.record:
            parser.error("record is required unless --index-only is used")
        write_record(root, json.loads(Path(args.record).read_text()))
    generate_index(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
