# Verification runtime

The [shared canon](../docs/canon.md) is the sole workflow policy. This document describes optional
runtime procedures; it adds no acceptance gates. Apply the canon's guidance with judgment; avoid automatic planning, review, or evidence ceremony. Preserve explicit project-required checks.

## Relevant checks

`strict-green-gate.sh --mode affected` runs affected checks and reports `FAST GREEN`.
`--mode plan` inspects selection. `--mode completion` (or `full`) explicitly runs the complete declared
matrix uncached. The legacy mode name is retained for CLI compatibility; `GREEN` certifies only that
matrix, not independent review, human approval, defect closure, or release readiness. Full verification
is appropriate for broad installer/policy/runtime changes or a real project requirement. Do not routinely
duplicate authoritative CI locally. Initialization does not add a full-matrix Stop hook.

Manifest coverage remains fail-closed. Uncovered paths block; unproven dependency completeness falls
back to full checks. Checks include staged, unstaged, and non-ignored untracked files. Source mutation
during execution fails verification. Cache is default-off and never used for full verification.
Commands run in declared order unless `parallel_safe: true`; dependencies wait for prerequisites and
failed preparation blocks dependents. Use explicit timeouts. Command and probe working directories
must resolve inside the repository. Nested project discovery avoids ancestor test duplication.
`--report` writes private diagnostics outside Git; reports cannot certify their own authority.

## Actual results and review

Inspect the actual relevant artifact, especially installer output, visual/device/document results, and
nondeterministic generation. For dependent generation, verify the anchor before later stages.
Use [review-workflow.md](../docs/review-workflow.md) for one implementation-review route and scoped
repairs. Extra design review requires a concrete distinct reason under the canon.

The existing `strict-confer` fallback snapshots stage-0 regular Git blobs only, omitting unstaged bytes,
symlinks, gitlinks, and arbitrary untracked state. Stage deliberate inputs and verify the reviewed diff.
It uses a default-deny host filesystem boundary, scrubbed environment, and ephemeral home. Never copy
host authentication files, histories, or token caches. If authentication or isolation fails, the route is
unavailable. Models and provider consent remain explicit. A successful separate review may use the
author’s model family; self-attestation is not review. Diversity needs a concrete distinct reason.

## Optional records and execution helpers

Preserve immutable historical `.agent/evidence/` records. `strict_evidence.py` can record separate
implementation, validation, review, merge, release, and external acceptance phases when a project needs
that record. Do not create evidence-only churn or require traceability regeneration for routine closure.
Keep private continuation/scoped authorization outside Git; do not copy transcripts or private memory.

Context, preparation, status, benchmark, and isolated harness tools remain available when relevant;
see [efficiency-runtime.md](../docs/efficiency-runtime.md). They are not workflow prerequisites. Do not
bootstrap delegation, external memory, or integrations just to implement a change. Preserve the existing
provider, permission, secret, and source-isolation boundaries whenever those tools are selected.

`STRICT_MODE=prototype` can make affected-mode failures advisory with disclosure, but cannot relax
explicit full verification or required checks. Persistent disable remains interactive and user-only.
