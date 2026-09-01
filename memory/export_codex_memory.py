#!/usr/bin/env python3
"""Export sanitized, scoped Codex turns for isolated MemPalace pilot databases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from mempalace_adapter import extract_records, index_generation_id, validate_palace_path


def parse_events(raw: bytes, path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.decode(errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number}: {error}") from error
        if isinstance(item, dict):
            events.append(item)
    return events


def read_events(path: Path) -> list[dict[str, Any]]:
    return parse_events(path.read_bytes(), path)


def safe_source_id(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root).as_posix()
    return hashlib.sha256(relative.encode()).hexdigest()[:20]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def export_sources(
    source_roots: list[Path],
    mappings: dict[str, str],
    output_root: Path,
    generation: str,
    *,
    limit: int | None = None,
    recent_first: bool = False,
    max_export_chars: int = 200_000,
) -> dict[str, int]:
    validate_palace_path(output_root)
    if max_export_chars <= 0:
        raise ValueError("max_export_chars must be positive")
    stats = {"sessions": 0, "records": 0, "export_files": 0, "quarantined": 0, "invalid": 0}
    candidates = [(source_root, path) for source_root in source_roots for path in source_root.rglob("*.jsonl")]
    if recent_first:
        candidates.sort(key=lambda item: item[1].stat().st_mtime, reverse=True)
    else:
        candidates.sort(key=lambda item: (str(item[0]), str(item[1])))
    catalog_path = output_root / "source-catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        catalog = {}
    if not isinstance(catalog, dict):
        catalog = {}
    for source_root, path in candidates:
        if limit is not None and stats["sessions"] >= limit:
            break
        stats["sessions"] += 1
        try:
            raw_source = path.read_bytes()
            events = parse_events(raw_source, path)
        except (OSError, ValueError):
            stats["invalid"] += 1
            continue
        records, quarantined = extract_records(events, mappings)
        if quarantined:
            stats["quarantined"] += 1
        grouped: dict[str, list[Any]] = {}
        for record in records:
            grouped.setdefault(record.scope, []).append(record)
        source_id = safe_source_id(source_root, path)
        source_hash = hashlib.sha256(raw_source).hexdigest()
        catalog[source_id] = str(path.resolve())
        for domain, domain_records in grouped.items():
            domain_root = output_root / domain
            domain_root.mkdir(mode=0o700, exist_ok=True)
            export_dir = domain_root / "export"
            export_dir.mkdir(mode=0o700, exist_ok=True)
            blocks: list[str] = []
            for record in domain_records:
                prefix = f"[{record.role} source_event={record.source_index}]\n"
                payload_limit = max(1, max_export_chars - len(prefix) - 2)
                segments = [record.text[start : start + payload_limit] for start in range(0, len(record.text), payload_limit)] or [""]
                for segment_index, segment in enumerate(segments, 1):
                    segment_prefix = prefix.rstrip("\n")
                    if len(segments) > 1:
                        segment_prefix = segment_prefix[:-1] + f" segment={segment_index}/{len(segments)}]"
                    blocks.append(f"{segment_prefix}\n{segment}\n")

            parts: list[list[str]] = [[]]
            part_chars = 0
            for block in blocks:
                if parts[-1] and part_chars + len(block) > max_export_chars:
                    parts.append([])
                    part_chars = 0
                parts[-1].append(block)
                part_chars += len(block)
            part_count = len(parts)
            written_paths: set[Path] = set()
            for part_index, part_blocks in enumerate(parts, 1):
                lines = [
                    f"source_id: {source_id}",
                    f"source_part: {part_index}/{part_count}",
                    f"source_sha256: {source_hash}",
                    f"index_generation: {generation}",
                    "trust: first-party-conversation",
                    "",
                    *part_blocks,
                ]
                suffix = "" if part_count == 1 else f"-p{part_index:04d}"
                output_path = export_dir / f"{source_id}{suffix}.md"
                atomic_write(output_path, "\n".join(lines))
                written_paths.add(output_path)
                stats["export_files"] += 1
            stale_candidates = {export_dir / f"{source_id}.md", *export_dir.glob(f"{source_id}-p*.md")}
            for stale_path in stale_candidates - written_paths:
                if stale_path.exists():
                    stale_path.unlink()
            stats["records"] += len(domain_records)
    atomic_write(catalog_path, json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--mempalace-version", default="3.9.0")
    parser.add_argument("--backend", default="chroma")
    parser.add_argument("--embedder", default="all-MiniLM-L6-v2")
    parser.add_argument("--dimension", type=int, default=384)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--recent", action="store_true")
    parser.add_argument("--max-export-chars", type=int, default=200_000)
    args = parser.parse_args(argv)
    mapping_path = Path(args.mapping).resolve()
    output_root = Path(args.output_root).resolve()
    if mapping_path.stat().st_mode & 0o077:
        print("mapping file must be owner-only", file=sys.stderr)
        return 2
    mappings = json.loads(mapping_path.read_text())
    generation = index_generation_id(
        args.mempalace_version,
        args.backend,
        args.embedder,
        args.dimension,
        "sanitize-v1",
        "chunk-v1",
    )
    try:
        stats = export_sources(
            [Path(path).resolve() for path in args.source_root],
            mappings,
            output_root,
            generation,
            limit=args.limit,
            recent_first=args.recent,
            max_export_chars=args.max_export_chars,
        )
    except (OSError, ValueError) as error:
        print(f"memory export failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"generation": generation, **stats}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
