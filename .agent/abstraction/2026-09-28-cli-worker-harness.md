# CLI worker harness rewrite

## Goal

Control worker model, effort, context, permissions, and usage from a deterministic local harness rather
than relying on Codex's built-in `spawn_agent` routing behavior.

## Observable behavior contract

- The operator starts a parent session with an explicit route, or the existing session invokes the
  harness for a bounded worker task. The parent and each worker are separate processes.
- The harness loads one versioned TOML routing file. It maps a named task category to a client, model,
  effort, context budget, sandbox/permission profile, timeout, and output limit. Unknown categories,
  missing fields, unsupported settings, or unavailable clients fail before any model call.
- Worker launch always passes model and effort as client arguments/configuration. Codex workers set
  `agents.max_depth = 0`; no worker calls the native `spawn_agent` tool.
- A worker receives a bounded task brief with relevant paths, acceptance conditions, and allowed writes;
  it receives no parent transcript or session history. It runs in an isolated worktree or an enforced
  read-only root, never the parent's writeable checkout. It writes its final result to a per-run file, and
  the parent validates the full diff against the allowed-write list before integration.
- The runner constructs a minimal provider-specific environment: Codex workers do not inherit Anthropic,
  Google, or other API-key variables, and third-party workers do not inherit unrelated provider keys.
  Codex uses its existing login without copying the auth file; a short-lived permission profile denies
  reads of the auth and session paths. Doctor exercises the actual local OS sandbox against sentinel files
  without a model call. If the boundary cannot be established, the route is unavailable.
- After exit, the harness correlates the process with client-authored execution records outside the worker
  workspace (for Codex, the CLI thread ID and persisted rollout `turn_context`; for other clients, a
  documented session record or provider receipt). Worker-generated prose is never route evidence. Missing
  or mismatched evidence marks the run unverified and blocks it from cost/quality summaries.
- Per-run records are written for success, timeout, signal, crash, and partial output. They bind category,
  route, requested/effective model and effort, context budget, prompt and source digests, batch/parent/retry
  relationships, output/result paths, exit state, elapsed time, and available usage data. Missing usage stays
  unknown and makes spend ineligible. Aggregated provider usage is supplementary and does not replace
  per-run attribution.
- Doctor is read-only by default. It reports tool versions, route config validity, auth mode/status,
  relevant environment-variable names (never values), and local filesystem-profile enforcement. `--apply`
  creates the reviewed starter config only when it is absent; it never overwrites machine configuration.
  `--probe` runs a live request only for enabled routes and consumes that route's allowance. Doctor never
  logs in or installs a provider CLI.
- Update checks only published, versioned releases whose annotated tag verifies against an independently
  provisioned signing-key fingerprint. It persists an owner-only preview receipt and displays release identity,
  plan digest, and inventory changes. Apply requires the exact tag and reviewed preview digest, recomputes
  the plan, and uses the existing inventory, rollback, and verification.
  Missing releases, unverified tags, dirty source, or failed verification prevent activation.
- Provider/model routes remain disabled until their client, authentication mode, invocation flags,
  effective-route evidence, and cost source are verified on that machine. OpenAI/ChatGPT subscription
  usage and third-party provider billing are shown as separate ledgers.

## Actor, trigger, states, and reversibility

- Actor: developer or coordinating agent.
- Trigger: explicit `harness worker`, `harness doctor`, or `harness update` invocation.
- Run state: planned -> dispatched -> verified or failed/unverified -> accepted/rejected by parent.
- Update state: checked -> planned -> explicitly applied -> verified or rolled back.
- Doctor state: inspected -> optionally planned -> explicitly applied -> rechecked.
- Re-running doctor is safe. Routing changes are reversible by restoring the versioned config. Updates
  are reversible through the install journal. Provider usage already consumed is not reversible.

## Existing patterns to preserve

- Strict Mode's closed schemas, source-bound records, private telemetry and fail-closed route checks.
- `stack_install.py`'s explicit inventory, plan/apply split, rollback journal, exact-byte verification,
  and no-overwrite behavior.
- Canonical PR review and human approval for route policy, provider activation, configuration writes,
  release publication, or spending on live route probes.

## Explicit non-goals

- Do not route third-party model usage through the OpenAI subscription or imply that shell invocation
  changes provider billing.
- Do not auto-select or promote a model from prompt text or unpaired usage totals.
- Do not read, copy, upload, or print API keys, auth files, transcripts, or full parent conversation.
- Do not auto-update from `main`, rewrite arbitrary user configuration, or run login/install commands.
- Do not claim usage savings or quality equivalence without paired accepted-task evidence that includes
  parent, retries, children, and verification.

## Acceptance checks

- Fixture-based route tests prove explicit argv/config per client, depth zero for Codex, and no fallback
  from unsupported or unavailable routes.
- Defect tests reject wrong/missing effective model or effort, parent-history payloads, oversized briefs,
  and usage records with mismatched run identity.
- Doctor fixtures cover absent/present API-key variable names without leaking values, malformed config,
  idempotent plans, backups, and preservation of unrelated config.
- Update fixtures cover no release, untrusted tag, dirty source, preview, successful apply, failed apply,
  rollback, and exact installed inventory.
- A real test worker per enabled route verifies actual model and effort before the route is marked ready;
  no live probe is run without explicit route and spending authorization.
