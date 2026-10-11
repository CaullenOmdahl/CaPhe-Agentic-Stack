# ADR 0006 — Canonical worker cwd permission projection

- **Status:** accepted design; implementation checks, review and live activation pending
- **Date:** 2026-10-11
- **Approver:** Caullen Omdahl
- **Scope:** security validator compatibility; unchanged grants, routes and two-worker ceiling

## Contract

Preserve exact managed native permission-profile verification. Accept the existing
exact legacy writable-root set, or that set with only the canonical writable
workspace omitted. The new alternative requires strict resolved identity, literal
canonical launcher workspace and effective cwd, and a concrete expected workspace
write entry. Narrow grants do not gain workspace permissions. Missing result roots,
extra roots, altered denies, network/tmp changes and mismatched identities fail.
Existing explicit-root resolved-alias behavior remains unchanged.

## Evidence and decision

Codex 0.160.0 projects cwd write separately from additional legacy writable roots.
Its native managed permission profile remains the executor authority. The previous
validator rejects verified full-workspace worker output solely for cwd omission.
Pinned upstream source and synthetic host-byte enforcement tests establish the
representation difference; they do not attest reproducible binary correspondence
or substitute for fresh isolated-worker acceptance.

The owner explicitly approved the reviewed correction, gated merge and local
installation on 11 October 2026. Rejected historical worker output remains rejected.
Actual-diff owner-selected local review, full uncached completion, rollback inventory
and fresh read-only/scoped-write probes precede resuming delegation. No broader
permission inference, model-policy change, credential export or release authority
is granted. Same-family review is recorded accurately, not as independent review.
