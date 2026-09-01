# Strict Mode v2 — evidence-preserving efficiency

## Prime directive

Ship correct, working, independently reviewed software. Match evidence to risk; do not spend tokens or
time reproducing evidence that cannot change acceptance.

## Evidence lanes

### Mechanically proven

Allowed only when a deterministic check proves one of:

- byte-identical rename;
- declared documentation-only path;
- validated generated output tied to its source;
- source transformation with a declared semantic-equivalence verifier.

Anything uncertain is scoped behavior. An agent cannot self-attest a mechanical exemption.

### Scoped behavior

Capture the observable contract or delta, demonstrate that a test/check detects the old defect, run
affected local checks, put the behavioral diff through independent PR review, and obtain the complete
uncached verification matrix before completion.

### Full risk

Use for architecture/platform choices and named human gates. Write an abstraction, optimize/audit it,
record an ADR with alternatives, obtain adversarial design review, record human acceptance, implement
with defect-detection evidence, verify the real artifact, obtain PR implementation review, and run the
complete matrix.

## Human gates

Stop for explicit approval on security/auth/secrets, domain invariants, schemas and migrations, release
or deploy order, architecture/language/model choices, money/legal/payroll, production-readiness claims,
irreversible actions, or a real unresolved fork. Nothing self-merges past a gate.

## Verification

`strict-green-gate.sh --mode affected` is fast feedback. It may use a manifest-proven dependency graph,
parallel commands, and explicitly safe cache entries. It reports `FAST GREEN`, never completion.

`strict-green-gate.sh --mode completion` is the DoD gate. It runs the complete declared matrix uncached.
When authoritative CI provides that evidence, record the CI URL/checks in the per-change evidence record;
absence or incomplete CI falls back to the complete local matrix.

Manifest coverage is fail-closed. Uncovered paths block; unproven dependency completeness escalates local
feedback to full. Cache is default-off and never participates in completion.

## Review

Implementation review is PR-based on the actual diff. Local review prepares design/ADRs or serves as an
explicitly recorded fallback when PR review is genuinely unavailable. Reviewing design is not reviewing
implementation. At most two revise-and-re-review rounds are allowed before human tie-break.

The packaged `strict-confer` peers are Claude Code, agy (Gemini-family), and Codex; direct Gemini CLI is
not assumed equivalent. Reviewer-model overrides require client verification. Confer snapshots include
tracked regular files and staged regular additions only, as proven by index mode; they omit symlinks,
gitlinks, arbitrary untracked state, and the live source-root environment, and refuse non-Git roots.

## Artifact verification

Tests do not prove nondeterministic, visual, device, document, or generated output. Inspect the real
artifact. Multi-stage generation is anchor-first: verify the first dependent artifact within its retry cap
before spending on later stages.

## Traceability

Write one compact JSON record under `.agent/evidence/` per change. Include decision, evidence lane, tests,
review URL, status, and named approval. Generate `.agent/traceability.md`; do not grow one hand-edited table.

## Relaxation

`STRICT_MODE=prototype` may relax one affected-mode command and must report that it did so. Completion is
never relaxed. Persistent disable remains interactive and user-only.
