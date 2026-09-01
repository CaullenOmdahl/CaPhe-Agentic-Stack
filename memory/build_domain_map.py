#!/usr/bin/env python3
"""Create a private explicit repository-root to memory-domain map."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


def slug(path: Path) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", path.name.lower()).strip("-") or "project"
    suffix = hashlib.sha256(str(path).encode()).hexdigest()[:8]
    return f"{base}-{suffix}"


def discover(roots: list[Path]) -> dict[str, str]:
    repositories: set[Path] = set()
    for root in roots:
        if (root / ".git").exists():
            repositories.add(root.resolve())
        for marker in root.rglob(".git"):
            if marker.is_dir() or marker.is_file():
                repositories.add(marker.parent.resolve())
    return {slug(path): str(path) for path in sorted(repositories)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(discover([Path(root).resolve() for root in args.root]), indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=output.parent, delete=False) as handle:
        handle.write(payload)
        tmp = Path(handle.name)
    os.chmod(tmp, 0o600)
    os.replace(tmp, output)
    print(f"wrote {len(json.loads(payload))} explicit domains to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
