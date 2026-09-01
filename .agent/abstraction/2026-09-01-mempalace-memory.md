# Abstraction — local verbatim memory retrieval

## Goal

Increase durable recall and citation accuracy while reducing prompt and retrieval tokens by indexing
immutable source records and loading only the evidence relevant to the current task.

## Surfaces

- Session and transcript ingestion.
- Scoped recall for user, project, person/client, and topic contexts.
- Startup context, query-time retrieval, and exact-source citation.
- Corrections, supersession, retention, deletion, and secret filtering.
- Offline benchmarks for recall, citation precision, latency, and token volume.

## Actions

- Preserve source conversations verbatim with stable identifiers and timestamps.
- Sanitize and index eligible source records into physically isolated palaces, wings, halls, rooms,
  and drawers; quarantine ambiguous scope rather than guessing.
- Search with semantic, lexical, structured-scope, temporal, and relationship signals.
- Resolve live search results to stable source, event, hash, and excerpt coordinates before answering;
  the harness supplies only the sanitizer-verified canonical slices and independently measures them.
- Mark facts superseded or invalid without silently destroying history.
- Rebuild the derived index from source records.

## State and data

- Source transcripts and explicit user memory notes are authoritative and append-only unless the user
  explicitly requests deletion.
- MemPalace is a pinned, replaceable, local retrieval dependency; it is not the canonical datastore.
  The pilot uses an isolated palace and local embeddings only.
- Every palace lives outside a Git working tree with owner-only permissions; startup refuses an in-tree or
  group/world-accessible index path.
- Wings scope memories by global user, project, person/client, or specialist agent.
- Halls classify decisions, procedures, preferences, incidents, facts, and artifacts.
- Rooms identify topics. Derived drawers contain sanitizer-approved source excerpts plus exact source
  coordinates. Closets are optional summaries that point to drawers and cannot replace source evidence.
- Every derived record retains source path or source identifier, stable record ID, timestamp, scope,
  trust class, content hash, sanitizer/chunker version, MemPalace version, backend, embedding model,
  vector dimension, and index generation.

## Rules

- `intended` Explicit user statements outrank inferred observations.
- `intended` Exact source resolution verifies source ID, coordinates, and content hash, then returns only a
  fresh sanitizer-approved excerpt. Raw secret-bearing spans never enter agent context.
- `intended` Summarization may accelerate navigation but never deletes or replaces verbatim source.
- `intended` Every candidate passes a fail-closed multi-pass secret scan before indexing. Detected
  secrets are replaced by typed placeholders in derived text; source remains in its existing protected
  location. Standalone vendor credentials, including OpenAI project keys, are covered by versioned
  sanitizer patterns. The pilot forbids remote embeddings. Any future remote path is a separate human-gated ADR.
- `intended` Separate physical palace databases enforce each client/project security domain. Federated
  cross-domain retrieval is explicit, user-authorized, and does not weaken per-palace filters.
- `intended` Scope derives only from trusted per-turn working-directory metadata resolved inside an
  explicitly mapped Git root. A user/assistant pair is indexed only when both belong to one security
  domain. Missing, changing, mixed, or unmapped metadata is quarantined without heuristic classification.
- `intended` Deterministic explicit corrections set validity/supersession metadata. Default retrieval
  masks superseded facts; historical queries may request the timeline. An LLM cannot silently invalidate.
- `intended` Retrieved memory is framed as untrusted quoted evidence with source and trust metadata.
  Tool output and fetched third-party content are excluded from startup context and ingestion by default.
- `intended` Benchmark probes are two-phase. Search returns coordinates only; the harness resolves those
  coordinates from the selected generation, frames and supplies the exact slices to the answer phase,
  requires the answer to echo the live citations, and derives token volume from the underlying supplied
  text rather than probe claims. Nonce-bound forbidden outcomes use normalized case and punctuation
  matching so superficial output formatting cannot bypass the injection gate.
- `intended` Indexing is idempotent, resume-safe, incremental, and bounded by per-palace quotas. Large
  tool outputs, binary/base64 content, and generated build logs are excluded by default.
- `intended` A bounded ingestion pass counts only sources whose bytes, generation, mapping, or processing
  state require work. Owner-only derived state lets repeated bounded passes advance through the backlog;
  unchanged, quarantined, and previously invalid sources do not permanently consume the front of every batch.
- `intended` A secret discovered after indexing tombstones the derived drawer and triggers a sanitized
  rebuild. User-authorized source deletion is followed by deletion verification across every retained
  palace generation and complete reindex. Each sync's complete source-root list is authoritative; sources
  under retired roots are removed from derived state. Initialized partial generations without an active
  pointer and orphan export files without catalog/state entries remain part of deletion reconciliation.
  Every retained generation is reconciled after partial deletions even while the domain remains non-empty.
- `intended` Failure of the derived index falls back to existing source/registry lookup.
- `legacy` Loading broad manually maintained summaries into every task is reduced to a small identity
  layer plus scoped query-time retrieval.

## Edge cases

- Duplicate transcripts, edited or compacted sessions, missing source files, renamed projects,
  multilingual text, embedding-model changes, deleted source, stale summaries, concurrent ingestion,
  secrets in transcripts, and conflicting observations across time.
- Embedding model, dimension, sanitizer, or chunker changes require a new index generation rather than
  mixed search. Reindex runs off the interactive path and the last healthy generation stays readable.
- Inaccessible or corrupt drawers must not be cited.
- Missing, unreadable, non-searchable, or symlinked canonical source roots fail before export mutation;
  transient source unavailability must not be interpreted as deletion.
- Transcript files and every path component must resolve beneath the validated source root without a
  symlink; out-of-root transcript aliases fail the export before reconciliation.

## Non-functional targets

- Local-only pilot; no transcript content or embedding request leaves the machine.
- Palace path and permission checks must pass, and a public-repository scan must prove no derived drawer,
  index, mapping, or private fixture is tracked or staged.
- Startup memory context at or below 500 tokens for the normal path.
- On the private acceptance set: 100% citation resolvability, zero secret-canary retrieval, zero
  unauthorized cross-palace retrieval, and all stored-injection probes remain inert. Adoption additionally
  requires a Pareto improvement: equal-or-better answer correctness with at least 30% fewer retrieved
  tokens, or at least 10 percentage points better top-5 source recall without increasing retrieved tokens.
- Correctness is scored against human-authored expected source IDs and observable answer predicates; an
  LLM may assist analysis but cannot be the acceptance oracle. Secret-canary success is a regression
  control, not a claim that novel secret formats are impossible.
- Baseline and candidate result IDs must each match the benchmark case IDs exactly; partial or extra fixtures
  fail before scoring so an incomplete baseline cannot lower the adoption bar.
- Warm query p95 target below two seconds on the primary local machine.
- Storage acceptance applies independently to every benchmarked security domain; the aggregate report uses
  the largest domain rather than summing physically isolated palaces.
- Raw sources and the existing memory system remain untouched during the pilot.

## Triage

| Behaviour | Status | Note |
|---|---|---|
| Verbatim source retention | intended | Existing protected source is canonical; derived text is sanitized |
| MemPalace as derived index | intended | Avoids backend lock-in and preserves recoverability |
| Small startup context | intended | Query-time retrieval supplies task-specific evidence |
| Summary-only canonical memory | legacy | Summaries become navigational closets |
| Automatic destructive forgetting | rejected | Deletion remains explicit and auditable |

## Approval

Caullen Omdahl approved implementation of the discussed efficiency, memory, performance,
and token-reduction plan in chat on 2026-09-01.

## Open questions

None blocking for the isolated, local-only pilot. Automatic write hooks enable only after privacy,
isolation, injection, resource, recall, citation, correctness, latency, and token benchmarks pass.
