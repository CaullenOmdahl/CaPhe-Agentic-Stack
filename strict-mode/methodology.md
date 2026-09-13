# Strict Mode v3 — evidence-preserving efficiency

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

Start with the smallest source-bound context that can decide the next action. The installed runtime's
`tools/stack_context.py` collects bounded Git state; retrieve sanitized historical excerpts only for a
specific unresolved question. Keep full histories canonical and outside this public distribution.

`strict-green-gate.sh --mode affected` is fast feedback. It may use a manifest-proven dependency graph,
parallel commands, and explicitly safe cache entries. It reports `FAST GREEN`, never completion.

`strict-green-gate.sh --mode completion` is the DoD gate. It runs the complete declared matrix uncached.
When authoritative CI provides that evidence, record the CI URL/checks in the per-change evidence record;
absence or incomplete CI falls back to the complete local matrix.

Manifest coverage is fail-closed. Uncovered paths block; unproven dependency completeness escalates local
feedback to full. Cache is default-off and never participates in completion.
Checks cover staged, unstaged, and non-ignored untracked working files. A changed source snapshot during
execution is not green. Commands run in declared order within each component unless `parallel_safe: true`
explicitly declares independence; selected dependent components wait for their prerequisites. Failed
preparation blocks dependent checks. Use explicit timeouts for commands that can stall.
Check and toolchain-probe working directories must resolve inside the repository. Custom dependency
verifiers use `dependency_verification.timeout_seconds` (default 10); timeout leaves the dependency
claim unproven and falls back to full checks.
`--report` writes a private diagnostic outside Git. Candidate-produced reports cannot certify their own
authority; automatic CI evidence reuse remains unavailable without an independently trusted executor.
Run the uncached full local matrix when that independently verified CI evidence is absent.
Generated default manifests assign Python test signals to their nearest declared project. Declared nested
projects run independently and ancestor pytest/unittest commands exclude them before collection,
preventing duplicate imports and execution.
Pytest configuration or dependencies in PEP 621, standardized groups, Poetry tables, or requirements
select `python -m pytest`; otherwise the project uses unittest discovery. Dart, Node, Cargo, and Go roots
remain independently discovered.

## Review

Implementation review is PR-based on the actual diff. Local review prepares design/ADRs or serves as an
explicitly recorded fallback when PR review is genuinely unavailable. Reviewing design is not reviewing
implementation. At most two revise-and-re-review rounds are allowed before human tie-break.

When a defect repeats across entrypoints, inspect sibling implementations for that same defect before
pushing the repair. Bound this search to the defect class and add regressions at the affected boundaries.

The packaged `strict-confer` peers are Claude Code, agy (Gemini-family), and Codex; direct Gemini CLI is
not assumed equivalent. Reviewer models come from an owner-only per-machine configuration: agy requires a
Gemini Pro High tier, Codex a non-lightweight current GPT tier, and Claude Sonnet or Opus. Overrides require
a successful compatibility probe with that same client. Reviewer availability is machine-local and requires
a successful authenticated headless invocation with recorded client version and resolved model. Confer snapshots include
stage-0 regular blobs from the Git index only; they omit unstaged worktree bytes, symlinks, gitlinks,
arbitrary untracked state, and the live source-root environment, and refuse non-Git or unmerged roots.
The peer process also runs behind a fail-closed, default-deny host filesystem boundary with a scrubbed
environment and an ephemeral home containing only non-secret onboarding preferences. Host authentication
files and token caches are never copied; a peer that cannot authenticate without them is unavailable. macOS
masks host data roots and reopens selected runtime paths through `sandbox-exec`; Linux constructs a selective
Bubblewrap namespace with a private PID namespace. If a peer cannot run within that boundary, the review
does not run.

## Artifact verification

Tests do not prove nondeterministic, visual, device, document, or generated output. Inspect the real
artifact. Multi-stage generation is anchor-first: verify the first dependent artifact within its retry cap
before spending on later stages.

## Traceability

Write immutable v2 JSON snapshots under `.agent/evidence/`, bound to the source examined. Record
implementation, validation, review, merge, release, and external acceptance separately. A new state gets
a new ID and explicitly supersedes its predecessor; legacy records remain unbound history. Generate
`.agent/traceability.md`. A declaration is not independent proof of its own claims.

Store task continuation and the user's original scoped authorization in the installed runtime's
`tools/stack_state.py` private store outside all Git worktrees. Preserve next action, subject source,
remaining checks, and source coordinates; do not duplicate raw transcripts or modify canonical memory.
Consult existing authorization before asking again. Deployment approval does not imply merge approval.

## Delegation and preparation

Treat model, effort, service tier, and context size as one route. Keep the incumbent for unqualified task
classes. Probe live capabilities; a catalog label alone does not prove authentication. Use
`tools/stack_route.py` to validate an explicit contract, observed capabilities, and trusted owner policy.
The coordinator retains architecture, ambiguous acceptance, integration, and escalation. Use a fresh
bounded child context for independent extraction or scoped work, with explicit model/effort, allowed
writes, checks, acceptance, output limits, and one repair attempt. Cap ordinary execution at two workers;
do not recursively delegate. Full-history forks inherit their model and effort.

After a failed bounded repair, escalate the task or tighten its acceptance contract. Count that repair,
parent inspection, and all children when evaluating savings. Independent canonical PR review stays on its
approved reviewer route. A cheaper model is not promoted from a successful demonstration alone.

For declared generation recipes, use `tools/stack_prepare.py`: probe toolchain, compare recipe/input/output
identities, and rerun missing or stale preparation before focused checks. Receipts are private freshness
metadata, never completion evidence. Use `tools/stack_watch.py` for bounded read-only JSON status queries;
unchanged polling should not wake a model. Display masking is opt-in and preserves source bindings.

See the installed `docs/efficiency-runtime.md` for commands, schema migration, benchmarks, and rollout.

## Relaxation

`STRICT_MODE=prototype` may relax one affected-mode command and must report that it did so. Completion is
never relaxed. Persistent disable remains interactive and user-only.
