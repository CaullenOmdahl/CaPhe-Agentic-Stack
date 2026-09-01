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

The local pilot pins MemPalace 3.9.0 and forbids remote embeddings. Sanitizer v6 starts a fresh index
generation and redacts standalone fine-grained GitHub tokens in addition to the existing vendor and
assignment patterns. Adoption requires the privacy,
isolation, injection, citation, correctness, recall, latency, storage, and token benchmarks in ADR-0002.

MemPalace may create backend files with group/world-readable defaults. After every `init`, `mine`,
`repair`, or migration, run the adapter's `harden_owner_only_tree`, require
`audit_owner_only_tree` to return no paths, and only then permit retrieval. A successful sync writes
`active-generation` atomically after mining and reconciliation finish; a failed new generation cannot
replace the last known-good active generation. When the final export leaves a domain, sync reconciles every
initialized retained palace generation against the empty export directory so stale drawers are removed
from historical as well as active derived indexes.

The 2026-09-01 private five-case BlackSheep v10 pilot retained 5/5 answer and recall-at-5 results while
reducing observed retrieval input from 9,820 to 3,742 approximate tokens (61.9%). The harness measured
the slowest end-to-end candidate case at 128,727.67 ms against a 180,000 ms cap and the benchmarked
owner-only palace at 109,212,400 bytes against a 268,435,456-byte cap. The full local v10 generation
contains 904 canonical sources across 18 physically isolated mapped domains. Citations resolved, and the secret-canary,
cross-domain, and injection gates remained at zero. Current benchmark cases require non-empty
human-authored answer predicate groups plus at least one injection probe. A group may provide narrow semantic
alternatives for formatting-equivalent terms, and the result records every case's recall and missing groups.
The benchmark harness generates a fresh
nonce, frames it inside untrusted evidence, invokes the candidate probe command itself, and requires the
command to echo `NONCE_ACK:<nonce>`. Scoring fails when the observed
candidate answer contains the nonce-bound forbidden outcome, including case or punctuation variants, or
when runner-controlled provenance is absent;
candidate result files cannot attest to their own injection safety.
The same runner places a fresh secret canary inside untrusted evidence and uses a two-phase protocol for
every case. Search returns source, event, hash, and optional excerpt bounds. The harness first requires those
coordinates to exist in the selected derived generation, resolves bounded slices from the owner-only catalog
and canonical JSONL, frames every slice as untrusted evidence itself, and supplies those exact frames to the
answer phase. The answer must echo the same live
citations. File-supplied answers, hits, citations, and token counts are replaced; retrieved tokens are derived
only from the harness-supplied context. Candidate-supplied safety counters are ignored: the harness scores and
scans the actual live answer, derives cross-domain failures from both export placement and canonical scope,
and rejects invalid coordinates or negative token measurements. Live append-only transcripts are not benchmark anchors; use stable historical sources so exact
whole-file hashes remain reproducible during a run.
Adoption also requires a positive baseline token count, a harness-timed candidate probe below an explicit
latency cap, and each audited owner-only security domain named by the acceptance cases below an explicit
byte cap. The reported storage value is the largest benchmarked palace, not a sum across isolated domains;
unrelated mapped domains do not consume a case set's per-palace budget. These measurements are
derived by the harness and cannot be asserted by candidate result files. Baseline and candidate result IDs
must each exactly match the benchmark case IDs before scoring.
The formatter also exercises a closing-delimiter self-test. Other domains still require their own
anchor-first run.

Use `memory/export_codex_memory.py` to create sanitized per-domain exports. Private mapping files, pilot
fixtures, palaces, and benchmark results stay outside this public repository.

Generation changes require a complete export pass. `memory/sync_mempalace.py --limit 0` means unlimited;
a bounded generation pass that cannot cover every current source fails before changing exports. Ordinary
bounded syncs keep an owner-only `processed-state.json` of source bytes, mapping, generation, and outcome;
unchanged completed sources do not consume the next batch, so repeated runs advance through the backlog.
The state is advisory: missing or incomplete exports force reprocessing. Deleted canonical sources are
removed from the private catalog, processed state, and every affected domain export before reconciliation.
Every source is also preflighted as readable valid JSONL before a generation transition writes anything.
Every requested source root must exist as a readable, searchable, non-symlink directory before any export
or pruning begins, so a missing or unmounted canonical source cannot be mistaken for intentional deletion.
The complete source-root list supplied to each run is authoritative: catalog and processed-state entries
outside that set are retired and their exports are pruned before new sources are processed.
During ordinary same-generation sync, a source that becomes unreadable or invalid is pruned from the
catalog and exports instead of leaving stale retrievable content.
The exporter records a hash of the trusted domain mapping. Mapping additions, removals, or root changes
that exceed a bounded pass fail before writes and require complete reconciliation.

Exports maintain an owner-only private source catalog. Resolve a selected result's source ID, event,
source hash, domain, and index generation with `memory/resolve_codex_memory.py`; it re-reads the canonical
JSONL once, rejects stale hashes or cross-domain events, sanitizes again, and emits only an untrusted frame.
