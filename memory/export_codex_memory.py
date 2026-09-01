#!/usr/bin/env python3
"""Export sanitized, scoped Codex turns for isolated MemPalace pilot databases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from mempalace_adapter import (
    CHUNKER_VERSION,
    SANITIZER_VERSION,
    IsolationError,
    extract_records,
    index_generation_id,
    validate_palace_path,
)


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
    identity = f"{source_root.resolve()}\0{relative}"
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def _validated_domain_root(output_root: Path, domain: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", domain) or domain in {".", ".."}:
        raise IsolationError(f"unsafe memory domain name: {domain!r}")
    unresolved_domain_root = output_root / domain
    if unresolved_domain_root.is_symlink():
        raise IsolationError(f"memory domain must not be a symlink: {domain!r}")
    domain_root = unresolved_domain_root.resolve()
    try:
        domain_root.relative_to(output_root.resolve())
    except ValueError as error:
        raise IsolationError(f"memory domain escapes output root: {domain!r}") from error
    return domain_root


def _validated_export_dir(domain_root: Path, *, create: bool = False) -> Path:
    export_dir = domain_root / "export"
    if export_dir.is_symlink():
        raise IsolationError(f"memory export directory must not be a symlink: {export_dir}")
    if export_dir.exists() and not export_dir.is_dir():
        raise IsolationError(f"memory export path must be a directory: {export_dir}")
    if create:
        export_dir.mkdir(mode=0o700, exist_ok=True)
    return export_dir


def _remove_source_exports(source_id: str, domain_roots: dict[str, Path]) -> None:
    for domain_root in domain_roots.values():
        export_dir = _validated_export_dir(domain_root)
        for stale_path in {
            export_dir / f"{source_id}.md",
            *export_dir.glob(f"{source_id}-p*.md"),
        }:
            if stale_path.exists():
                stale_path.unlink()


def _exported_source_ids(domain_roots: dict[str, Path]) -> set[str]:
    source_ids: set[str] = set()
    for domain_root in domain_roots.values():
        export_dir = _validated_export_dir(domain_root)
        for export_path in export_dir.glob("*.md"):
            match = re.fullmatch(r"([0-9a-f]{20})(?:-p\d{4})?\.md", export_path.name)
            if match:
                source_ids.add(match.group(1))
    return source_ids


def _source_exports_complete(
    source_id: str,
    domain_roots: dict[str, Path],
    source_hash: str,
    generation: str,
) -> bool:
    found = False
    for domain_root in domain_roots.values():
        export_dir = _validated_export_dir(domain_root)
        paths = sorted(
            {
                export_dir / f"{source_id}.md",
                *export_dir.glob(f"{source_id}-p*.md"),
            }
        )
        paths = [path for path in paths if path.exists()]
        if not paths:
            continue
        found = True
        part_total: int | None = None
        part_indexes: set[int] = set()
        for path in paths:
            if path.is_symlink() or not path.is_file():
                return False
            headers: dict[str, str] = {}
            try:
                header_lines = path.read_text(errors="replace").splitlines()[:6]
            except OSError:
                return False
            for line in header_lines:
                if ": " in line:
                    key, value = line.split(": ", 1)
                    headers[key] = value
            try:
                part_index_text, current_total_text = headers["source_part"].split("/", 1)
                part_index = int(part_index_text)
                current_total = int(current_total_text)
            except (KeyError, TypeError, ValueError):
                return False
            if (
                headers.get("source_id") != source_id
                or headers.get("source_sha256") != source_hash
                or headers.get("index_generation") != generation
                or current_total <= 0
                or not 1 <= part_index <= current_total
                or (part_total is not None and part_total != current_total)
            ):
                return False
            part_total = current_total
            part_indexes.add(part_index)
        if (
            part_total is None
            or len(paths) != part_total
            or part_indexes != set(range(1, part_total + 1))
        ):
            return False
    return found


def _source_has_exports(source_id: str, domain_roots: dict[str, Path]) -> bool:
    for domain_root in domain_roots.values():
        export_dir = _validated_export_dir(domain_root)
        if (export_dir / f"{source_id}.md").exists() or any(
            export_dir.glob(f"{source_id}-p*.md")
        ):
            return True
    return False


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
    for source_root in source_roots:
        if (
            source_root.is_symlink()
            or not source_root.is_dir()
            or not os.access(source_root, os.R_OK | os.X_OK)
        ):
            raise ValueError(f"source root is unavailable: {source_root}")
    source_roots = [source_root.resolve() for source_root in source_roots]
    domain_roots = {domain: _validated_domain_root(output_root, domain) for domain in mappings}
    all_domain_roots = dict(domain_roots)
    for existing in output_root.iterdir():
        if existing.is_dir():
            all_domain_roots.setdefault(existing.name, _validated_domain_root(output_root, existing.name))
    if max_export_chars <= 0:
        raise ValueError("max_export_chars must be positive")
    stats = {"sessions": 0, "records": 0, "export_files": 0, "quarantined": 0, "invalid": 0}
    candidates: list[tuple[Path, Path]] = []
    for source_root in source_roots:
        for path in source_root.rglob("*.jsonl"):
            try:
                resolved_path = path.resolve(strict=True)
            except OSError as error:
                raise ValueError(f"transcript candidate is unavailable: {path}") from error
            if (
                path.is_symlink()
                or resolved_path != path
                or not resolved_path.is_relative_to(source_root)
                or not resolved_path.is_file()
            ):
                raise ValueError(f"transcript candidate escapes source root or is symlinked: {path}")
            candidates.append((source_root, resolved_path))
    current_source_ids = {safe_source_id(source_root, path) for source_root, path in candidates}
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
    processed_state_path = output_root / "processed-state.json"
    try:
        processed_state = (
            json.loads(processed_state_path.read_text())
            if processed_state_path.exists()
            else {}
        )
    except (OSError, json.JSONDecodeError):
        processed_state = {}
    if not isinstance(processed_state, dict):
        processed_state = {}
    existing_generations: set[str] = set()
    has_existing_exports = False
    for domain_root in all_domain_roots.values():
        export_dir = _validated_export_dir(domain_root)
        for export_path in export_dir.glob("*.md"):
            has_existing_exports = True
            for line in export_path.read_text(errors="replace").splitlines()[:8]:
                if line.startswith("index_generation: "):
                    existing_generations.add(line.removeprefix("index_generation: ").strip())
                    break
    existing_generations.update(
        state.get("generation")
        for state in processed_state.values()
        if isinstance(state, dict) and isinstance(state.get("generation"), str)
    )
    mapping_state_path = output_root / "mapping-state"
    mapping_hash = hashlib.sha256(
        json.dumps(mappings, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    try:
        previous_mapping_hash = mapping_state_path.read_text().strip()
    except OSError:
        previous_mapping_hash = ""
    mapping_transition = bool(
        (has_existing_exports or processed_state)
        and (not previous_mapping_hash or previous_mapping_hash != mapping_hash)
    )
    if mapping_transition and limit is not None and len(candidates) > limit:
        raise ValueError("mapping changes require a complete export reconciliation")
    generation_transition = bool(
        existing_generations and existing_generations != {generation}
    )
    if generation_transition and limit is not None and len(candidates) > limit:
        raise ValueError("generation changes require a complete export rebuild; remove or raise --limit")
    if generation_transition:
        for _, path in candidates:
            try:
                parse_events(path.read_bytes(), path)
            except (OSError, ValueError) as error:
                raise ValueError(
                    f"generation rebuild requires every source to be readable and valid: {path}"
                ) from error

    resolved_source_roots = [root.resolve() for root in source_roots]
    stale_source_ids: set[str] = set()
    known_source_paths = dict(catalog)
    for source_id, state in processed_state.items():
        if source_id not in known_source_paths and isinstance(state, dict):
            known_source_paths[source_id] = state.get("source_path")
    for source_id in _exported_source_ids(all_domain_roots):
        known_source_paths.setdefault(source_id, None)
    for source_id, source_path_text in known_source_paths.items():
        try:
            source_path = Path(source_path_text).resolve()
            belongs_to_current_roots = any(
                source_path.is_relative_to(source_root) for source_root in resolved_source_roots
            )
        except (OSError, TypeError):
            belongs_to_current_roots = False
        if not belongs_to_current_roots or source_id not in current_source_ids:
            stale_source_ids.add(source_id)
    for source_id in stale_source_ids:
        _remove_source_exports(source_id, all_domain_roots)
        catalog.pop(source_id, None)
        processed_state.pop(source_id, None)
    for source_root, path in candidates:
        source_id = safe_source_id(source_root, path)
        source_path = str(path.resolve())
        try:
            raw_source = path.read_bytes()
        except OSError:
            if limit is not None and stats["sessions"] >= limit:
                break
            stats["sessions"] += 1
            stats["invalid"] += 1
            _remove_source_exports(source_id, all_domain_roots)
            catalog.pop(source_id, None)
            processed_state.pop(source_id, None)
            continue
        source_hash = hashlib.sha256(raw_source).hexdigest()
        previous_state = processed_state.get(source_id)
        state_is_current = isinstance(previous_state, dict) and all(
            (
                previous_state.get("source_path") == source_path,
                previous_state.get("source_sha256") == source_hash,
                previous_state.get("generation") == generation,
                previous_state.get("mapping_sha256") == mapping_hash,
            )
        )
        if state_is_current:
            status = previous_state.get("status")
            if status == "exported" and _source_exports_complete(
                source_id, all_domain_roots, source_hash, generation
            ):
                continue
            if status in {"empty", "invalid", "quarantined"} and not _source_has_exports(
                source_id, all_domain_roots
            ):
                continue
        if limit is not None and stats["sessions"] >= limit:
            break
        stats["sessions"] += 1
        state = {
            "source_path": source_path,
            "source_sha256": source_hash,
            "generation": generation,
            "mapping_sha256": mapping_hash,
        }
        try:
            events = parse_events(raw_source, path)
        except ValueError:
            stats["invalid"] += 1
            _remove_source_exports(source_id, all_domain_roots)
            catalog.pop(source_id, None)
            processed_state[source_id] = {**state, "status": "invalid"}
            continue
        records, quarantined = extract_records(events, mappings)
        if quarantined:
            stats["quarantined"] += 1
        grouped: dict[str, list[Any]] = {}
        for record in records:
            grouped.setdefault(record.scope, []).append(record)
        catalog[source_id] = source_path
        current_domains = set(grouped)
        for domain, existing_domain_root in all_domain_roots.items():
            if domain in current_domains:
                continue
            existing_export = _validated_export_dir(existing_domain_root)
            stale_candidates = {
                existing_export / f"{source_id}.md",
                *existing_export.glob(f"{source_id}-p*.md"),
            }
            for stale_path in stale_candidates:
                if stale_path.exists():
                    stale_path.unlink()
        for domain, domain_records in grouped.items():
            domain_root = domain_roots[domain]
            domain_root.mkdir(mode=0o700, exist_ok=True)
            export_dir = _validated_export_dir(domain_root, create=True)
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
        processed_state[source_id] = {
            **state,
            "status": (
                "exported"
                if records
                else "quarantined"
                if quarantined
                else "empty"
            ),
        }
    atomic_write(catalog_path, json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    atomic_write(
        processed_state_path,
        json.dumps(processed_state, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(mapping_state_path, mapping_hash + "\n")
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
        SANITIZER_VERSION,
        CHUNKER_VERSION,
    )
    try:
        stats = export_sources(
            [Path(path) for path in args.source_root],
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
