#!/usr/bin/env python3
"""Bounded, local-only Codex transcript sync for isolated MemPalace domains."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Callable, Sequence


MEMORY_DIR = Path(__file__).resolve().parent
if str(MEMORY_DIR) not in sys.path:
    sys.path.insert(0, str(MEMORY_DIR))

from export_codex_memory import export_sources  # noqa: E402
from mempalace_adapter import (  # noqa: E402
    CHUNKER_VERSION,
    SANITIZER_VERSION,
    audit_owner_only_tree,
    harden_owner_only_tree,
    index_generation_id,
    validate_palace_path,
)


MEMPALACE_VERSION = "3.9.0"
EMBEDDER = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
Runner = Callable[..., object]


def _private_local_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MEMPALACE_LLM_API_KEY"):
        env.pop(name, None)
    env["MEMPALACE_EMBEDDING_MODEL"] = "minilm"
    return env


def _base_command(palace: Path) -> list[str]:
    return [
        "uvx",
        "--from",
        f"mempalace=={MEMPALACE_VERSION}",
        "mempalace",
        "--palace",
        str(palace),
    ]


def _write_private_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.chmod(0o600)
    os.replace(temporary, path)


def sync_domain(
    domain_root: Path,
    *,
    generation: str,
    runner: Runner = subprocess.run,
    max_chunks_per_file: int = 500,
) -> None:
    """Initialize/mine one physical domain, hardening every generated artifact before use."""
    domain_root = domain_root.resolve()
    export_dir = domain_root / "export"
    if export_dir.is_symlink():
        raise ValueError("export directory must not be a symlink")
    if not export_dir.is_dir():
        return
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", generation):
        raise ValueError("generation must be a safe path component")
    has_exports = any(export_dir.glob("*.md"))
    selected_generation = generation
    retained_palaces: list[Path] = []
    has_active_pointer = False
    if not has_exports:
        active_pointer = domain_root / "active-generation"
        if active_pointer.is_symlink():
            raise ValueError("active generation pointer must not be a symlink")
        has_active_pointer = active_pointer.is_file()
        if active_pointer.exists() and not has_active_pointer:
            raise ValueError("active generation pointer is invalid")
        palaces_root = domain_root / "palaces"
        if palaces_root.is_symlink():
            raise ValueError("palaces directory is unavailable")
        if not palaces_root.is_dir():
            if has_active_pointer:
                raise ValueError("palaces directory is unavailable")
            return
        for retained in sorted(palaces_root.iterdir()):
            if retained.is_symlink():
                raise ValueError("retained palace must not be a symlink")
            if not retained.is_dir():
                continue
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", retained.name):
                raise ValueError("retained generation is invalid")
            retained_palaces.append(retained)
        if not retained_palaces:
            return
        if has_active_pointer:
            selected_generation = active_pointer.read_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", selected_generation):
                raise ValueError("active generation is invalid")
    palace = domain_root / "palaces" / selected_generation
    if has_exports:
        palace.mkdir(mode=0o700, parents=True, exist_ok=True)
    elif has_active_pointer and (palace.is_symlink() or palace not in retained_palaces):
        raise ValueError("active palace is unavailable")
    harden_owner_only_tree(domain_root)
    env = _private_local_env()
    base = _base_command(palace)
    def run_write(command: list[str], **kwargs: object) -> None:
        try:
            runner(command, text=True, check=True, env=env, **kwargs)
        finally:
            harden_owner_only_tree(domain_root)
            offenders = audit_owner_only_tree(domain_root)
            if offenders:
                raise PermissionError(f"owner-only palace audit failed for {domain_root}: {offenders[:5]}")

    initialized_marker = palace / ".initialized"
    wing = domain_root.name.rsplit("-", 1)[0]
    if not has_exports:
        for retained_palace in retained_palaces:
            if not (retained_palace / ".initialized").is_file():
                raise ValueError("retained palace is not initialized")
            run_write(
                [
                    *_base_command(retained_palace),
                    "sync",
                    str(export_dir),
                    "--wing",
                    wing,
                    "--apply",
                ]
            )
        return
    if not initialized_marker.exists():
        run_write(
            [*base, "init", str(export_dir), "--backend", "chroma", "--yes", "--no-llm"],
            input="n\n",
        )
        _write_private_text(initialized_marker, selected_generation + "\n")
    run_write(
        [
            *base,
            "mine",
            str(export_dir),
            "--backend",
            "chroma",
            "--wing",
            wing,
            "--agent",
            "codex-local-memory",
            "--max-chunks-per-file",
            str(max_chunks_per_file),
        ],
    )
    run_write(
        [*base, "sync", str(export_dir), "--wing", wing, "--apply"],
    )
    _write_private_text(domain_root / "active-generation", selected_generation + "\n")
    harden_owner_only_tree(domain_root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", action="append", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-export-chars", type=int, default=200_000)
    parser.add_argument("--max-chunks-per-file", type=int, default=500)
    args = parser.parse_args(argv)

    output_root = Path(args.output_root).resolve()
    mapping_path = Path(args.mapping).resolve()
    validate_palace_path(output_root)
    harden_owner_only_tree(output_root)
    if stat.S_IMODE(mapping_path.stat().st_mode) & 0o077:
        raise PermissionError("mapping file must be owner-only")
    mappings = json.loads(mapping_path.read_text())
    generation = index_generation_id(
        MEMPALACE_VERSION,
        "chroma",
        EMBEDDER,
        EMBEDDING_DIMENSION,
        SANITIZER_VERSION,
        CHUNKER_VERSION,
    )
    stats = export_sources(
        [Path(path).resolve() for path in args.source_root],
        mappings,
        output_root,
        generation,
        limit=None if args.limit == 0 else args.limit,
        recent_first=True,
        max_export_chars=args.max_export_chars,
    )
    for domain_root in sorted(path for path in output_root.iterdir() if path.is_dir()):
        sync_domain(domain_root, generation=generation, max_chunks_per_file=args.max_chunks_per_file)
    harden_owner_only_tree(output_root)
    print(json.dumps({"generation": generation, **stats}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
