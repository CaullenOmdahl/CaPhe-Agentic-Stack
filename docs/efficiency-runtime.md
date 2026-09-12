# Efficiency runtime: implementation and operation

Strict Mode v3 turns the [research proposal](efficiency-improvement-plan.md) into reusable tools for
bounded context, preparation, explicit delegation, and verifiable installation. The target is accepted
work per total cost, including parent inspection and repairs. A lower token price alone is insufficient.

## What is implemented

| Operation | Implementation | Acceptance boundary |
| --- | --- | --- |
| Gather context | `tools/stack_context.py` | Bounded UTF-8 output, source identity, explicit omissions/incomplete state |
| Wait for work | `tools/stack_watch.py` | Read-only JSON query, total deadline, status changes and actionable failures |
| Continue a task | `tools/stack_state.py` | Owner-only, repository-scoped state outside Git; original authorization preserved |
| Prepare generated files | `tools/stack_prepare.py` | Recipe, input, toolchain, environment and output freshness; failures never count as fresh |
| Choose model and effort | `tools/stack_route.py` | Closed delegation contract, live capabilities, explicit owner policy, incumbent fallback |
| Compare workflow cost | `tools/benchmark_workflow.py` | Final request identities, retries/children, paired task acceptance, explicit rate cards |
| Record acceptance | `strict-mode/bin/strict_evidence.py` | Immutable source-bound v2 snapshots; six separate acceptance phases |
| Run verification | `strict-mode/bin/strict_gate.py` | Actual working-state coverage, ordered preparation, failure propagation, uncached completion |
| Distribute and inspect | `tools/stack_install.py`, `tools/stack_doctor.py` | Explicit payload, rollback, effective hook verification; existing project content preserved |

Automatic CI receipt reuse is deliberately unavailable: a candidate workflow cannot certify its own
manifest, helper scripts, result producer, or isolation. Full local completion remains the fallback.
Consumer dependency graphs also remain unproven until repository-specific verification establishes
completeness. Installation does not silently shorten their full matrices. Masking defaults off; model
routes remain unpromoted without the paired evidence described below.

## Daily execution

Set `CAPHE_RUNTIME` to the installed distribution, normally `$HOME/.local/share/caphe/runtime`. This is
an installed payload without Git metadata; normal agent use does not depend on a source checkout.
Keep machine paths and raw outputs in private local records.

```bash
python3 "$CAPHE_RUNTIME/tools/stack_doctor.py" --repo . --runtime "$CAPHE_RUNTIME"
python3 "$CAPHE_RUNTIME/tools/stack_context.py" --repo . --max-bytes 4096
```

Use a simple `git status --short` when only a clean/dirty answer is needed; a full bound snapshot costs
extra local I/O. Read the compact result before fetching more. An incomplete or stale result requires a targeted refresh;
a matching pair of observations is not proof of filesystem isolation. Context and gate digests use
separate versioned formats: never substitute one for the other. Hidden Git index flags and submodules
must be resolved explicitly when the context collector reports them incomplete.
Context snapshot v3 streams tracked worktree bytes, modes, and symlink targets directly; a clean filter's
normalized Git diff cannot establish freshness. This adds file-reading cost even in a clean checkout.
The completion gate separately binds initialized nested Git repositories recursively, including their working changes.
Absent and empty uninitialized gitlinks have explicit identities; required checks still determine
whether their contents are needed. Unstaged gitlink replacements bind their actual file type and
visible contents; symlink leaves and replaced directory parents bind the link target without following
it, with former tracked descendants recorded as absent. Embedded repositories
inside parent-tracked directories bind their own HEAD and index. Malformed present Git metadata and
hidden index flags fail closed.

For history, feed `project_history_envelope` only caller-sanitized excerpts with source ID, coordinate,
and digest. It rejects raw tool/reasoning records and malformed envelopes. Pattern redaction is a second
check, not a universal secret detector. Retrieve more from canonical records only when acceptance needs
it. Do not copy full conversations into worker prompts or the public evidence directory.

For a read-only status query that emits the watcher's declared JSON fields:

```bash
python3 "$CAPHE_RUNTIME/tools/stack_watch.py" --timeout 45 --interval 5 \
  --process-timeout 10 --process python3 path/to/read_only_status.py
```

The query must report the watched task's status; its own successful process exit does not mean the task
finished. The first running observation establishes a baseline. Repeated unchanged observations consume
no model calls. The tool never posts comments, schedules tasks, or sends messages. A zero timeout does
not start a query. Use an app's purpose-built event wait when it already provides these guarantees.
Process-backed watching requires POSIX; native Windows fails before launching a query and directs the
caller to Linux or WSL. Parsing and comparing supplied observations does not launch processes.

## Preparation and checks

Declare an exact preparation recipe in private project state. Required fields are `argv`, relative `cwd`,
nonempty `inputs` and `outputs` file lists, toolchain probe argv lists, and explicit non-secret `env` values.
`timeout_seconds` is optional and defaults to 900. Inputs and outputs cannot overlap. The recipe receives
only basic process environment plus its declared values; it does not copy environment files.

```json
{
  "argv": ["python3", "scripts/generate.py"],
  "cwd": ".",
  "inputs": ["scripts/generate.py", "schema.json"],
  "outputs": ["generated/model.py"],
  "toolchain": [["python3", "--version"]],
  "env": {},
  "timeout_seconds": 300
}
```

Use the project's existing generation commands. For Flutter/Freezed/Riverpod work, declare the actual
package's build_runner command, lockfiles, source inputs, generated outputs, and toolchain rather than
assuming a fresh worktree already contains them. For a dynamic input set, regenerate the explicit list
from repository declarations before checking freshness. An incomplete recipe cannot prove freshness.

```bash
python3 "$CAPHE_RUNTIME/tools/stack_prepare.py" --root . \
  --manifest "$CAPHE_PRIVATE/prepare.json" --receipt-root "$CAPHE_PRIVATE/receipts"
python3 "$CAPHE_RUNTIME/tools/stack_prepare.py" --root . \
  --manifest "$CAPHE_PRIVATE/prepare.json" --receipt-root "$CAPHE_PRIVATE/receipts" \
  --check-receipt "$CAPHE_PRIVATE/receipts/selected-receipt.json"
```

Use canonical, owner-only private paths outside all repositories. Save the returned `receipt_path`
and pass its exact containing directory as `--receipt-root` when checking it. The read path enforces
the same private-storage boundary as writing; this is local provenance, not executor attestation.
The freshness check exits nonzero on missing or stale evidence. Never
skip required completion checks because preparation was fresh.

Preparation commands run on POSIX hosts. Their merged stdout/stderr is hashed incrementally through
a pipe; the deadline covers output collection and process completion. Failed runs retain unsuccessful
diagnostic receipts and never count as fresh preparation.

The gate includes staged, unstaged, and non-ignored untracked changes because checks execute the working
checkout. Commands in a component run in declared order by default. `parallel_safe: true` is an explicit
independence claim; use it only for checks that do not share installation or generation state. Failed
prerequisites block dependent commands. `depends_on` also orders selected components. Completion runs all
commands uncached, and a source change during checks requires a rerun against the resulting source.
Feedback cache v3 invalidates older markers. New markers publish only after the final source snapshot
is unchanged and only to Git-ignored, untracked destinations; otherwise the check remains uncached.

Gate process execution supports POSIX hosts; this distribution is verified on macOS and Linux.
Native Windows execution fails before launching checks; use a Linux environment such as WSL.
After a check or dependency-verifier timeout, the gate kills the original process group and gives
output collection a bounded grace period. It retains available failure output and closes inherited output pipes if descendants
keep them open. This bounds collection; it does not establish containment of detached descendants.
Ordinary completed commands retain their full output.
Custom dependency verifiers must leave the source snapshot unchanged; mutation rejects planning and
execution before narrower checks can run. Generated unittest manifests include both root modules and
`tests/` when present, with independently scheduled nested projects excluded from parent discovery.
Gate manifests reject unknown fields at every configuration level, so misspelled timeout or scheduling
options fail before execution instead of silently using a default.

```bash
bash "$CAPHE_RUNTIME/strict-mode/bin/strict-green-gate.sh" --mode affected
bash "$CAPHE_RUNTIME/strict-mode/bin/strict-green-gate.sh" --mode completion \
  --report "$CAPHE_PRIVATE/completion-diagnostic.json"
```

A diagnostic contains command outcomes and source hashes, not raw command output. It explicitly lacks
attestation authority. Prototype relaxation applies only to affected feedback; `full`, `completion`, and
plan/configuration failures are not relaxed. Existing explicit user disable remains user-controlled.

## Model, effort, and delegation

Keep Astra as coordinator for ambiguous contracts, architecture, integration, and escalation. Evaluate
cheaper models for narrow extraction and independently testable scoped changes. Test effort separately:
Terra low, medium, and high are different configurations. Do not assume lower effort preserves quality,
or that greater effort always improves it. Probe the exact model, effort, client, and service tier on
each machine, then record observed availability privately.

Pass `stack_route.py` a JSON object containing `contract`, `capabilities`, and `policy` on stdin. The
[delegation schema](../schemas/delegation-contract-v1.json) declares subject source, acceptance, allowed
writes/exclusions, required checks, output limits, repair budget, parent identity, and children. The
policy contains an explicit incumbent and task-class candidate routes. Missing promotion retains a
capability-validated incumbent; unsupported incumbents fail instead of silently selecting another model.
Owner approval metadata binds the exact route digest and evaluation references; the caller must supply
trusted policy. The JSON is a declaration, not cryptographic proof of approval.

Use at most two ordinary workers, no recursive delegation, and disjoint write scopes. A fresh context
contains the contract and relevant evidence, not full conversation history. Dispatch the resolved model
and effort explicitly through the available agent tool. Full-history forks inherit model/effort and are
not a cheap-route mechanism. After one failed repair, tighten the contract or escalate. Independent PR
review retains its separately approved reviewer route and human gates.

## Benchmark and promotion

Normalize provider telemetry into closed `request_final` events. Each request has a unique ID; each retry
has another ID. Declare parent and child IDs and close a root task exactly once. Bind repetitions to the
same task and acceptance digest. Quality evidence also requires `task_class`, `source_digest`, and
`harness_digest` on every request. The source digest is the SHA-256 of the frozen evaluation input/problem
snapshot, not a worker's output or changing repair workspace. The harness digest is the SHA-256 of a
canonical manifest covering acceptance code, harness configuration, and tool/dependency versions.
Preserve missing material usage as unknown. Record whether output
already includes reasoning; never add reasoning twice. Native credit rates and USD rates are separate
cards, dated and keyed by model and service tier. Unknown rates, children, usage, or closure make whole-task
spend ineligible. Partial observed spend is not the total.

```bash
python3 "$CAPHE_RUNTIME/tools/benchmark_workflow.py" \
  --card "$CAPHE_PRIVATE/rate-card.json" --incumbent astra-high \
  < "$CAPHE_PRIVATE/request-finals.jsonl"
```

The report compares paired root acceptance outcomes, averaging repetitions within each task and weighting
tasks equally within one task class. A trial's requests must share the same evaluation bindings, and
incumbent/candidate bindings must match for each task/repetition. Missing bindings, mixed classes, or
source/harness mismatches make quality inconclusive; legacy records retain otherwise eligible usage and
cost totals. Computed comparisons expose the class and paired evaluation bindings. Digest declarations
still require source provenance checks; merely filling in a hash does not establish a valid experiment.
The report records task and run counts separately. Its latency is final-root request duration, not
invented whole-workflow duration; collect independent end-to-end timing for overlapping workers/retries.
Each configuration must keep one model, effort, and service-tier tuple across recorded requests for a
quality comparison. Mixed routes, including different retry or child routes, make quality inconclusive
while retaining valid request-level cost totals. Comparing composite workflow policies requires a
separate stable policy contract that this benchmark does not yet implement.
Small samples are descriptive. Before promotion, run representative frozen tasks with the incumbent and
candidate, at multiple repetitions, under the same acceptance checks. Include parent review and all
repairs, rejection rate, escaped defects, external wait, cached input, output, and reasoning. Predeclare
quality tolerances and the minimum sample; retain the incumbent when evidence is inconclusive.

Fast mode is a separate cost decision from effort. Current official pricing lists a 2.5× standard-credit
multiplier for Astra Fast and GPT-5.6 Fast; API Priority has separate rates. Recheck the applicable card
rather than mapping a service label to a guessed multiplier. [OpenAI pricing](https://learn.chatgpt.com/docs/pricing),
[Speed configuration](https://learn.chatgpt.com/docs/agent-configuration/speed).

## Evidence and rollout

Use `PrivateStateStore` for next action, unresolved checks, source coordinates, and scoped authorization.
It rejects Git and canonical memory/transcript destinations. Authorization records preserve the user's
statement; the agent still checks that the next action is covered. No automatic memory ingestion is added.

The evidence CLI and `validate_record` require v2 snapshots. The deprecated Python `write_record` API
also accepts closed, bounded legacy notes with the same public-text checks and immutable IDs. These
notes remain explicitly unbound and stale; they cannot certify acceptance or participate in v2
supersession. The index may retain a validated ADR identifier, but suppresses legacy status, tests,
review text, and extra fields. Older records with unknown fields remain readable without becoming
writable through this compatibility path.

New public evidence writes use [schema v2](../schemas/public-evidence-v2.json). Record implementation,
validation, review, merge, release, and external acceptance separately. Use explicit not-applicable
reasons; source tests cannot imply device or release success. Artifact claims require matching artifact
bindings; device claims additionally require semantic acceptance. Update state through a new immutable ID with `supersedes`.
Legacy records remain readable and explicitly unbound. Generate the index with `strict_evidence.py`.

Install only a reviewed source payload. Plan first, apply with a private rollback journal, and verify
exact managed bytes. Upgrades remove retired files only from a verified prior runtime inventory, with
rollback; changed managed files require reconciliation and unrelated files remain untouched.
An initial install rejects existing files at managed destinations. Structural file/directory upgrades
require the replaced subtree to belong entirely to the previous inventory; unrelated children block them.
Then merge global canon/skill updates while preserving user-specific authorization
and operational instructions. Keep duplicate discovered skill copies consistent. Refresh project markers
and effective hooks using the new initializer; preserve dirty/staged/untracked work, custom hooks,
manifests, symlinked instruction aliases, and explicit disable. Verify every target with doctor and a
side-effect-free hook probe. Activation also records and checks the generated hook chain and every original
hook target, including forwarded hooks, without executing that chain. These local records detect drift;
they are not signed attestation. Older records without forwarded-target identities require reconciliation
through the original hook directory before doctor can verify them.
Global installation and project activation are distinct results.

Git resolves [relative hook paths](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corehooksPath)
from the hook's execution directory; [receive hooks run from the Git directory](https://git-scm.com/docs/githooks#_description).
The initializer rejects receive-sensitive hooks with relative invocations before changing files or
configuration, including such invocations in existing managed records. Reconcile and verify an absolute
original hook directory before retrying initialization.

If an original custom hook intentionally changes, verify and record that accepted change, restore
`core.hooksPath` in the worktree configuration to the recorded original hook directory, and rerun the
normal initializer followed by doctor. Save the managed hook path first and restore it if reconciliation
fails. Do not edit generated activation metadata merely to silence a
mismatch. Preserve the original hook and its arguments/stdin behavior throughout reconciliation.

A project without a proven affected graph retains its full checks. Do not replace a carefully maintained
manifest with a generated default. A machine update does not claim application release, hardware
readiness, or a completed production deployment. Keep detailed rollout inventories and exceptions private.

This repository's CI retains `tests/`, `test/`, and `strict-mode/test/` from the exact PR base in a
disposable checkout containing candidate product source. It runs the accepted runner and manifest there,
then separately against the untouched candidate checkout to discover candidate-added tests even when
the retained checks fail. Pushes to main use the preceding main commit; missing baseline policy fails
closed. Both source checkouts disable persisted credentials. Candidate replacements cannot remove the
accepted test implementations. The job rejects changed HEAD, index entries/flags, or nonignored source
state after checks.
The workflow and test sources still require independent review: this is not tamper-proof attestation or
a trusted receipt service. Additions to the candidate's check matrix need separate verification until
they become accepted baseline policy. GitHub's [PR event semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)
and [checkout configuration](https://github.com/actions/checkout) define the checkout boundary.
