# ADR 0007 — explicit CLI workers and harness lifecycle

- **Status:** accepted for implementation; independent design and PR review required before activation
- **Date:** 2026-09-28
- **Approver:** Caullen Omdahl
- **Authorization:** The owner stated that the command-line worker architecture makes sense and supplied
  the proposed Codex/Claude invocations, route configuration, effective-model verification, bounded briefs,
  per-category usage tracking, tagged updates, and dry-run environment doctor.
- **Scope:** Replace built-in `spawn_agent` delegation in the shared harness procedure with explicit CLI
  subprocesses; add a versioned route contract, actual-route verification, per-run telemetry, and previewable
  update/doctor lifecycle commands. No release publication, remote-machine install, login, provider activation,
  or live paid route probe is authorized by this ADR.

## Decision

The harness, rather than Codex's built-in multi-agent tool, launches every worker process. Each dispatch
uses an explicit task-category route containing client, model, effort, context budget, permissions, timeout,
and output limits. The harness does not change the current Codex app session's model. Codex worker invocations set
`agents.max_depth=0`, preventing recursive delegation. `harness batch` caps simultaneous worker processes
at the configured `max_workers`.

Workers receive a fresh bounded brief and source pointers, never the parent's full conversation. They run
against a standalone tracked-only snapshot, never the parent's writable checkout. Legacy Codex `read-only`
and `workspace-write` sandbox modes are not accepted as the filesystem boundary: they may permit reads
outside the worker root. The CLI receives a per-run custom profile that makes only the snapshot a workspace
root, disables network access, and grants writes only to declared paths. Codex parser validation is
non-billable; routes remain disabled until a live probe on each host confirms the effective permission
profile and requested model/effort. The parent validates the complete snapshot diff against allowed paths
before integration. The runner passes a minimal environment and a short-lived named profile in the existing
Codex home; it does not copy auth files, and the profile denies access to auth and session paths. If the
effective boundary cannot be confirmed, the run is not accepted.

Worker processes also run inside a Linux user systemd scope with `KillMode=control-group`. This contains
descendants that detach or create a new session and lets the harness stop the entire scope before checking
the snapshot. The harness fails closed when a user systemd manager is unavailable. macOS can run planning
and doctor checks, but worker execution remains disabled until an equivalent OS-managed descendant
containment boundary is implemented and verified there.

Workers write their final result to a per-run file. The harness records requested and effective route metadata
and accepts the run as verified only when it correlates the process with trusted client-authored records
outside the worker workspace (Codex thread ID plus persisted rollout `turn_context`, or a documented
equivalent). Worker-generated prose is never route evidence. A record is written for success, timeout, signal,
crash, or partial output; unknown usage remains unknown and spend-ineligible. Cost and quality accounting
uses per-run telemetry with parent, retry, and child links; `ccusage` or another aggregate report is
supplementary.

Route configuration is deterministic, versioned TOML. Prompts may describe task intent and acceptance, but
they do not select the client/model/effort. Unavailable or unsupported routes fail closed. Third-party
providers require separate authentication, route verification, and cost reporting; OpenAI plan usage is not
treated as payment for those providers.

`harness doctor` checks without side effects by default. An explicit apply mode creates the reviewed
starter config only when absent; it never overwrites an existing file. It reports
credential variable names without reading or printing values and never installs tools or logs in.

`harness update` obtains only a published tagged release whose annotated tag verifies against an
independently provisioned signing-key fingerprint, persists an owner-only preview receipt, and prints
its digest with release identity and planned changes. Apply requires the exact tag and reviewed preview
digest; it recomputes the plan and refuses if the tag, signature, target inventory, or file changes differ.
It reuses the inventory-bound transactional installer, returns its selected verification receipt path,
requires the signed payload to retain an executable `bin/harness` entrypoint, and verifies the installed
artifact. The trust root is not updated by the payload it authorizes. It never tracks `main` implicitly. No release currently exists,
so update operations must report that state rather than silently using a branch or untagged source.

## Alternatives considered

- **Continue native `spawn_agent`:** rejected for dispatch because session logs provided by the owner show
  that accepted model/effort overrides can disagree with effective routing. CLI arguments plus runtime
  metadata provide a separate, inspectable boundary.
- **Keep model selection in prompts:** rejected because it is advisory text and cannot deterministically
  bind a route.
- **Automatically choose the cheapest client:** rejected because availability, authentication, data-egress
  scope, billing, and quality differ by provider and task.
- **Update from latest `main`:** rejected because an unreviewed commit could change prompts, routing, or
  local environment behavior. Use reviewed version tags and explicit apply.
- **Silently rewrite Codex/Claude/provider config:** rejected because existing keys, account modes, and
  user preferences are machine-owned state. Doctor must plan narrowly, preserve unrelated content, and
  require explicit apply.
- **Trust worker-reported route metadata or GitHub tag names alone:** rejected because a worker can
  fabricate its own claims and a mutable/unsigned tag is not a trust boundary. Verify client records outside
  the workspace and require a tag signature anchored outside the updated payload.

## Human-gated details

This ADR accepts the process architecture, not a universal active route table. The versioned public config
will contain only reviewed defaults; provider-specific routes stay disabled until compatibility, effective
route evidence, and cost source are verified. Changing the default parent model, enabling an external
provider, modifying machine-global Codex defaults, publishing a release, or running a paid probe requires
its own explicit approval and evidence.

## Review and verification

Design review must challenge route authenticity, provider-account billing separation, credential handling,
source/context boundaries, subprocess/worktree isolation, and update rollback. Implementation review is the
actual PR diff. Completion requires regression tests, the uncached completion matrix, no secret leakage,
and artifact verification of a real installed runtime. Any unsupported client or unavailable release stays
disabled and is reported as a blocker, not silently substituted.
