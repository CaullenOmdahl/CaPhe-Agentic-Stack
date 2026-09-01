#!/usr/bin/env python3
"""Resolve one MemPalace result to freshly sanitized canonical Codex evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat

from mempalace_adapter import IsolationError, resolve_catalog_event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--source-event", required=True, type=int)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--index-generation", required=True)
    args = parser.parse_args()
    mapping_path = Path(args.mapping).resolve()
    if not mapping_path.is_file() or stat.S_IMODE(mapping_path.stat().st_mode) & 0o077:
        raise SystemExit("mapping file must be owner-only")
    mappings = json.loads(mapping_path.read_text())
    try:
        resolved = resolve_catalog_event(
            Path(args.catalog),
            source_id=args.source_id,
            source_event=args.source_event,
            expected_sha256=args.source_sha256,
            expected_scope=args.domain,
            mappings=mappings,
            index_generation=args.index_generation,
        )
    except IsolationError as error:
        raise SystemExit(f"memory resolution failed: {error}") from error
    print(resolved.framed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
