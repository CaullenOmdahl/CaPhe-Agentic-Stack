# Efficiency improvement plan

Status: proposed; research and implementation instructions, not an activated policy.
Research checked: 2026-09-12. Repository baseline: `4e9c057866ec3bf9e3dcd1985d2586cc4ccc341a`.

## Recommendation

Optimize the cost of **accepted work**, including planning, failed attempts, review, and verification.
First reduce repeated discovery and oversized evidence reads. Then make affected checks useful, reuse
authoritative completion evidence, and evaluate model-and-effort routing. Keep independent PR review,
named human gates, and real-artifact verification.

This plan combines inspection of this repository, a private sample of implementation and maintenance
histories, and published research. Only generalized lessons are included here. Private transcripts,
project identifiers, operational measurements, and machine configuration remain outside this repository.
The sample identifies opportunities; it does not establish billed-token savings or universal causality.

No proposed workflow has yet demonstrated end-to-end savings in this stack. Lower token use, lower
credits, lower latency, and unchanged quality are separate claims and must be measured separately.

## What exists and what remains

| Area | Already present | Remaining opportunity |
| --- | --- | --- |
| Governance | Thin adapters, shared canon, risk lanes, named gates | Keep installed versions consistent; avoid contradictory instructions about completion evidence |
| Verification | Affected/completion modes, dependency validation, opt-in feedback caching | This repo's manifest still selects one `**` component; provide proven component manifests and CI receipts |
| Command output | Strict gate prints compact successes and preserves failures | Apply structured, recoverable summaries to discovery, history, review, and diagnostics |
| Review | Active-integration discovery, current-head review, thread-aware findings, bounded waits | Implement deterministic collection and change detection instead of reconstructing this state repeatedly |
| Evidence | Compact JSON records and generated traceability | Add validated provenance and an active-work view; distinguish implemented, verified, approved exception, and released |
| Memory | Scoped, local, rebuildable source-linked retrieval and benchmarks | Measure whole-task effects; excerpt-size estimates are not complete workflow costs |
| Product behavior | Intended-behavior and UX skills; anchor-first artifact verification | Make semantic display contracts and acceptance matrices easier to apply before expensive builds |

Existing implementation anchors:
[gate](../strict-mode/bin/strict_gate.py), [manifest](../.agent/strict-gate.json),
[evidence](../strict-mode/bin/strict_evidence.py), [methodology](../strict-mode/methodology.md),
[branch context](../skills/prepare-branch-context/SKILL.md),
[review loop](../skills/gh-review-certify-loop/SKILL.md), and
[memory benchmark](../memory/benchmark_memory.py).

## Lessons from the history audit

These are generalized patterns from a targeted sample, not findings about every task.

1. **Discovery sometimes repeats work that already exists.** Compact diagnostics and associated
   instructions were already implemented in a sampled project. New work should discover their contract,
   reuse them, and add missing capabilities rather than rebuild another wrapper.
2. **Small history requests can return very large envelopes.** A turn limit or per-item character cap
   does not necessarily cap the number of command, tool, and reasoning records. Project relevant fields
   inside the tool orchestration layer before returning them to the model.
3. **Repeated status polling adds coordination work.** Long build and review tasks repeatedly inspected
   the same logs and described unchanged state. The underlying build wait may be necessary; repeated
   model interpretation is often avoidable.
4. **Fresh worktrees need explicit preparation.** Missing ignored generated sources caused focused-test
   failures even though the full gate knew how to generate them. Make prerequisite preparation reusable
   from the focused path.
5. **Semantic UI errors caused costly late corrections.** Metric labels, units, cohort definitions,
   local-time rules, clipping, and physical output need observable acceptance cases before rebuilding
   every platform. Passing code tests alone did not establish the intended display behavior.
6. **Task states must remain distinct.** Diagnosis is not a performance fix; a proposed helper is not an
   installed helper; a merged exception is not a green completion gate; screenshots do not prove printer
   hardware. Preserve these distinctions through task continuation and final reporting.
7. **Independent checks produced valuable findings.** Review and device inspection caught substantive
   startup, layout, and generated-asset defects. Optimize their inputs and scheduling, not their removal.
8. **Large cross-repository changes accumulate coordination cost.** Attribute work by its actual target,
   not merely the task's working directory. Separate rollout units and evidence so framework work does
   not become indistinguishable from product implementation.

## Published evidence and its limits

Results below retain the original denominator. They are evidence for experiments, not promised savings.

| Technique and primary source | Published result | Quality and transfer limit | Use here |
| --- | --- | --- | --- |
| Focused, curated skills — [SkillsBench v4, June 2026](https://arxiv.org/html/2602.12670v4), [repo](https://github.com/benchflow-ai/skillsbench) | Across 87 tasks and 18 model/harness configurations, GPT-5.5/Codex pass rate rose from 46.8% to 66.5%; mean token use was essentially unchanged | Task-dependent; some tasks worsened. Self-generated skills performed worse than the no-skill baseline for that configuration | Preserve tested procedural skills; evaluate additions on held-out tasks |
| Programmatic tool calling — [Anthropic, November 2025](https://www.anthropic.com/engineering/advanced-tool-use) | Vendor research reports average tokens of 43,588 versus 27,297, a 37% reduction | Vendor-specific setup; separately reported accuracy gains do not prove identical quality for every token-saving comparison | Filter and aggregate tool results in code using existing orchestration |
| Searchable tool schemas — [Cloudflare, February 2026](https://blog.cloudflare.com/code-mode-mcp/), [repo](https://github.com/cloudflare/mcp) | Roughly 1,000 schema tokens for two tools versus 1.17 million for the equivalent complete API surface | Static schema footprint, not task tokens, latency, or solve rate | Discover only relevant tools; avoid adding a duplicate tool-execution platform |
| Recoverable observation masking — [JetBrains study v3](https://arxiv.org/html/2508.21433v3), [engineering blog](https://blog.jetbrains.com/research/2025/12/efficient-context-management/), [repo](https://github.com/JetBrains-Research/the-complexity-trap) | On 500 SWE-bench Verified instances, Qwen3-Coder-480B changed from 53.4%/$1.29 to 54.8%/$0.61 solved/modelled cost per instance | A thinking Gemini configuration fell from 40.4% to 36.4% solved with masking. Compression can harm reasoning models | Conditional experiment; keep raw evidence recoverable and preserve current failures |
| Harness and effort allocation — [LangChain, February 2026](https://www.langchain.com/blog/improving-deep-agents-with-harness-engineering), [repo](https://github.com/langchain-ai/deepagents) | GPT-5.2-Codex on an 89-task Terminal-Bench 2.0 setup improved from 52.8% to 66.5% through harness changes; always-xhigh scored 53.9%, versus 63.6% at high | Several changes interact; timeout-sensitive results are not a universal effort ranking or isolated cost proof | Compare phase-specific effort under the same time budget |
| Repository instructions — [AGENTS study v2, June 2026](https://arxiv.org/html/2602.11988v2) | Generated context increased cost about 20–23% in the studied settings; success differences were not statistically significant | Different models/repos; instruction length alone was not established as the cause | Remove redundant or irrelevant context only after checking behavior coverage |
| Repository instructions — [independent study v2](https://arxiv.org/html/2601.20404v2) | On 124 small PR tasks using GPT-5.2-Codex, median runtime fell 28.64% and output tokens 16.58% | Correctness was not a primary measured outcome; median total tokens increased 1.29% despite lower mean totals | Instruction files can help; there is no evidence for deleting them wholesale |
| Stable cacheable context — [Manus engineering](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) and [OpenAI caching docs](https://developers.openai.com/api/docs/guides/prompt-caching) | Production guidance supports stable prefixes and cache-aware request construction | Cached tokens still count as logical input; cost/latency benefits depend on actual hits and provider billing | Keep canonical prefixes stable where the client permits; measure cache usage |

Treat additional repositories as ideas to test. [RTK](https://github.com/rtk-ai/rtk) reports shell-output
compression, not a complete matched quality benchmark; a [reported test-summary issue](https://github.com/rtk-ai/rtk/issues/3935)
illustrates why exit codes and collection failures must survive filtering.
[context-mode's benchmark](https://github.com/mksglu/context-mode/blob/main/BENCHMARK.md) uses prepared
tool-output fixtures, not an end-to-end agent quality comparison. Check its license before incorporating
code. Neither project should become an unconditional interception layer on this evidence alone.

Do not adopt terse reasoning as a blanket optimization: [Chain of Draft](https://arxiv.org/html/2502.18600v1)
reduced GPT-4o GSM8K output from 205.1 to 43.9 tokens but also reduced accuracy from 95.4% to 91.1%.
Likewise, [ACE](https://arxiv.org/html/2510.04618v3) reports adaptation-stage savings alongside increased
evaluation input in a comparison; adaptation cost is not total workflow cost.

## Astra, delegation, and reasoning effort

Select a **model × effort × task type × risk** combination. Effort labels are not equivalent quantities
across models. More effort can reduce retries on difficult work, or increase latency without improving
acceptance on straightforward work. Astra may be cheaper for a hard task if it avoids coordination and
repair, despite its higher unit price.

The following are starting hypotheses for evaluation, not approved global defaults:

| Work | Initial candidate | Escalation/acceptance rule |
| --- | --- | --- |
| Exact lookup, inventory, structured extraction | Luna low; medium when several sources must agree | Require source pointers and schema validation; unresolved ambiguity returns to the parent |
| Narrow implementation with settled behavior | Terra medium | Focused defect-detection checks and bounded write ownership; compare with Luna high |
| Difficult scoped implementation | Terra high or Sol medium | Choose one based on measured results; do not march through every model tier |
| Task decomposition, integration, ambiguity | Astra medium | Raise to high when evidence exposes unresolved complexity |
| Architecture, difficult debugging, adversarial synthesis | Astra high; xhigh only when justified by evaluation | Preserve named approval and independent implementation review |
| Canonical PR review | Existing approved reviewer route | Worker routing does not downgrade reviewers or make parent review independent |

Current [Codex pricing](https://learn.chatgpt.com/docs/pricing), checked 2026-09-12, gives these standard
credits per million tokens. Rates are a dated input to the experiment, not a quote for a completed task.
Sol's listed rate is promotional at least through 2026-11-21; some enterprise agreements use other rates.

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| GPT-6 Astra | 250 | 25 | 1,250 |
| GPT-5.6 Sol | 100 | 10 | 500 |
| GPT-5.6 Terra | 50 | 5 | 300 |
| GPT-5.6 Luna | 5 | 0.5 | 30 |

Standard and fast service must be measured separately. Do not substitute API dollar prices for Codex
credits. The [Astra API model page](https://developers.openai.com/api/docs/models/gpt-6-astra) documents
different pricing and long-context conditions; client context limits and supported effort values must
also be capability-probed rather than inferred from the API maximum.

[Codex subagent documentation](https://learn.chatgpt.com/docs/agent-configuration/subagents) supports
explicit model/effort defaults and custom agents. Omitting both normally inherits the parent; custom
agent configuration can affect resolution. In the current collaboration tool, full-history forks inherit
the parent and do not accept model overrides. A cheaper worker therefore needs explicit model and effort
with a fresh or bounded context, plus the applicable canon and scoped source pointers.

Start with at most two concurrent workers and no nested delegation in the pilot. Shared-directory
agents do not automatically have isolated write permissions. Use separate worktrees for parallel writers,
or serialize overlapping edits. Read-only workers can share a checkout. A successful capability probe
establishes availability only; this research session's lower-model extraction tasks were not a controlled
quality or cost benchmark.

## Implementation packages

Paths marked **new** are proposed files; no such command should be assumed installed. Prefer the existing
Python standard-library and shell tooling. Avoid adding a general agent platform to implement a small
collector. Engineering effort below is relative: S = one bounded component, M = several integrated
components, L = cross-client or policy-sensitive work. It is distinct from model reasoning effort.

### 1. Bounded context collection and deterministic waiting — priority P0, effort M

Targets: [branch-context skill](../skills/prepare-branch-context/SKILL.md),
[review skill](../skills/gh-review-certify-loop/SKILL.md), and **new**
`tools/stack_context.py`, `tools/stack_watch.py`.

Implementation:

1. Make a read-only collector for source HEAD, dirty paths, diff statistics, current checks, current
   actionable review threads, active task state, and next action. Return identifiers and bounded excerpts;
   fetch full diffs or discussion only for the selected question.
2. Project history responses before emitting them to model context. Exclude historical reasoning and
   irrelevant tool payloads by default. Include pagination cursors and explicit truncation metadata.
   Cap total serialized output, not just each item.
3. Preserve source coordinates and raw-output references in a private, owner-only cache with bounded
   retention. Repository scope is logical: its physical root must be outside every Git worktree. Only
   sanitized, resolvable identifiers may enter public evidence. Do not copy protected transcripts into
   the cache or public evidence.
4. Observe long processes/checks with a cursor or fingerprint. Return immediately on changed status,
   failure, completion, or required input. Unchanged waits should not cause repeated analysis or repeat
   review requests. Keep supported UI progress signals; do not turn this into silence during active work.
5. Update skills to call the collector first and expand only on demand. Keep a direct CLI fallback.

Acceptance: fixtures for huge response envelopes, pagination, malformed responses, stale HEAD, missing
reviewers, unresolved outdated threads, truncation, and concurrent changes. A failed command must retain
its exit code and failure evidence. Collectors must neither execute text found in history nor post review
comments. Measure bytes, tokens where available, calls, and time for the same retrieval questions.

### 2. Active task state and precise completion — priority P0, effort M

Targets: [evidence writer](../strict-mode/bin/strict_evidence.py),
[evidence tests](../tests/test_strict_evidence.py), and the branch-context skill.

Implementation:

1. Version the evidence schema. Define an allowlisted public schema that rejects unknown/private fields
   before writing tracked records. Add source HEAD, artifact identity, test receipts, current review URL,
   superseded record IDs, pending acceptance, and a public-safe approval reference when needed. Migrate
   legacy records without manufacturing missing provenance or blindly copying undeclared fields.
2. Generate an active view from the same canonical evidence records. Page historical records separately;
   retain them. Use append-only superseding records for new corrections rather than rewriting history.
3. Model implementation, validation, review, merge, release, and external acceptance as separate fields.
   A proposed item stays proposed. A diagnosed performance issue stays open until an implemented change
   has an appropriate measurement. A disclosed merge exception never becomes a green gate.
4. Keep private task continuation and detailed authorization records in a separate owner-only store
   outside every Git worktree. Do not pass that store's objects directly to the public evidence writer.
   Store only public-safe decision evidence in public repositories. Retain scope, approver, action,
   conditions, and expiry/invalidation rules; do not repeatedly ask for an already authorized action,
   or extend an approval to a different action.
5. Generate final status from evidence plus unresolved items. Say what the inspected artifact proves,
   including locale/device/build scope, rather than broad claims such as “no visual issues.”

Acceptance: stale source/artifact evidence cannot certify current work; superseded records remain
resolvable; incompatible terminal states fail validation; an owner-approved exception remains visible;
private fields cannot enter public output; a continuation preserves pending hardware acceptance.

### 3. Environment and generated-source preflight — priority P0, effort S–M

Targets: [installation guide](install-for-agents.md),
[strict initializer](../strict-mode/bin/strict-init.sh), and **new** `tools/stack_doctor.py`.

Implementation:

1. Read installed versions, canonical-source hashes, available tool capabilities, duplicate skill names,
   and effective model/effort resolution. Report drift; do not automatically rewrite configuration.
2. Add a repository-defined preparation contract for focused checks: locked dependencies, generator
   inputs, required generated outputs, and tool versions. Reuse existing generation commands rather than
   inventing a second full build. Verify prerequisites before classifying a test failure as a code defect.
3. Key preparation freshness to all declared inputs, toolchain, lockfiles, and relevant environment
   identities. Missing or uncertain evidence reruns preparation. Generated artifacts never stand in for
   completion tests.
4. Offload heavy execution through the machine's existing private workflow. Verify source snapshot,
   dirty-state handling, platform, dependencies, and returned artifact hashes. Private host details stay
   outside distributed files. Preserve ignored operational files with their project.

Acceptance: clean-worktree, stale generator, lockfile change, missing tool, unsupported effort, duplicate
skill, offline host, and platform mismatch cases. Existing helpers report “already available”; no silent
installs, private configuration copying, generated-source commits, or unrelated cleanup.

### 4. Useful affected checks and authoritative completion receipts — priority P1, effort L

Targets: [gate](../strict-mode/bin/strict_gate.py), [gate tests](../tests/test_strict_gate.py),
[manifest](../.agent/strict-gate.json), [quality workflow](../.github/workflows/quality.yml),
[methodology](../strict-mode/methodology.md), and [strict-mode skill](../skills/strict-mode/SKILL.md).

Implementation:

1. Reuse the gate's existing dependency and cache machinery. Add reviewed component manifests for
   consumers whose dependency completeness can be proven. Unknown coverage blocks or selects the full
   matrix according to existing fail-closed rules. Shared config and manifest changes select all.
2. Make hooks explicitly run affected feedback. Suppress duplicate same-state feedback only with a
   matching snapshot, manifest, command, environment, and toolchain identity. HEAD alone is insufficient
   for a dirty working tree. Preserve exit status and label feedback as non-authoritative.
3. Define a versioned completion-receipt schema and producer in the quality workflow. Generate a receipt
   from the exact executed manifest: every command/result, tested source revision, workflow/manifest
   digests, run/job IDs, toolchain/platform scope, and artifact digest. Upload it as a retained CI artifact;
   specify expiry and resolve it through authenticated provider APIs. Check conclusions alone are not
   a receipt. A missing/expired artifact is unavailable evidence.
4. Add a receipt validator to existing evidence tooling. Bind the artifact/digest to the trusted
   repository and run using provider metadata or attestations. Authenticate both the workflow and an
   independently approved verification bundle from a protected base or trusted policy artifact. Bind
   the manifest, executable check implementations, receipt producer/validator, their transitive runner
   dependencies, and check-selection configuration into that bundle. A trusted command name with a
   weakened candidate script is insufficient. Execute protected-base check implementations against the
   candidate checkout, or separately approve the changed bundle before certification. Candidate code
   must not overwrite the trusted runner, producer, or result store; collect authoritative results across
   an enforced isolation boundary. If that integrity or dependency closure cannot be established, this
   receipt route is unavailable. Neither PR changes nor local fallback can approve their own verification
   policy. Validate revision/merge-base semantics, every trusted required command, successful conclusions,
   environment scope, and check URLs. Reject untrusted/partial receipts.
5. Align canon, methodology, installed skill, and CLI messaging: completion requires every declared
   command covered by either validated authoritative CI evidence or a full uncached local run. Keep
   the existing local completion command exhaustive; put receipt selection in the evidence/orchestration
   layer. Absent/incomplete receipts fall back to that local command with the approved matrix. A policy
   trust failure cannot be repaired by rerunning the same unapproved PR manifest locally; use the trusted
   requirements or await the policy decision. This is an evidence route, not a completion cache. Never
   turn a receipt into permission to merge.
6. Preserve baseline failures as explicit findings with reproduction and ownership. Do not globally
   ignore them or treat disclosure as acceptance. Follow the named exception process where applicable.

Acceptance: a real producer/validator round trip covers the complete matrix; local completion still runs
all commands uncached. Selective plans detect shared-package regressions and unknown paths. Stale,
partial, skipped, cancelled, fork-origin, altered-workflow, altered-manifest, expired, tampered, and
different-platform CI receipts cannot certify completion. Specifically test command removal/weakening
in a PR manifest, mutated check scripts and imported helpers, altered runner configuration, a compromised
receipt producer, and candidate writes to the result store. Include attempts to regain trust through a
local fallback using the same unapproved inputs. Add canon/CLI consistency checks to prevent contradictory
installation output. Compare equal source states before calling two runs redundant.

### 5. Bounded delegation with model-and-effort routing — priority P1, effort M–L

Targets: [Codex adapter](../adapters/codex/CODEX.md), installation guide, and **new**
`docs/model-routing.md` plus a small delegation-contract schema under `schemas/`.

Implementation:

1. Obtain the model/architecture decision required by [OWNERS](../.agent/OWNERS.md). Record the experiment
   and fallback in an ADR before activating new defaults. Keep capability data machine-local.
2. Define each worker contract: task ID, source revision, goal, acceptance cases, applicable canon/risk
   lane, source pointers, allowed writes/exclusions, required checks, output schema, budget, and escalation.
3. Return a concise result: changed files or source citations, checks with outcomes, uncertainties,
   unresolved requirements, and artifact pointers. Do not relay the entire transcript to the parent.
4. Start from the routing table above. Use explicit model and effort; verify resolved values. Reject
   unsupported combinations. Keep the existing approved reviewer configuration independent of workers.
5. Allow one bounded repair attempt for a failed delegated result in the pilot, then return the evidence
   to Astra to reassess scope or solve directly. This is a delegation budget, not permission to suppress
   failing tests or declare incomplete work successful. Avoid an automatic ladder through every tier.
6. Parent validation should inspect the diff/claim and relevant acceptance evidence. Re-running the
   worker's entire research from scratch defeats delegation; trusting unsupported summaries defeats
   quality. Escalate when source evidence is missing or ambiguous.

Acceptance: explicit model/effort survives client defaults; inherited-context cost is accounted for;
workers respect write boundaries; failed results escalate; canonical approval and review remain intact.
Pilot lookup, extraction, and settled implementation separately. Use this staged evaluation matrix;
every row includes the unchanged incumbent model/effort as control:

| Task class | Candidates to evaluate before promotion |
| --- | --- |
| Lookup/extraction | Luna low, Luna medium, Astra low/medium |
| Settled implementation | Luna high, Terra medium, Astra low/medium |
| Difficult scoped implementation | Terra high, Sol medium, Astra medium/high |
| Coordination and ambiguous integration | Astra medium, Astra high |
| Architecture/adversarial synthesis | Astra high, Astra xhigh |

Do not run every combination on every task. Start with the first two classes, then expand only when
observability and quality support it. A candidate absent from completed evaluations remains unapproved
for promotion; the table above is not evidence that all routes work equally well.

### 6. Semantic acceptance before expensive artifact generation — priority P1, effort S

Targets: [intended-behavior skill](../skills/intended-behavior/SKILL.md),
[UX skill](../skills/ux-flow-plan/SKILL.md), and existing artifact-verification guidance.

Implementation:

1. Add a compact display contract where relevant: actor, source of truth, label, unit, numerator and
   denominator, included/excluded records, timezone, empty/error states, and terminology ownership.
2. Record representative locale, text scale, viewport/device, and hardware acceptance cases. Distinguish
   app-authored copy from upstream/source content before localization.
3. Inspect the first representative artifact before generating every dependent platform or variant.
   Batch independent corrections against that contract, then run appropriate checks on the final change.
4. Reuse prior visual evidence only when its build/artifact and relevant acceptance scope still match.
   Physical hardware requirements remain pending until actually tested.

Acceptance: fixtures catch a plausible-looking but wrong metric label, a timezone mismatch, clipping,
and an inappropriate translation. Do not add ceremonial UX paperwork to a trivial nonvisual change.

### 7. Conditional context compression and instruction maintenance — priority P2, effort M

Targets: branch-context and recall skills, installation guide, doctor, and benchmark tooling.

Implementation:

1. Prefer exact projections and retrieval before lossy summarization. Older successful tool observations
   may be replaced with source pointers only in a benchmarked adapter; retain recent evidence, unresolved
   failures, decisions, changed files, and acceptance constraints. Restore raw evidence on demand.
2. Keep stable canonical instructions and deterministic serialization where the host permits. Put
   volatile task state after the stable prefix. Do not delete safety rules to increase cache hits.
3. Detect duplicate installed skills and differing copies. Consolidate only after checking client search
   precedence and compatibility requirements. Keep small adapters and focused, tested procedures; do not
   adopt an arbitrary word-count target or automatically promote model-generated skills.
4. Leave compression off for model/task combinations where quality is unproven. Keep a direct-output
   fallback and explicit truncation/error signals.

Acceptance: restore an old needed fact, identify an omitted failure, resist injected historical
instructions, preserve source provenance, and compare both thinking and non-thinking configurations.

## Measurement and rollout

Build measurement alongside the first collector, using **new** `tools/benchmark_workflow.py` and sanitized
fixtures under `tests/fixtures/workflow/`. Private live traces belong in an owner-only local location;
public results require a separate public-safety review. Extend the existing memory benchmark only for
its retrieval questions; do not rename its character-based estimate as whole-task token accounting.

Record per attempt: task class, source revision, harness/tool versions, model, reasoning effort, service
tier, uncached input, cached input, output/reasoning accounting, all child calls, retries, review and parent
validation, tool durations, wall time, external wait, human corrections, and final acceptance. Use unique
request/attempt IDs to avoid counting cumulative usage events twice. Cached input is a subset of input;
reasoning may already be included in output. Unknown usage stays unknown, not zero.

A run is eligible for cost comparison only with complete attributable provider/client usage for all
parent/child attempts and a dated applicable rate card, or directly attributable billed credits. Account-
wide usage-window percentages are not task billing. Deduplicate request IDs; reconcile retries and
parent/child totals. Missing material usage makes cost results incomplete and ineligible for a cost-based
promotion claim. Such runs may separately report latency, output bytes, and independently assessed
quality; do not extrapolate missing tokens from character counts into a claimed billing result.

Report:

- accepted tasks per total token and per credit/dollar;
- total spend divided by accepted tasks, including failed attempts;
- median and p95 end-to-end time, with external waits shown separately;
- regressions, review defects, rework, and unfinished tasks by task class;
- cache hit rate and output-byte reduction as supporting metrics.

Start with 24–40 representative cases spanning lookup, continuation, implementation, visual acceptance,
review, and long-running checks; include deliberately difficult and failure cases. Freeze a held-out
subset before tuning and run at least three paired repetitions per configuration for the pilot. These
counts are a starting design, not a claim of sufficient statistical power. Increase repetitions based on
variance and the quality difference the owner requires the study to detect.

Compare the unchanged current configuration, optimized collection with the same model/effort, and then
the routing candidates. Change one major factor at a time before evaluating the combined workflow.
Use the same task snapshots, acceptance rubric, reviewer route, and resource limits. Blind human
assessment of ambiguous output where practical; a model's self-rating is not the quality measure.

Proposed promotion rule: no acceptance-invariant or serious-review regression; no known per-class
quality loss; paired uncertainty bounds must support the owner's quality requirement. Inconclusive
quality evidence keeps the existing route. A 20% reduction in total cost per accepted task is a useful
pilot target, not a forecast or a substitute for quality. Record token and latency tradeoffs separately.
Finite evaluations cannot guarantee zero future regressions; retain monitoring and rollback.

Deliver small PRs in this order:

1. Baseline schema, fixtures, bounded collector, and benchmark reporting.
2. Deterministic waiting and active-state views using that collector.
3. Preflight and focused preparation contracts.
4. Completion-receipt design/approval, validator, and aligned instructions.
5. Model/effort ADR, delegation contract, then opt-in routing experiments.
6. Proven consumer manifests and semantic artifact recipes.
7. Optional compression and instruction consolidation only after held-out results.

For each behavioral PR, provide old-defect detection, focused checks, independent PR review, and full
completion evidence under the existing methodology. Use the workhorse for appropriate heavy experiments
through its private offload workflow; preserve platform-specific artifact checks. Roll back each change
independently: direct collector fallback, previous installed configuration, uncached local completion,
or the original model route. Do not roll back by disabling governance.

The proposed router, CI receipt semantics, and evidence-schema changes need their applicable decisions
and approvals before activation. This document authorizes no configuration change, merge, release,
installation, or relaxation of existing gates.
