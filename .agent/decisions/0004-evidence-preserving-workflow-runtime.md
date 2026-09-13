# ADR-0004: Evidence-preserving workflow runtime

Status: accepted for implementation and verified local installation; rollout remains evidence-gated.
Approver: Caullen Omdahl, 2026-09-12.
Approval scope: implement the researched efficiency methodology, push the work, and update local and
secondary-machine projects to use it. This does not authorize application releases, unrelated cleanup,
merging pull requests, or weaker verification.

## Decision

Implement the capabilities in `docs/efficiency-improvement-plan.md` as a small Python standard-library
runtime plus the existing strict-mode tools. Use bounded projections and deterministic observation
before model reasoning, immutable public evidence and separate private state, explicit model/effort
resolution, and source-bound preparation/installation reports. Install from reviewed source rather than
requiring runtime repository checkouts.

Retain the legacy Python evidence writer only for closed, bounded, immutable unbound notes. The CLI
and snapshot validator require v2. Legacy notes never acquire source binding or acceptance, and v2
supersession cannot promote them. This preserves the accepted API contract without a retained-test waiver.

Use isolated worker checkouts with bounded ownership and acceptance contracts. Keep independent PR
review and complete checks. Record and resolve design findings before activating the affected capability.

CI command reports are diagnostic unless an independently trusted verification bundle and enforced
execution/result isolation can be authenticated. The candidate-controlled CI workflow, including its
required runner, manifest, and retained test implementations from the exact PR base, does not establish
this receipt contract. Implement explicitly
nonauthoritative reporting without an automatic CI receipt
consumer or certifier; retain uncached local completion. Do not turn missing infrastructure into a claim
that receipt-based certification is implemented or enabled.

Install explicit routing controls with the incumbent as the fallback. Promote only task-class routes
supported by held-out acceptance and attributable usage evidence. Capability probes and parser fixtures
do not demonstrate model quality or whole-task savings. Keep observation masking opt-in and disabled
for unqualified routes. Preserve existing approved implementation-review models.

## Alternatives

- A general orchestration platform adds a second runtime and migration cost; reuse the current clients.
- Wholesale command compression risks hiding failures; prefer exact projections and restoration.
- Always delegating to the cheapest model ignores repair and integration cost; evaluate model and effort
  jointly and let unresolved scope return to the parent.
- Trusting a candidate's CI report permits weakened checks; unsupported evidence cannot certify work.
- Replacing consumer instructions/manifests wholesale risks losing project constraints; update managed
  regions, preserve custom rules, and verify activation per target.

## Verification and rollout

Use defect-detecting tests for bounds, source changes, immutable writes, provenance, privacy, hook paths,
dependency coverage, preparation receipt freshness, model resolution, and incomplete usage. Compare deterministic
collection/preparation behavior on representative fixtures and real repositories. Run both platform
gates and independent PR review before broad installation. Model experiments use frozen held-out cases
and explicitly report inconclusive quality/cost results.

Rollout is one-way from reviewed source to owner-controlled runtime locations and managed project
scaffolding. Store private inventories, before/after hashes, conflicts, and rollback material outside
Git worktrees with owner-only permissions. Preserve unrelated staged/unstaged state and operational files.
Global installation, project activation, and benchmark-based route promotion are distinct states.

## Design review resolutions

An authenticated, tool-disabled Claude Sonnet 4.6 assessment identified the known evidence overwrite,
open-schema, hook-dispatch, dirty-snapshot, and receipt-forgery defects as activation blockers. These
become defect-detecting acceptance cases; a non-empty design assessment is not implementation approval.

- Activation requires resolving Git's effective hook dispatch and invoking an explicit side-effect-free
  managed-hook probe, plus deployed source and managed-region hashes. File presence is insufficient.
- Affected feedback covers the union of staged, unstaged, and non-ignored untracked changes and labels
  the actual working snapshot. It is never described as isolated staged-content certification.
- Evidence uses explicit stable record IDs with immutable canonical content; identical writes are
  idempotent and conflicting IDs fail. A new snapshot uses a new ID and explicit supersession. A
  completed implementation phase cannot hide pending review or external acceptance.
- Candidate reports cannot certify source or runner trust. Diagnostic CI reporting is available;
  automatic CI certification and its forgery-resistance verification remain deferred until a trusted executor exists. Completion continues through
  the full uncached local path when such evidence is unavailable.
- Semantic acceptance applies to product artifacts when a task has display/device behavior. Runtime JSON
  and Markdown outputs have separate parse/format contracts, without invented hardware claims.

The owner has already authorized settling and implementing this methodology. The resolutions preserve
the requested scope and quality bar and require no broader operational permission.
