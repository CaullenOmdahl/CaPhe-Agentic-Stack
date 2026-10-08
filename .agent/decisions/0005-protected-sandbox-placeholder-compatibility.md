# ADR 0005 — Preserve protected sandbox placeholders

- **Status:** accepted design; implementation review and activation pending
- **Date:** 2026-10-08
- **Approver:** Caullen Omdahl
- **Scope:** launcher compatibility only; preserve isolation, configured routes and worker ceiling

## Contract

A Linux worker may leave only its declared source changes and designated result.
Known CLI sandbox scaffolding is prepared before the source baseline. Every prepared
placeholder must remain the same real, empty directory with unchanged permissions.
Existing paths and arbitrary newly created directories never receive this exception.

## Context

Minimal live read-only and scoped-write probes with Codex CLI 0.160.0 returned their
expected artifacts but failed final validation after empty `.aws` directories appeared
under writable roots. Recorded worker commands did not create them. Codex's protocol
source includes `.aws` among protected metadata names alongside `.git`, `.agents` and
`.codex`. A standalone sandbox command did not reproduce creation; this observation
does not imply that every CLI invocation creates a placeholder.

## Decision

Add `.aws` to the existing fixed preparation list. Record mode, device and inode for
each directory created by the launcher. Reject nonempty, replaced, missing, symlinked,
mode-changed or non-directory placeholders after execution. Preserve the ordinary
source allowlist, result validation, network restrictions and process containment.

The owner explicitly approved the scoped launcher compatibility repair. Checks and
independent implementation review precede local activation; fresh live probes must
verify both enabled permission routes before backlog workers resume.

## Alternatives

Ignoring all empty output directories would admit undeclared writes. Bypassing final
validation or broadening worker permissions would weaken isolation. Keeping the old
list leaves compatible worker results unusable. These alternatives are rejected.

## Consequences

Placeholder validation becomes stricter for all four names. Filesystem identity is
checked after execution; it is not a continuous filesystem audit. Existing sandbox
enforcement and write verification remain necessary. No account, model policy,
concurrency, release or deployment authorization changes.

## Adversarial design review

An independent Gemini-family reviewer inspected the preparation, baseline and final
validation paths and reported no actionable design findings. Implementation review
remains separate. Inode/device checks validate final identity; they do not establish
continuous monitoring or replace sandbox enforcement.
