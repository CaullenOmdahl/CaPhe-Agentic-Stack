# ADR 0001 — Evidence-preserving Strict Mode v2

- **Status:** accepted
- **Date:** 2026-09-01
- **Approver:** Caullen Omdahl (authorized full implementation in chat, 2026-09-01)
- **Deciders / reviewers:** Codex; v1 rejected by Claude and agy; v2 accepted-with-conditions by Claude
  and rejected by agy; v3 accepted by Claude and agy

## Context

The existing methodology preserves strong evidence but applies broad initialization text, automatic
stack discovery, full local checks, and centralized traceability in ways that duplicate work and omit
some nested components. See the linked Strict Mode v2 abstraction.

## Decision

Adopt three evidence lanes, selected by deterministic evidence: mechanically proven, scoped behavior,
and full risk. Use a declarative component manifest for affected-component local checks and require an
uncached complete matrix in pull-request CI. If CI is absent or incomplete, completion requires the full
uncached local matrix through `strict-green-gate.sh --mode completion`; focused pre-commit success is
labeled `FAST GREEN` and cannot satisfy DoD. Manifest lint blocks uncovered paths, and affected mode is
available only when dependency completeness is proven by built-in workspace extractors or a repository
verifier; otherwise it runs full. Manifest edits force full verification. Caching is disabled by default and requires explicit complete
input/toolchain declarations plus atomic per-key locking. Store evidence per change and generate the
aggregate index. Keep all existing named human gates and PR implementation review.
Generated manifests preserve each Python test root's declared runner: explicit pytest configuration or
dependency, including standardized top-level dependency groups, selects `python -m pytest`, while
undeclared roots retain unittest discovery.

Local `strict-confer` fallback reviews use a default-deny host filesystem boundary, an index-only project
snapshot, an ephemeral shadow home seeded with only minimum peer CLI identity/authentication state, selected
system/runtime paths, and a rebuilt allowlisted environment. Linux uses a selective Bubblewrap namespace;
macOS uses a default-deny Sandbox profile. A peer that cannot run within that boundary is unavailable rather
than silently receiving broader host access.

Implementation remains Bash plus Python 3. Python is selected for safe marker replacement, JSON schema
handling, deterministic planning, hashing, concurrency, and portable tests; Bash remains the stable CLI
and git-hook boundary.

Platform scoring:

| Option | Platform | Performance | Determinism | Portability | Ecosystem | Security |
|---|---:|---:|---:|---:|---:|---:|
| Bash wrapper + Python core | 5 | 4 | 5 | 5 | 5 | 4 |
| Bash only | 5 | 3 | 3 | 3 | 3 | 3 |
| Node core | 4 | 4 | 5 | 3 | 5 | 4 |
| Rust binary | 3 | 5 | 5 | 2 | 4 | 5 |

Python wins because it is already used by strict-confer, is present on supported developer machines,
and avoids adding a compiled distribution artifact. Bash-only loses on reliable JSON, hashing, and
parallel log management. Node is not universal across all governed repositories. Rust adds build and
distribution overhead disproportionate to this control-plane tool.

## Second opinion

V1 was rejected because it lacked a no-CI fallback, permitted self-attested lane selection, could not
detect incomplete dependency declarations, and under-specified cache identity and locking. V2 adds an
uncached full local completion fallback, deterministic exemption proofs, manifest/graph lint with full
fallback, and default-off locked caching. Claude accepted v2 with conditions; agy rejected because the
completion gate was not a concrete command and dependency verification remained optional. V3 makes the
completion mode explicit and permits affected mode only with proven dependency completeness.
Final v3 review accepted the design; evidence:
`.agent/reviews/20260901T090934Z-20260901T090602Z-22514-27682-strict-memory-efficiency-v2-design-v3.md`.
The exact-head Codex review at `97d4166` rejected source-root-only masking because unrelated host data
remained readable. The default-deny selective-runtime revision closes that adversarial finding.
A later exact-head review found that unconditional unittest discovery could skip declared pytest suites;
runner-aware Python discovery closes that coverage gap without changing plain unittest repositories.

## Consequences

Local commits become faster and diagnostics improve. Full CI remains authoritative when complete;
otherwise the uncached local full matrix is authoritative. Repository manifests require maintenance,
so unknown paths, detected missing edges, or manifest edits trigger the full matrix.
The source distribution must add tests for initialization, planning, caching, and evidence generation.
Peer CLI compatibility is now bounded by the explicit runtime/auth allowlist; failures remain loud and do
not weaken the isolation policy.

## Alternatives considered

- Keep the current all-local gate: rejected because it duplicates workspace work and can miss nested stacks.
- Remove local gates: rejected because it delays cheap feedback.
- Trust automatic discovery only: rejected because dependency impact is repository-specific.
