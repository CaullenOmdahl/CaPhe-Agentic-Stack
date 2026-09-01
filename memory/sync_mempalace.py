#!/usr/bin/env python3
"""Bounded, local-only Codex transcript sync for isolated MemPalace domains."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
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


def sync_domain(domain_root: Path, *, runner: Runner = subprocess.run, max_chunks_per_file: int = 500) -> None:
    """Initialize/mine one physical domain, hardening every generated artifact before use."""
    domain_root = domain_root.resolve()
    export_dir = domain_root / "export"
    if not export_dir.is_dir() or not any(export_dir.glob("*.md")):
        return
    palace = domain_root / "palace"
    palace.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = _private_local_env()
    base = _base_command(palace)
    if not (export_dir / "mempalace.yaml").exists():
        runner(
            [*base, "init", str(export_dir), "--backend", "chroma", "--yes", "--no-llm"],
            input="n\n",
            text=True,
            check=True,
            env=env,
        )
    harden_owner_only_tree(domain_root)
    wing = domain_root.name.rsplit("-", 1)[0]
    runner(
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
        text=True,
        check=True,
        env=env,
    )
    runner(
        [*base, "sync", str(export_dir), "--wing", wing, "--apply"],
        text=True,
        check=True,
        env=env,
    )
    harden_owner_only_tree(domain_root)
    offenders = audit_owner_only_tree(domain_root)
    if offenders:
        raise PermissionError(f"owner-only palace audit failed for {domain_root}: {offenders[:5]}")


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
        limit=args.limit,
        recent_first=True,
        max_export_chars=args.max_export_chars,
    )
    for domain_root in sorted(path for path in output_root.iterdir() if path.is_dir()):
        sync_domain(domain_root, max_chunks_per_file=args.max_chunks_per_file)
    harden_owner_only_tree(output_root)
    print(json.dumps({"generation": generation, **stats}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
