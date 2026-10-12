# Current Stack Inventory

This is a public-safe inventory of the repository's distribution shape. It intentionally avoids local usernames, hostnames, client names, credentials, cache paths, private release procedures, and live machine inventories.

## Agent Entrypoints

The distribution provides one shared canon with thin agent-specific adapters:

- Root tool files: detected by each agent and point to the adapter plus canon.
- Codex adapter: points to the shared canon and adds sandbox, memory, and offload cautions.
- Claude adapter: points to the shared canon and adds skill/review reminders.
- Gemini / Antigravity adapter: points to the shared canon and adds model-effort and offload reminders.

The important pattern is single-source canon plus small adapters. Parallel full copies should be avoided because they drift. Tool-native filenames can coexist with consistent human-facing adapter filenames when a tool expects a specific entrypoint.

Machine-global installs should use the agents' normal config locations rather than a runtime checkout of this repository. The repository files are source templates; installed copies should point at the machine-level canon and installed skills. Local install notes and machine inventories are allowed, but they live outside this public repo.

## Skill Categories

The shipped skills cover process and verification, product/UX planning, branch orientation,
diff review, shared private memory, derived recall, and optional model orchestration.

Provider deployment, document creation, browser control, device automation, and client-specific release
skills may exist on an operator's machine. They are not bundled here and are not prerequisites.
Only generic, reusable, public-safe skills should be promoted into this repository.

## Public Skills In This Repository

| Skill | Purpose |
| --- | --- |
| [code-refactor-review](../skills/code-refactor-review/SKILL.md) | Assess reuse, consistency, composition, unnecessary indirection, and avoidable churn |
| [codex-review](../skills/codex-review/SKILL.md) | Run a separately performed, capability-probed Codex CLI diff review |
| [gh-review-certify-loop](../skills/gh-review-certify-loop/SKILL.md) | Discover active reviewers and follow relevant PR findings |
| [intended-behavior](../skills/intended-behavior/SKILL.md) | Establish observable behavior before implementation |
| [memory-palace-recall](../skills/memory-palace-recall/SKILL.md) | Retrieve scoped, sanitized, source-linked local evidence |
| [orchestrate](../skills/orchestrate/SKILL.md) | Resolve bounded remote work using capability and owner-policy constraints |
| [prepare-branch-context](../skills/prepare-branch-context/SKILL.md) | Orient to a branch or PR without changing it |
| [project-memory](../skills/project-memory/SKILL.md) | Read and maintain durable memory in private project Git or a private hub |
| [route-review](../skills/route-review/SKILL.md) | Recommend route changes from private telemetry without editing policy |
| [second-opinion](../skills/second-opinion/SKILL.md) | Select and probe an available separate assessment route |
| [strict-mode](../skills/strict-mode/SKILL.md) | Apply the canon and relevant verification procedures |
| [ux-flow-plan](../skills/ux-flow-plan/SKILL.md) | Map current and desired product flows before implementation planning |

Skills are instruction packages. Tool-dependent skills need their referenced runtime components and
machine-local capabilities; copying `SKILL.md` alone does not install those dependencies.

## Tooling Policy

Agents should inspect the active machine for useful local CLIs before using auth-dependent integrations. Common high-value tool categories to check for include version control, repository hosting CLIs, fast search, JSON tooling, language runtimes, package managers, test runners, build tools, container CLIs, SSH, and file sync tools.

The reusable rule is CLI-first, auth-light tool selection:

- Prefer the developer's existing CLI and repository scripts over MCP servers or hosted integrations.
- Use `git` and `gh` for repository and GitHub work when they are authenticated and sufficient.
- Use MCP or app integrations when they provide unique access, safer structured data, or the user explicitly asks for them.
- Keep exact private paths, account names, hostnames, and tokens out of this public inventory. Store those details locally when they help the agent operate the developer's environment.

## Current Review Policy

Follow the canon and [practical review guidance](review-workflow.md): use one separate review when
useful or required, remote preferred. When a review requirement applies, successful separate local
review satisfies the implementation-review gate. Local self-review and design discussion do
not. Preserve actual branch protections and human merge/release gates; do not duplicate a completed
fallback with remote review. This inventory summarizes policy and is not a separate authority.

The canon defines proportionate checks and closure. Full matrix execution is explicit and relevant for
broad changes or project requirements; optional QA and new evidence files do not block resolved defects.

## Current Worktree Policy

Use isolated branches or worktrees for meaningful changes. Before answering repo-state questions, inspect the actual checkout and distinguish:

- tracked modifications,
- staged changes,
- untracked files,
- unpushed commits,
- sibling worktrees.

## Public-Repo Boundary

Do not copy raw home-directory configuration, caches, auth files, project histories, machine inventories, or private skill bodies into this repo.
