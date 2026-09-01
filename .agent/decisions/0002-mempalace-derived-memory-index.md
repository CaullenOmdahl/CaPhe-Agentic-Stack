# ADR 0002 — MemPalace as a derived local memory index

- **Status:** accepted
- **Date:** 2026-09-01
- **Approver:** Caullen Omdahl (authorized full implementation in chat, 2026-09-01)
- **Deciders / reviewers:** Codex; v1 rejected by Claude and agy; v2 accepted-with-conditions by Claude
  and rejected by agy; v3 accepted by Claude and agy

## Context

The current memory arrangement preserves transcript files and compact registries but depends heavily on
manual summary routing. Broad summaries consume startup context while exact or vaguely described prior
work can remain hard to retrieve. MemPalace demonstrates local verbatim retrieval, scoped hierarchy,
pluggable backends, and reproducible retrieval benchmarks.

## Decision

Pin upstream MemPalace as an optional local retrieval dependency and build a thin adapter from protected
source transcripts to sanitized scoped drawers. Use separate physical palaces per security domain,
trusted metadata mapping, and quarantine for ambiguous scope. Preserve existing transcripts and explicit
notes as canonical. Treat embeddings, graph relationships, rooms, and summaries as rebuildable derived
indexes. The isolated pilot uses local embeddings only, excludes tool/external output by default, frames
retrieval as untrusted evidence, masks superseded facts, records the full index-generation identity, and
enables automatic ingestion only after privacy, isolation, injection, resource, correctness, citation,
latency, recall, and token benchmarks pass.
Derived palaces must live outside Git working trees with owner-only permissions. Scope is accepted only
from trusted per-turn working-directory metadata mapped to one security domain. Exact-source resolution
returns stable coordinates plus a freshly sanitized excerpt, never raw source text to the agent.
Bounded ingestion persists owner-only derived processing state and counts only sources that require work,
so repeated runs drain a backlog instead of rescanning the newest completed window. Benchmark baseline and
candidate IDs must each exactly match the declared case set before any adoption score is calculated. Live
benchmarks separate search from answering: the harness validates search coordinates against the selected
export generation, resolves bounded canonical event slices, frames the slices itself, supplies and measures
that exact context, and requires the answer phase to echo those same citations. Sanitizer behavior changes
create a new generation; sanitizer v6 explicitly covers standalone fine-grained GitHub tokens.

Platform scoring:

| Option | Platform | Performance | Determinism | Portability | Ecosystem | Security |
|---|---:|---:|---:|---:|---:|---:|
| Upstream MemPalace + adapter | 4 | 5 | 4 | 4 | 5 | 4 |
| Extend Markdown registry only | 5 | 2 | 5 | 5 | 4 | 5 |
| Build custom vector/graph store | 3 | 4 | 3 | 3 | 3 | 3 |
| Hosted memory service | 5 | 4 | 3 | 4 | 5 | 2 |

The upstream adapter wins on demonstrated retrieval, local operation, backend flexibility, and reduced
maintenance. Markdown-only loses on semantic recall. A custom store duplicates mature work. Hosted
memory loses on privacy, availability, and recurring external dependency.

## Second opinion

V1 was rejected for missing secret controls, soft tenant isolation, ambiguous scope, stored prompt
injection, no deterministic redaction/supersession path, incomplete embedder identity, unbounded resource
use, and a break-even acceptance floor. V2 adds fail-closed sanitization, physical isolation, quarantine,
untrusted-evidence framing, deterministic masking/tombstones, complete generation identity, bounded
incremental indexing, local-only embeddings, and a Pareto-improvement adoption gate.
Claude accepted v2 with conditions; agy rejected raw exact-source dereferencing and reliance on metadata
that might not exist. V3 sanitizes every resolved excerpt and quarantines any turn without trusted,
mapped, single-domain working-directory metadata.
Final v3 review accepted the design; evidence:
`.agent/reviews/20260901T090934Z-20260901T090602Z-22514-27682-strict-memory-efficiency-v2-design-v3.md`.
The exact-head Codex review at `97d4166` rejected incomplete baseline acceptance and non-advancing bounded
syncs; exact case coverage and persisted processing state address those adversarial findings. A later review
rejected fixture-retained citations and probe-reported retrieval text; the two-phase, harness-resolved
coordinate protocol makes both citation provenance and token volume independently observable.
The final exact-head review found three remaining acceptance gaps: superficial case/punctuation changes
could evade forbidden-outcome matching, unavailable source roots could be treated as an empty export, and
isolated palace sizes were summed against a per-domain cap. The accepted repair normalizes injection
outcomes, validates every canonical source root before mutation, and measures the largest benchmarked
palace independently.

## Consequences

Memory source remains portable and auditable. Sanitized derived indexes add local disk, isolation,
sanitizer, and embedding-model management. Backend, embedder, sanitizer, or chunker changes create a new
generation off the interactive path. Upstream upgrades remain pinned and reviewed deliberately. Adoption
requires a measured net benefit and no privacy/isolation/injection gate failure.

## Alternatives considered

- Replace the current memory tree with MemPalace storage: rejected because it creates unnecessary lock-in.
- Import all private history immediately: rejected until secret filtering and acceptance metrics pass.
- Use generated summaries as canonical: rejected because lossy compression impairs recovery and audit.
