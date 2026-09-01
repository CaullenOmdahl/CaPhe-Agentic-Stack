#!/usr/bin/env python3
"""Sanitize and scope Codex transcript records for a derived MemPalace index (ADR-0002)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterable, NamedTuple


SANITIZER_VERSION = "sanitize-v1"
CHUNKER_VERSION = "chunk-v2"


class IsolationError(ValueError):
    pass


class Chunk(NamedTuple):
    text: str
    start: int
    end: int


class MemoryRecord(NamedTuple):
    text: str
    role: str
    scope: str
    trust: str
    source_index: int


class ResolvedExcerpt(NamedTuple):
    text: str
    framed: str
    source_id: str
    start: int
    end: int
    content_hash: str


class ResolvedEvent(NamedTuple):
    text: str
    framed: str
    source_id: str
    source_event: int
    role: str
    content_hash: str


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)),
    ("GITHUB_TOKEN", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("AUTH_BEARER", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("ASSIGNED_SECRET", re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]{8,}")),
)


def sanitize_text(text: str) -> str:
    sanitized = text
    for label, pattern in SECRET_PATTERNS:
        sanitized = pattern.sub(f"[REDACTED:{label}]", sanitized)
    return sanitized


def sanitize_and_chunk(text: str, *, chunk_chars: int = 4000) -> list[Chunk]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    sanitized = sanitize_text(text)
    return [
        Chunk(sanitized[start : start + chunk_chars], start, min(start + chunk_chars, len(sanitized)))
        for start in range(0, len(sanitized), chunk_chars)
    ] or [Chunk("", 0, 0)]


def _domain_for_cwd(cwd: str | None, mappings: dict[str, str]) -> str | None:
    if not cwd:
        return None
    candidate = Path(cwd).resolve()
    matches: list[tuple[int, str]] = []
    for domain, root_text in mappings.items():
        root = Path(root_text).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        matches.append((len(root.parts), domain))
    if not matches:
        return None
    matches.sort(reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None
    return matches[0][1]


def resolve_scope(user_cwd: str | None, assistant_cwd: str | None, mappings: dict[str, str]) -> str | None:
    user_domain = _domain_for_cwd(user_cwd, mappings)
    assistant_domain = _domain_for_cwd(assistant_cwd, mappings)
    return user_domain if user_domain and user_domain == assistant_domain else None


def _message_text(payload: dict[str, Any]) -> str | None:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"}:
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else None
    return None


def extract_records(events: Iterable[dict[str, Any]], mappings: dict[str, str]) -> tuple[list[MemoryRecord], bool]:
    records: list[MemoryRecord] = []
    quarantined = False
    cwd: str | None = None
    turn_messages: list[tuple[str, str, int]] = []

    def flush_turn() -> None:
        nonlocal quarantined, turn_messages
        if not turn_messages:
            return
        roles = {role for role, _, _ in turn_messages}
        scope = resolve_scope(cwd, cwd, mappings)
        if scope is None or "user" not in roles or "assistant" not in roles:
            quarantined = True
        else:
            for role, text, source_index in turn_messages:
                records.append(MemoryRecord(sanitize_text(text), role, scope, "first-party", source_index))
        turn_messages = []

    for index, event in enumerate(events):
        if event.get("type") == "turn_context":
            flush_turn()
            payload = event.get("payload", {})
            cwd = payload.get("cwd") if isinstance(payload, dict) else None
            continue
        if event.get("type") != "response_item":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        role = payload.get("role")
        text = _message_text(payload)
        if role in {"user", "assistant"} and text is not None:
            turn_messages.append((role, text, index))
    flush_turn()
    return records, quarantined


def resolve_excerpt(
    source: str,
    start: int,
    end: int,
    *,
    source_id: str,
    expected_sha256: str,
) -> ResolvedExcerpt:
    if start < 0 or end < start or end > len(source):
        raise ValueError("invalid source coordinates")
    excerpt = sanitize_text(source[start:end])
    content_hash = hashlib.sha256(source.encode()).hexdigest()
    if content_hash != expected_sha256:
        raise IsolationError("source changed after indexing; refresh before resolving")
    framed = (
        f'<UNTRUSTED_MEMORY_EVIDENCE source_id="{source_id}" start="{start}" end="{end}" '
        f'sha256="{content_hash}">\n{excerpt}\n</UNTRUSTED_MEMORY_EVIDENCE>'
    )
    return ResolvedExcerpt(excerpt, framed, source_id, start, end, content_hash)


def resolve_catalog_event(
    catalog_path: Path,
    *,
    source_id: str,
    source_event: int,
    expected_sha256: str,
    expected_scope: str,
    mappings: dict[str, str],
    index_generation: str,
) -> ResolvedEvent:
    """Resolve one indexed event, failing closed on stale hashes or cross-domain scope."""
    catalog_path = catalog_path.resolve()
    if not catalog_path.is_file() or stat.S_IMODE(catalog_path.stat().st_mode) & 0o077:
        raise IsolationError("source catalog must be an owner-only regular file")
    try:
        catalog = json.loads(catalog_path.read_text())
        source_path = Path(catalog[source_id]).resolve()
        raw = source_path.read_bytes()
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise IsolationError("source catalog entry is unavailable") from error
    content_hash = hashlib.sha256(raw).hexdigest()
    if content_hash != expected_sha256:
        raise IsolationError("source changed after indexing; refresh before resolving")
    events: list[dict[str, Any]] = []
    try:
        for line in raw.decode(errors="replace").splitlines():
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    events.append(item)
    except json.JSONDecodeError as error:
        raise IsolationError("canonical source is not valid JSONL") from error
    records, _ = extract_records(events, mappings)
    matches = [
        record
        for record in records
        if record.source_index == source_event and record.scope == expected_scope
    ]
    if len(matches) != 1:
        raise IsolationError("source event is missing, ambiguous, or outside the requested scope")
    record = matches[0]
    text = sanitize_text(record.text)
    framed = (
        f'<UNTRUSTED_MEMORY_EVIDENCE source_id="{source_id}" source_event="{source_event}" '
        f'role="{record.role}" sha256="{content_hash}" index_generation="{index_generation}">\n'
        f"{text}\n</UNTRUSTED_MEMORY_EVIDENCE>"
    )
    return ResolvedEvent(text, framed, source_id, source_event, record.role, content_hash)


def validate_palace_path(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise IsolationError("palace directory must already exist")
    _validate_outside_git(resolved)
    mode = stat.S_IMODE(resolved.stat().st_mode)
    if mode & 0o077:
        raise IsolationError("palace directory must be owner-only (0700 or stricter)")


def _validate_outside_git(path: Path) -> None:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise IsolationError("palace must live outside every Git working tree")


def audit_owner_only_tree(path: Path) -> list[tuple[str, int]]:
    """Return generated paths whose mode permits group or other access."""
    if path.is_symlink():
        raise IsolationError("palace root must not be a symlink")
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise IsolationError("palace directory must already exist")
    _validate_outside_git(resolved)
    offenders: list[tuple[str, int]] = []
    for candidate in (resolved, *sorted(resolved.rglob("*"))):
        relative = "." if candidate == resolved else candidate.relative_to(resolved).as_posix()
        if candidate.is_symlink():
            offenders.append((relative, stat.S_IMODE(candidate.lstat().st_mode)))
            continue
        mode = stat.S_IMODE(candidate.stat().st_mode)
        expected = 0o700 if candidate.is_dir() else 0o600
        if mode != expected:
            offenders.append((relative, mode))
    return offenders


def harden_owner_only_tree(path: Path) -> None:
    """Repair MemPalace-generated modes after init/mine before any retrieval."""
    if path.is_symlink():
        raise IsolationError("palace root must not be a symlink")
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise IsolationError("palace directory must already exist")
    _validate_outside_git(resolved)
    candidates = (resolved, *resolved.rglob("*"))
    if any(candidate.is_symlink() for candidate in candidates):
        raise IsolationError("palace tree must not contain symlinks")
    for candidate in candidates:
        candidate.chmod(0o700 if candidate.is_dir() else 0o600)


def index_generation_id(
    mempalace_version: str,
    backend: str,
    embedder: str,
    dimension: int,
    sanitizer_version: str,
    chunker_version: str,
) -> str:
    payload = json.dumps(
        {
            "mempalace": mempalace_version,
            "backend": backend,
            "embedder": embedder,
            "dimension": dimension,
            "sanitizer": sanitizer_version,
            "chunker": chunker_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def adoption_passes(baseline: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if not candidate.get("citations_resolved", False):
        return False
    if any(candidate.get(field, 0) != 0 for field in ("secret_canaries", "cross_domain_hits", "injection_failures")):
        return False
    baseline_accuracy = baseline["correct"] / baseline["total"]
    candidate_accuracy = candidate["correct"] / candidate["total"]
    token_reduction = 1 - (candidate["tokens"] / baseline["tokens"])
    recall_gain = candidate["recall_at_5"] - baseline["recall_at_5"]
    return (candidate_accuracy >= baseline_accuracy and token_reduction >= 0.30) or (
        recall_gain >= 0.10 and candidate["tokens"] <= baseline["tokens"]
    )


if __name__ == "__main__":
    raise SystemExit("Use memory/export_codex_memory.py for the pilot CLI")
