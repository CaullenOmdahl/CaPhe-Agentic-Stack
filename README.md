# CaPhe Agentic Stack

**One shared workflow for coding agents. Clear expectations, useful verification, and continuity across tools.**

CaPhe helps solo developers and teams use Codex, Claude Code, and Gemini / Antigravity in the same
codebase without maintaining three competing sets of instructions. A shared operating canon tells
agents how to work; small adapters make it readable by each tool. Reusable skills and optional CLI
helpers support planning, review, verification, delegation, and private project memory.

Start with the instructions. Add tools when they solve a concrete problem.

[Get started](#get-started) · [Documentation](docs/README.md) · [Workflow examples](docs/workflow-examples.md) · [Contribute](CONTRIBUTING.md)

## Why CaPhe?

The difficult part of using several coding agents is keeping their work consistent: what counts as
done, which decisions need a human, where project knowledge lives, and how a new session picks up.
CaPhe makes those expectations explicit and portable.

| Common friction | What CaPhe provides | Why it helps |
| --- | --- | --- |
| Different agents follow different rules | One [canon](docs/canon.md), with thin tool adapters | Change shared policy in one place and reconcile installed copies |
| A plausible answer gets mistaken for finished work | Relevant checks, actual-result inspection, and separate diff review when useful or required | Assess the result using evidence |
| Small tasks accumulate process overhead | Proportionate workflow; one executor by default; optional helpers | Match effort to the change and its risk |
| Sessions lose project decisions | Shared [private project memory](docs/memory-architecture.md), accessible across agents | Carry durable knowledge forward without tying it to one client |
| Delegation obscures the model, permissions, or cost | Explicit CLI worker routes, bounded briefs, isolated source snapshots, and usage records | Inspect what ran and under which constraints |
| Public workflow docs collect private machine details | One-way installation and explicit [public/private boundaries](docs/public-safety.md) | Share reusable practices while keeping operational state private |

These are design benefits, not a claim of measured productivity or cost savings. Historical experiments
have narrow scopes; use your own tasks and acceptance criteria to evaluate the stack.

## Get started

### Explore without installing

You need Git to clone the repository. For the CLI examples, use Python 3.11 or newer on macOS or Linux
(including a Linux environment such as WSL). The worker harness uses Python's `tomllib`.

```bash
git clone https://github.com/CaullenOmdahl/CaPhe-Agentic-Stack.git
cd CaPhe-Agentic-Stack
python3 tools/stack_context.py --repo . --max-bytes 4096
```

The context command reports bounded repository state; it does not install the stack or launch a model.
Then read the [canon](docs/canon.md) and [workflow examples](docs/workflow-examples.md).
Agent clients, authentication, and provider subscriptions are supplied separately by the operator.

### Use the instructions in a project

1. Read the canon and reconcile it with your project's existing requirements.
2. Merge the root entrypoint your agent reads: [`AGENTS.md`](AGENTS.md), [`CLAUDE.md`](CLAUDE.md),
   or [`GEMINI.md`](GEMINI.md). Preserve existing project instructions.
3. Keep `docs/canon.md` and the corresponding `adapters/` files at the referenced relative paths,
   or rewrite those references to your chosen locations.
4. Install selected complete `skills/<name>/` directories into the skill locations your client reads.
   Keep supporting files and update references to the canon and any required runtime tools.
5. Ask the agent to read the entrypoint and describe the applicable workflow before its first change.

Instruction-only adoption does not require the worker harness, memory hub, hooks, or a new hosted service.
For machine-global installation, path rewriting, runtime verification, and upgrades, follow
[Install for agents](docs/install-for-agents.md). The installer manages the runtime payload;
merging global instructions and activating a project are separate steps.

An installation request you can give your agent:

> Read `docs/install-for-agents.md`. Inspect my existing agent configuration, propose a scoped install,
> and preserve my instructions. Install only the components I select. Keep private machine state outside
> the public repository and verify the resulting entrypoints, skills, and runtime references.

## What a task looks like

For a substantial bug fix, the workflow is straightforward:

1. Establish the intended behavior and inspect the relevant code.
2. Implement the smallest coherent fix on a branch.
3. Add a regression when it protects the behavior, run relevant checks, and inspect the result.
4. Obtain one separate diff review when useful or required; address real findings.
5. Report what changed, what passed, and any remaining limitations. Preserve required GitHub checks
   and human approval for consequential actions.

A wording correction can simply be edited and inspected. A release, secret-handling change, or data
migration needs its applicable safeguards and scoped authorization. Optional QA remains separate from
closing a verified defect. See [concrete examples](docs/workflow-examples.md).

## Choose your components

| Component | Use it for | Start here |
| --- | --- | --- |
| Shared canon and adapters | Consistent instructions across agents | [Canon](docs/canon.md), [adapters](adapters/) |
| Workflow skills | Behavior discovery, UX planning, branch context, and review | [Skill inventory](docs/current-stack-inventory.md#public-skills-in-this-repository) |
| Verification runtime (`strict-mode/`) | Affected checks, optional full matrices, and project hook integration | [Runtime overview](strict-mode/README.md) |
| Context, preparation, and status tools | Bounded discovery, generated-file freshness, and deterministic waiting | [Efficiency runtime](docs/efficiency-runtime.md) |
| CLI worker harness | Explicit task routes and isolated delegated work | [Harness operation](docs/efficiency-runtime.md#model-effort-and-delegation) |
| Shared project memory | Durable facts in private project Git or a private hub | [Memory architecture](docs/memory-architecture.md) |
| MemPalace adapter | Optional local retrieval over sanitized, source-linked records | [Derived retrieval](docs/memory-architecture.md#derived-retrieval-index) |
| Model-routing proof of concept | Capability-gated remote dispatch and route evaluation | [Routing scope](docs/model-routing.md) |

### Compatibility and current limits

- **Instructions:** dedicated entrypoints and adapters for Codex, Claude Code, and Gemini / Antigravity.
  Other clients can adapt the canon; verify their instruction and skill discovery rather than assuming it.
- **Runtime:** process execution targets macOS and Linux. Native Windows execution of the verification,
  preparation, and process-watching helpers is unsupported; use Linux/WSL.
- **CLI workers:** Codex is the implemented worker adapter. Non-Codex harness adapters remain disabled.
  Instruction support for a client does not imply worker support.
- **Model routing:** the public registry is catalog metadata, not proof of authenticated availability.
  Remote dispatch is a proof of concept requiring private capability and owner-policy configuration.
- **Updates:** the harness updater requires signed tagged releases and separately established signing
  trust. A source checkout or installable payload does not imply a signed release is available.
- **Review:** use one suitable, separately performed review when useful or required. The same model
  family is eligible; author self-attestation is not review. Actual repository requirements still apply.
- **CI:** GitHub Actions is disabled for cost control. The checked-in workflow is a manual opt-in recipe;
  there is no automatic CI badge or implied hosted check coverage.

## Privacy and trust

Installation flows from this repository to local agent configuration. Private machine inventories,
credentials, histories, caches, task state, and client operations do not flow back into this repository.
Private project memory lives in private Git or a private hub; public repositories never receive it.
MemPalace indexes are optional, local, rebuildable, and separated by security domain.

The worker harness limits source access through its snapshot and permission boundaries. These controls
have explicit failure modes and prerequisites; a model name, installed binary, or successful process exit
alone does not prove a task was safely completed. See [runtime boundaries](docs/efficiency-runtime.md)
and [public-safety rules](docs/public-safety.md).

## Documentation and source map

The [documentation index](docs/README.md) separates getting started, operating guides, and historical research.
The [canon](docs/canon.md) is the sole shared workflow policy authority; other pages explain its use.

```text
AGENTS.md / CLAUDE.md / GEMINI.md   Agent entrypoints
adapters/                         Tool-specific instructions
skills/                           Reusable workflow skills and references
bin/harness                       CLI worker harness entrypoint
tools/                            Install, context, routing, and lifecycle helpers
strict-mode/                      Verification runner, hooks, templates, and tests
memory/                           Shared-memory and derived-retrieval tools
registry/ / schemas/              Model catalog and validation contracts
docs/                             Guides, research, and design decisions
tests/ / test/                    Python regressions and public-safety checks
```

## Contributing and feedback

Use [GitHub issues](https://github.com/CaullenOmdahl/CaPhe-Agentic-Stack/issues) for reproducible bugs,
confusing documentation, and focused proposals. Include public-safe examples, the component involved,
and expected versus observed behavior. Keep credentials and private operational details out of issues.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for local checks and the PR workflow. Small improvements to
instructions and examples are welcome; policy changes should update the canon and affected procedures together.

## License

This repository currently has no license file. Public visibility does not provide an explicit
open-source license. License selection remains a maintainer decision.
