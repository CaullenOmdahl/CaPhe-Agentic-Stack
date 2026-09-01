# Local Memory Architecture

The stack uses protected source records plus rebuildable local retrieval indexes.

- **Source:** transcripts and explicit notes remain canonical.
- **Derived drawers:** sanitizer-approved excerpts with stable source coordinates and content hashes.
- **Isolation:** separate owner-only domain roots outside Git worktrees, with an immutable palace for each
  index generation.
- **Scope:** trusted per-turn working-directory metadata mapped to an explicit repository root; ambiguous
  records quarantine rather than guess.
- **Retrieval:** semantic/lexical search selects candidates; exact resolution sanitizes again and frames
  results as untrusted evidence.
- **Lifecycle:** explicit corrections supersede; default search masks invalid facts. Index generation records
  MemPalace, backend, embedder/dimension, sanitizer, and chunker identity.

The local pilot pins MemPalace 3.9.0 and forbids remote embeddings. Adoption requires the privacy,
isolation, injection, citation, correctness, recall, latency, storage, and token benchmarks in ADR-0002.

MemPalace may create backend files with group/world-readable defaults. After every `init`, `mine`,
`repair`, or migration, run the adapter's `harden_owner_only_tree`, require
`audit_owner_only_tree` to return no paths, and only then permit retrieval. A successful sync writes
`active-generation` atomically after mining and reconciliation finish; a failed new generation cannot
replace the last known-good active generation.

The 2026-09-01 private five-case BlackSheep pilot retained 5/5 answer and recall-at-5 results while
reducing observed retrieval input from 9,820 to 6,110 approximate tokens (37.8%). Citations resolved,
and the secret-canary, cross-domain, and injection artifact gates remained at zero. This passes the
ADR's Pareto adoption floor for that domain; other domains still require their own anchor-first run.

Use `memory/export_codex_memory.py` to create sanitized per-domain exports. Private mapping files, pilot
fixtures, palaces, and benchmark results stay outside this public repository.

Exports maintain an owner-only private source catalog. Resolve a selected result's source ID, event,
source hash, domain, and index generation with `memory/resolve_codex_memory.py`; it re-reads the canonical
JSONL once, rejects stale hashes or cross-domain events, sanitizes again, and emits only an untrusted frame.
