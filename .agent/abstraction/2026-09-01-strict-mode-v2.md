# Abstraction — Strict Mode v2 efficiency

## Goal

Reduce repeated work, wall-clock time, and agent context use without weakening the
observable evidence required to accept a change.

## Surfaces

- Repository initialization and managed instruction routing.
- Work classification and required evidence.
- Local pre-commit verification and full pull-request verification.
- Design and implementation review records.
- Traceability records and generated indexes.

## Actions

- Initialize or refresh strict-mode scaffolding safely and idempotently.
- Classify a change as mechanically proven, scoped behavior, or full risk from deterministic evidence.
- Determine affected components from staged paths and an explicit repository manifest.
- Run affected checks locally and the complete matrix in pull-request CI.
- Run a concrete completion command that verifies authoritative CI evidence or executes the full local
  matrix uncached; a focused pre-commit success is labeled `FAST GREEN`, never completion.
- Record compact per-change evidence and regenerate a navigable index.

## State and data

- The methodology and templates are version-controlled source.
- Installed copies are derived runtime artifacts, never the editing source.
- A repository manifest declares component paths, dependency propagation, and commands.
- Per-change evidence records are canonical; the aggregate traceability document is generated.
- Caching is disabled by default. A repository may opt in per command only when it declares all content,
  environment, configuration, and toolchain identity inputs.
- Local peer review runs from an index-only snapshot behind an OS boundary. Each peer receives an
  ephemeral home containing only the minimum CLI identity/authentication state needed to run.

## Rules

- `intended` A mechanical exemption is allowed only for byte-identical renames, declared documentation
  paths, validated generated output, or source transformed by a declared semantic-equivalence verifier.
  Otherwise the change is scoped behavior; agents cannot self-attest the exemption.
- `intended` Scoped behavior changes require an observable contract or delta abstraction,
  defect-detection evidence, impacted checks, independent PR review, and full CI.
- `intended` Full-risk changes retain full abstraction, ADR, adversarial design review,
  human approval, implementation review, full verification, and artifact checks.
- `intended` Human gates for security, auth, schema, architecture, releases, money, legal,
  production readiness, and irreversible actions are unchanged.
- `intended` A local affected-component gate may never substitute for the full PR matrix. If CI is
  absent, unavailable, unauthenticated, or lacks every declared full command, the completion gate runs
  the complete local matrix uncached.
- `intended` Cached success is valid only for byte-identical declared inputs, commands, selected
  environment values, configuration, and toolchain command output. Cache writes use an atomic rename
  under a per-key lock. CI and completion fallback runs are uncached.
- `intended` Manifest lint blocks on any uncovered tracked path, unknown dependency, duplicate command,
  or cycle. Affected mode is allowed only when dependency completeness is proven by built-in workspace
  extractors (Dart/pub, Node workspaces/package dependencies, Cargo metadata, or Go modules) or a declared
  repository verifier. Otherwise affected mode escalates to the full matrix. Manifest edits force full.
- `intended` Generated manifests inspect each Python test root's nearest project declaration and invoke
  pytest when it is declared. A project with explicit pytest configuration is itself a test root even when
  its configured `testpaths` does not include a directory literally named `tests`. Pytest runs from that
  project root without a hard-coded path so every configured root is honored. A project that declares a
  pytest dependency is also scheduled, including conventional root-level `test_*.py` modules; plain test
  trees retain unittest discovery so default gates do not silently skip authoritative tests.
- `intended` Failure output is preserved and displayed.
- `intended` Initialization fails atomically on malformed markers and deduplicates symlink aliases.
- `intended` Peer review denies host filesystem access by default. It exposes only the staged snapshot,
  the peer's ephemeral run directory, selected operating-system/runtime paths, the exact peer executable,
  and network access needed for the review service. The child environment is rebuilt from an allowlist;
  unrelated repositories, notes, credentials, environment variables, and host temporary files stay hidden.
- `legacy` Re-running all auto-detected stacks at every commit is replaced by explicit impact scope.
- `legacy` A single ever-growing traceability table is replaced by per-change evidence records.

## Edge cases

- No staged paths, deleted components, renamed files, shared dependency changes, malformed manifests,
  unavailable toolchains, cache corruption, interrupted parallel checks, symlinked instruction files,
  unmatched or duplicate managed markers, and repositories without CI.
- Unknown paths, an under-specified component detected by graph lint, or any manifest change
  conservatively triggers the full local matrix.
- A failed or missing independent review remains a failure, not a cached success.
- A reviewer CLI that cannot operate within the bounded runtime fails loudly; broad host access is not a
  compatibility fallback.

## Non-functional targets

- Managed instruction block: at most 180 words.
- Focused local gate: schedules no unrelated component command for a correctly declared manifest.
- Full mode: schedules every declared command exactly once.
- Deterministic plan output suitable for tests and audit.
- `strict-green-gate.sh --mode completion` is the DoD command; it never returns `GREEN` from a scoped run.
- Parallel execution must not interleave or discard per-command logs.
- The implementation remains local-first and requires no hosted service for local checks.

## Triage

| Behaviour | Status | Note |
|---|---|---|
| Three evidence lanes | intended | Preserves acceptance evidence while removing irrelevant ceremony |
| Manifest-driven affected checks | intended | Full PR CI remains authoritative |
| Content-addressed local cache | intended | Per-command opt-in, locked, disabled in CI/fallback |
| Per-change evidence records | intended | Generated aggregate index remains human-readable |
| Human-gated phase for all changes | legacy | Retained only for genuinely gated work or unresolved forks |

## Approval

Caullen Omdahl approved implementation of the discussed efficiency, memory, performance,
and token-reduction plan in chat on 2026-09-01.

## Open questions

None blocking. Repository-specific manifests may be added incrementally; unknown scope fails safe.
