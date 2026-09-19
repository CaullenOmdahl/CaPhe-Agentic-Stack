# Model routing and orchestration design

Status: proposed design, awaiting owner review. Builds on the Strict Mode v3 efficiency runtime
(`tools/stack_route.py`, `tools/benchmark_workflow.py`, `schemas/delegation-contract-v1.json`).
Model and architecture choices remain an OWNERS high-risk gate; this document records the design and
the assumptions that need owner confirmation. It does not activate any route.

## Problem

Today the person running a session chooses the model by hand, and the same model then does the
planning, the work, and the integration. When that model is a frontier tier, the session pays frontier
input prices to ingest every tool result and every worker output, so delegation saves little. When it
is a cheap tier, planning and ambiguity handling suffer.

The repository already has the governance half of a fix: a closed delegation contract, an owner-policy
route resolver with incumbent fallback, and a paired cost/quality benchmark. It lacks the execution
half: nothing classifies work, nothing produces live capability data, no policy file exists, nothing
dispatches a resolved route to an actual agent, and nothing turns agent telemetry into benchmark events.
Because no events exist, no cheaper route can ever gather the evidence the canon requires for promotion.

## Goal

Make the coordinator stay on a mid-tier route, send planning to a frontier route only when the work is
ambiguous or architectural, send bounded scoped work to the cheapest approved route for its class across
Codex, Claude, and Gemini, and record every dispatch so promotion evidence accumulates from real work.

Optimize accepted work per total cost, including planner, coordinator inspection, repairs, and children.
A lower unit price alone is not success.

## Non-goals for the proof of concept

- No local model backend. The registry reserves a slot; no dispatcher backend is built.
- No automatic policy changes. Every promotion, demotion, or replacement is a human decision recorded in
  an ADR. Tools report and recommend only.
- No change to canonical PR review. The reviewer route stays separately approved and independent.
- No new daemon or router service. Existing CLIs and harness sub-agent features are the only backends.
- No statistical claims. The benchmark remains descriptive until the owner declares sample requirements.

## Roles

Roles are stable names. Models are assigned to roles through the registry and can change without
touching the skill or the tools.

| Role | What it does | What it must be good at | Starting assignment |
| --- | --- | --- | --- |
| hypervisor | The always-running coordinator that every result feeds back into. Classifies work, writes contracts, resolves routes, dispatches, inspects bounded results and check outcomes, escalates. Never reads worker transcripts. | Reliable tool use, strict JSON adherence, large context, low input price. Deliberately not the frontier tier. | Terra medium |
| planner | Invoked by the hypervisor only for ambiguous, architectural, or multi-component work. Produces a delegation plan, not prose. | Reasoning depth, decomposition, adversarial synthesis. | Astra high |
| worker | Executes one bounded contract in a fresh context containing the contract, canon pointers, and source pointers. Returns a bounded result. | Depends on task class. | Class route from policy, incumbent when unapproved |
| reviewer | Canonical independent PR review. | Unchanged. | Existing approved reviewer route |

The planner is told explicitly that its output will be consumed as worker contracts by a cheaper
coordinator. A delegation plan is a list of child contracts, each with task class, lane, goal,
acceptance, allowed writes, required checks, and output limits. The hypervisor validates the plan with
the existing contract validator before dispatching anything.

## Task classes and lane ceilings

A task class selects the route. A lane ceiling prevents a risky task from being classified into a cheap
route. The hypervisor proposes the class; a deterministic rule then rejects any class whose ceiling is
below the contract's declared lane, and rejects read-only classes on contracts that declare writes.

| Class | Examples | Lane ceiling | Writes | Candidates to evaluate |
| --- | --- | --- | --- | --- |
| mechanical | moves, renames, permissions, formatting, byte-identical edits | mechanically-proven | yes | Luna low, Claude Haiku |
| lookup-extraction | inventory, structured extraction, documentation lookup | any | no | Luna low or medium, Gemini Flash tier |
| settled-implementation | narrow change with fixed behavior and existing tests | scoped-behavior | yes | Terra medium, Luna high, Claude Sonnet |
| difficult-implementation | scoped but hard, or spanning several files | scoped-behavior | yes | Terra high, Sol medium, Claude Sonnet |
| test-authoring | write tests against a stated contract | scoped-behavior | yes | Terra medium, Claude Sonnet |
| coordination | decompose, integrate, dispatch, validate | full-risk | yes | Terra medium, Astra medium |
| planning-architecture | brainstorm, design, adversarial synthesis | full-risk | no | Astra high, Claude Opus, Gemini Pro tier |
| review | canonical PR review | reserved | no | approved reviewer route only |

Vendor strengths are not hardcoded. Claude, Gemini, and Codex models appear as candidates per class, and
the paired benchmark decides which are promoted. The candidate lists above are hypotheses.

A misclassification into a cheap route is caught by the contract's acceptance checks, one bounded repair,
and escalation back to the hypervisor. A misclassification into an expensive route costs money but not
correctness, and shows up in route review as spend without a matching lane.

## Model registry

The registry is the "rolling database of models". It records what each model is, what it costs, where it
falls, why it was chosen, and its lifecycle state. Routes reference registry IDs, never bare vendor model
strings, so a replacement or deprecation is one registry edit plus one policy edit, both reviewed by PR.

### Two layers

- **Public catalog** in the repository at `registry/models.json`, validated by
  `schemas/model-registry-v1.json`. Contains published information only: vendor, family, tier, published
  rates with date and source URL, context window, supported effort vocabulary, intended roles and
  classes, rationale, lifecycle status and dates, predecessor and successor links, and ADR references.
- **Private overlay** in the owner-only store, produced by the probe tool. Contains what is true on this
  machine: which clients are installed and authenticated, which registry models resolved, which efforts
  and service tiers each client accepted, probe timestamp, and client versions. Never committed.

Route resolution requires a model to be present in both layers with status `active` or `pilot`.
An owner may admit a named low-risk class to a labeled, time-bounded `pilot` before paired benchmark
evidence exists. That admission gathers evidence; it is not a promotion.

### Registry entry fields

| Field | Meaning |
| --- | --- |
| `id` | Stable registry identifier, for example `codex-terra`, `claude-sonnet`, `gemini-pro`. |
| `vendor`, `family`, `client` | Who serves it and which CLI or harness backend dispatches it. `client` is one of `codex`, `claude`, `agy`, `gemini`, `local`. |
| `vendor_model` | The exact string the client accepts. The only place a vendor model string appears. |
| `tier` | One of `frontier`, `strong`, `standard`, `light`, `local`. A coarse position for humans. |
| `roles`, `classes` | Roles it may fill and task classes it may serve as a candidate. |
| `efforts` | Effort vocabulary the vendor documents. The probe records which values actually work. |
| `rates` | Dated, sourced published rates per service tier in the vendor's native unit. Mirrors the benchmark rate card shape. |
| `context_window` | Documented limit. Client limits are probed, not inferred. |
| `status` | `candidate`, `pilot`, `active`, `deprecated`, `retired`. |
| `lifecycle` | `added`, `last_reviewed`, `deprecated_on`, `sunset_on` dates as known. |
| `rationale` | Why it is here and where it falls. A short paragraph, not a benchmark claim. |
| `decision_refs` | ADR or evidence IDs behind the current status. |
| `predecessor`, `successor` | Registry IDs, for replacement tracking. |

### Lifecycle

| Transition | Trigger | Who decides | Effect on routing |
| --- | --- | --- | --- |
| new model released | Anyone adds an entry as `candidate` with rates, tier hypothesis, and rationale by PR | Owner review of the PR | Not routable |
| `candidate` to `pilot` | Owner admits a labeled, time-bounded pilot for named low-risk classes | Owner, recorded in ADR | Routable for those classes only; every dispatch is telemetry |
| `pilot` to `active` | Paired benchmark evidence for the class meets the owner's predeclared tolerance | Owner, recorded in ADR | Routable as promoted |
| any to `deprecated` | Vendor announces sunset | Anyone by PR | Still routable; route review flags every route using it and the sunset date |
| `deprecated` to `retired` | Sunset date passes or vendor removes it | Anyone by PR, or route review flags overdue | Not routable; resolution fails closed to the incumbent; a retired incumbent halts routing and asks the owner |
| replacement | A successor reaches `active` for the same classes | Owner | Policy edit swaps the ID; the predecessor moves toward `deprecated` |

Rates carry a `checked` date. Route review flags any rate older than the owner's staleness window.

## Route resolution

The existing route shape is model, effort, service tier, plus a config label. Add:

- `client`, so the dispatcher knows which backend to use.
- Registry binding: `model` must be a registry ID, and resolution consults the public catalog plus the
  private overlay for status and probed capability.
- Lane ceilings per class in the policy, enforced before route lookup.

Publish the change as route schema version 2. Version 1 routes remain accepted so existing tests and
callers keep working; the dispatcher requires version 2.

The policy file lives at `~/.config/caphe/routing-policy.json`, owner-only. A template with no live
values ships in `strict-mode/templates/`. Policy declares the incumbent worker route, the role
assignments for hypervisor and planner, per-class candidate routes with promotion metadata exactly as
the resolver already expects, and lane ceilings.

## Dispatch

`tools/stack_dispatch.py` takes a validated contract and a resolved version 2 route, and returns a bounded
result plus one benchmark event.

### Backends

| Backend | When | Mechanism |
| --- | --- | --- |
| `cli` | Cross-vendor work, and the default for the proof of concept | Headless invocation of `codex exec`, `claude -p`, `agy --print`, or `gemini -p` with explicit model, effort, sandbox, and tool isolation. Reuses the tested invocations from the second-opinion skill. |
| `native` | Same-vendor work when the running harness exposes sub-agents with explicit model and effort | The skill instructs the hypervisor to use the harness sub-agent feature with the resolved values. The dispatcher still records the event from whatever usage the harness reports. |
| `local` | Reserved | Not implemented. The registry and schema accept `client: local` so a later phase adds a backend without a schema change. |

### Worker prompt

A fresh context, never a fork. It contains the serialized contract, the canon references the contract
names, the source pointers the hypervisor supplies, the output limits, and the required result shape:
changed files or citations, checks run with outcomes, uncertainties, unresolved requirements, and
artifact pointers. No conversation history, no transcript excerpts, no secrets.

### Isolation

Workers with write scopes run in a dedicated worktree, or the hypervisor serializes them; the contract
validator already requires disjoint child write scopes. Read-only classes run with the client's read-only
or plan mode. CLI workers start with no MCP servers unless the contract names one. Sandbox flags per
client are recorded in the dispatcher, not left to client defaults. A remote worker receives only a frozen,
tracked-only source snapshot classified `public` or `sanitized`; unknown, ignored, untracked, credential,
secret-bearing, and transcript inputs fail closed before invocation. A client without freshly observed
authentication and enforceable isolation remains a catalog candidate, not a dispatcher backend.

### Result and telemetry

The dispatcher reads the client's JSON output, extracts the final message and the usage fields, truncates
the message to the contract's output limits and marks truncation, and appends one `request_final` event
to the private telemetry log in the exact schema `benchmark_workflow.py` validates. It fills `task_class`,
`source_digest` from the frozen contract and source pointer snapshot, and `harness_digest` from the
dispatcher version, client version, and contract validator version. Unknown usage stays null. Retries and
repairs get new request IDs with the same task ID. The hypervisor's own root request closes the task.

Each dispatch also freezes its contract and source pointer snapshot into a private corpus directory. That
corpus is the benchmark task set. It grows from real work rather than synthetic tasks.

## Orchestrate skill

`skills/orchestrate/SKILL.md` is the hypervisor procedure. It is agent-agnostic and installed like the
other skills.

1. Read the request. If it is plainly one class and one contract, skip the planner.
2. Otherwise invoke the planner role with the planner prompt and validate the returned delegation plan.
3. For each contract: propose a class, run the lane ceiling check, resolve the route, dispatch.
4. Inspect the bounded result and the check outcomes. Do not rerun the worker's research; do not accept
   an unsupported claim. Missing or ambiguous evidence escalates.
5. On failure: one repair with a tightened contract, then escalate to the hypervisor's own execution or
   to the human when the class is gated.
6. Record. Every dispatch has an event; the root task closes once.
7. Hand the integrated change to the normal PR review route.

The skill also carries the planner prompt, which states that output will be consumed as contracts, and
the result shape workers must return.

## Route review

`skills/route-review/SKILL.md` plus `tools/stack_route_review.py`. Read-only over the private telemetry
log, the private corpus, the public registry, the private overlay, and the policy. Produces a report;
never edits policy or registry.

The report contains, per task class and route: dispatch count, acceptance rate, repair rate, escalation
rate, spend per accepted task where cost-eligible, and the paired incumbent versus candidate deltas from
`benchmark_workflow.py`. It flags: active routes on deprecated or retired models with sunset dates; rates
past the staleness window; registry candidates with no dispatches; classes whose spend does not match
their lane; hypervisor input volume trends, which is the signal the owner originally noticed; and any
model in the overlay that failed its last probe.

Each flag carries a recommended action from a fixed vocabulary: `promote`, `demote`, `replace`,
`retire`, `reprobe`, `refresh-rates`, `collect-more`. The owner acts by PR and ADR. Run it on demand,
when the registry changes, and on the cadence the owner sets.

## Local model phase

Deferred. When local models are evaluated, they run on a separate offload host documented privately,
chosen for quality over speed. The registry gains entries with `client: local` and a private overlay
field for the host route. The dispatcher gains a `local` backend. Rates for local entries record
zero marginal token cost with a hardware note, and the benchmark treats them like any other candidate:
no promotion without paired evidence. Gemini CLI's built-in local Gemma routing is a candidate first
entry because it needs no new runtime. Nothing in the proof of concept blocks this.

## Error handling

- Route unavailable, unsupported, or on a retired model: fail closed to the incumbent; a retired or
  unavailable incumbent halts and reports.
- Class violates lane ceiling: reject before resolution and report the violation.
- Worker times out or returns empty output: failure, not approval. Counts as a repair attempt only if a
  repair is dispatched.
- Output over limits: truncate, mark, and keep the full output in the private log for the hypervisor to
  fetch if acceptance needs it.
- Usage missing: null in the event; cost becomes ineligible, never estimated.
- Policy or registry fails validation: nothing dispatches.

## Testing

Unit tests only, no network, matching the existing suite:

- Registry schema validation, lifecycle transition rules, and dual-layer resolution.
- Route schema version 2 acceptance and version 1 compatibility.
- Lane ceiling enforcement for every class.
- Per-client argv construction with explicit model, effort, sandbox, and isolation flags.
- Usage and final-message extraction from recorded fixture output of each client's JSON format.
- Event emission validated against the benchmark event schema, including truncation and null usage.
- Route review report generation and every flag from synthetic telemetry fixtures.

The proof of concept also needs one live, manually observed run per client, recorded privately, before
the owner approves any pilot. Live runs are evidence for the owner, not test-suite fixtures.

## Phasing

| Phase | Scope | Exit criterion |
| --- | --- | --- |
| 1, proof of concept | Registry schema and catalog seeded with remote-model candidates; probe tool; route schema v2 and registry binding; dispatcher with a capability-gated CLI backend; policy template; orchestrate skill; `docs/model-routing.md`; unit tests | One mechanical and one lookup-extraction task dispatched end to end through each freshly authenticated and isolation-verified client, each producing a valid event, with the hypervisor on Terra medium |
| 2, review loop | Route review tool and skill; intake and deprecation procedure documented; `native` backend guidance; first pilot ADR | First route review report over real telemetry; owner decides first promotion or demotion |
| 3, local | Local backend and offload host overlay | Owner decision after phase 2 evidence |

## Assumptions recorded for owner confirmation

1. Hypervisor and incumbent worker route are Terra medium; planner is Astra high. Both are registry
   assignments and can change without code edits.
2. A labeled, time-bounded pilot admission for `mechanical` and `lookup-extraction` may be approved by ADR
   after a fresh authenticated and isolation-capability probe. It gathers evidence; it is not a promotion.
   Every other class stays on the incumbent.
3. Code, schemas, skills, registry catalog, and docs are public in this repository. Policy, overlay,
   telemetry, and corpus are private in the owner-only store.
4. The proof of concept uses remote models only.
