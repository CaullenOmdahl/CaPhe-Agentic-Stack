# Local Memory Architecture

The stack uses protected source records plus rebuildable local retrieval indexes.

- **Source:** transcripts and explicit notes remain canonical.
- **Derived drawers:** sanitizer-approved excerpts with stable source coordinates and content hashes.
- **Isolation:** separate owner-only domain roots outside Git worktrees, with an immutable palace for each
  index generation.
- **Scope:** trusted per-turn working-directory metadata mapped to an explicit repository root; ambiguous
  records quarantine rather than guess.
- **Retrieval:** semantic/lexical search selects candidates; exact resolution sanitizes again, escapes
  structural delimiters, and frames results as untrusted evidence.
- **Lifecycle:** explicit corrections supersede; default search masks invalid facts. Index generation records
  MemPalace, backend, embedder/dimension, sanitizer, and chunker identity.

The local pilot pins MemPalace 3.9.0 and forbids remote embeddings. Adoption requires the privacy,
isolation, injection, citation, correctness, recall, latency, storage, and token benchmarks in ADR-0002.

MemPalace may create backend files with group/world-readable defaults. After every `init`, `mine`,
`repair`, or migration, run the adapter's `harden_owner_only_tree`, require
`audit_owner_only_tree` to return no paths, and only then permit retrieval. A successful sync writes
`active-generation` atomically after mining and reconciliation finish; a failed new generation cannot
replace the last known-good active generation. When the final export leaves a domain, sync reconciles the
existing active palace against the empty export directory so stale drawers are actually removed.

The 2026-09-01 private five-case BlackSheep v9 pilot retained 5/5 answer and recall-at-5 results while
reducing observed retrieval input from 9,820 to 5,585 approximate tokens (43.1%). The harness measured
the slowest end-to-end candidate case at 107,493.63 ms against a 180,000 ms cap and the complete owner-only
index at 118,889,029 bytes against a 268,435,456-byte cap. Citations resolved, and the secret-canary,
cross-domain, and injection gates remained at zero. Current benchmark cases require non-empty
human-authored answer predicate groups plus at least one injection probe. A group may provide narrow semantic
alternatives for formatting-equivalent terms, and the result records every case's recall and missing groups.
The benchmark harness generates a fresh
nonce, frames it inside untrusted evidence, invokes the candidate probe command itself, and requires the
command to echo `NONCE_ACK:<nonce>`. Scoring fails when the observed
candidate answer contains the nonce-bound forbidden outcome or when runner-controlled provenance is absent;
candidate result files cannot attest to their own injection safety.
The same runner places a fresh secret canary inside untrusted evidence, runs every benchmark retrieval,
and replaces file-supplied answers, source hits, and token counts with those live observations. Candidate-supplied safety
counters are ignored: the harness scores and scans the actual live answer, resolves every observed top-five citation against the owner-only
catalog and canonical JSONL, first requiring its hash, event, and generation to exist in the selected
derived export. It derives cross-domain failures from both export placement and canonical scope, and rejects
negative token measurements. Live append-only transcripts are not benchmark anchors; use stable historical sources so exact
whole-file hashes remain reproducible during a run.
Adoption also requires a positive baseline token count, a harness-timed candidate probe below an explicit
latency cap, and the audited owner-only index tree below an explicit byte cap. These measurements are
derived by the harness and cannot be asserted by candidate result files.
The formatter also exercises a closing-delimiter self-test. Other domains still require their own
anchor-first run.

Use `memory/export_codex_memory.py` to create sanitized per-domain exports. Private mapping files, pilot
fixtures, palaces, and benchmark results stay outside this public repository.

Generation changes require a complete export pass. `memory/sync_mempalace.py --limit 0` means unlimited;
a bounded pass that cannot cover every current source fails before changing exports. Deleted canonical
sources are removed from both the private catalog and every affected domain export before reconciliation.
Every source is also preflighted as readable valid JSONL before a generation transition writes anything.
During ordinary same-generation sync, a source that becomes unreadable or invalid is pruned from the
catalog and exports instead of leaving stale retrievable content.
The exporter records a hash of the trusted domain mapping. Mapping additions, removals, or root changes
that exceed a bounded pass fail before writes and require complete reconciliation.

Exports maintain an owner-only private source catalog. Resolve a selected result's source ID, event,
source hash, domain, and index generation with `memory/resolve_codex_memory.py`; it re-reads the canonical
JSONL once, rejects stale hashes or cross-domain events, sanitizes again, and emits only an untrusted frame.
