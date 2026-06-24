# CaPhe Agentic Stack

CaPhe Agentic Stack is a public-safe, agent-agnostic development workflow kit for teams or solo developers using multiple coding agents in the same codebase.

It is not an app framework, prompt dump, or private machine backup. It is a small set of shared operating rules, agent entrypoints, reusable workflow skills, and review/safety documentation designed to keep Codex, Claude, Gemini / Antigravity, and adjacent tools aligned.

## What This Repository Does

This repository provides:

- one shared canon for how coding agents should work;
- root-level entrypoint files that common agent tools can auto-detect;
- thin agent-specific adapters for Codex, Claude, and Gemini / Antigravity;
- reusable skills for review, branch orientation, and UX-first planning;
- a pull-request-centered review workflow;
- public-safety rules for keeping private machine and client details out of public docs;
- a research index of outside public accounts and repositories worth monitoring.

The main design goal is to prevent drift. Instead of maintaining unrelated `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` files with subtly different rules, each tool gets a thin entrypoint that points back to the same canon.

## What This Is Not

This repository intentionally does not include:

- credentials, tokens, cookies, signing keys, service accounts, or `.env` files;
- local cache, telemetry, browser state, session history, or task-state files;
- private hostnames, IP addresses, SSH aliases, VPN details, or network topology;
- client-specific release procedures, customer data, or private project history;
- a replacement for independent pull-request review.

If a workflow depends on private operational details, document the shape of the workflow here and keep the private values in an ignored local file or a private repository.

## Repository Layout

```text
.
├── AGENTS.md
├── CLAUDE.md
├── GEMINI.md
├── adapters/
│   ├── claude/CLAUDE.md
│   ├── codex/CODEX.md
│   └── gemini/GEMINI.md
├── docs/
│   ├── canon.md
│   ├── current-stack-inventory.md
│   ├── external-account-research.md
│   ├── external-workflow-integrations.md
│   ├── public-safety.md
│   └── review-workflow.md
└── skills/
    ├── code-refactor-review/SKILL.md
    ├── prepare-branch-context/SKILL.md
    └── ux-flow-plan/SKILL.md
```

## Core Concepts

### Shared Canon

[`docs/canon.md`](docs/canon.md) is the central operating model. It defines:

- autonomy and when agents should keep going;
- when to stop for a human;
- how to handle non-trivial behavior changes;
- the expected build and verification discipline;
- the pull-request review rule;
- public/private environment boundaries.

Agent-specific files should not reinvent those rules. They should point back to the canon and add only tool-specific notes.

### Root Entrypoints

The root files are designed for agent auto-detection:

- [`AGENTS.md`](AGENTS.md) for Codex-style agents;
- [`CLAUDE.md`](CLAUDE.md) for Claude-based tools;
- [`GEMINI.md`](GEMINI.md) for Gemini / Antigravity.

These files are intentionally short. They direct the agent to the relevant adapter and the shared canon.

### Agent Adapters

The `adapters/` directory contains tool-specific instructions:

- [`adapters/codex/CODEX.md`](adapters/codex/CODEX.md): Codex-specific notes around filesystem/network access, memory, and offload boundaries.
- [`adapters/claude/CLAUDE.md`](adapters/claude/CLAUDE.md): Claude-specific skill and review reminders.
- [`adapters/gemini/GEMINI.md`](adapters/gemini/GEMINI.md): Gemini / Antigravity-specific model-effort and offload reminders.

Adapters should stay small. If a rule applies to every agent, put it in `docs/canon.md`.

### Skills

The `skills/` directory contains reusable public workflow skills:

- [`skills/code-refactor-review`](skills/code-refactor-review/SKILL.md): review diffs for reuse, composition, codebase consistency, unnecessary indirection, React/frontend state slop, and avoidable churn.
- [`skills/prepare-branch-context`](skills/prepare-branch-context/SKILL.md): build read-only context for a branch or PR before follow-up work.
- [`skills/ux-flow-plan`](skills/ux-flow-plan/SKILL.md): map current and desired product flows before attaching implementation files.

These skills are local workflow aids. They do not replace tests, artifact verification, or independent PR review.

## Review Model

This stack treats pull requests as the canonical implementation-review path.

The default route is:

1. Work on a branch.
2. Inspect the actual diff before staging.
3. Commit only intended files.
4. Run relevant verification.
5. Push and open a pull request.
6. Trigger or wait for independent agent review where available.
7. Address actionable findings.
8. Leave merge approval to a human maintainer.

See [`docs/review-workflow.md`](docs/review-workflow.md) for the detailed route.

Local review tools are useful preparation. They are not proof that implementation review is complete.

## Public Safety

This repository is meant to be public. Before pushing, use the checks in [`docs/public-safety.md`](docs/public-safety.md), including scans for:

- secrets and token-like strings;
- local user paths;
- hostnames and IP-like strings;
- sensitive filenames such as `.env`, `.npmrc`, and credential/secret files.

The public-safety rule is conservative by design: if a workflow needs private details, keep them outside this repository and document only the reusable structure here.

## Stack Inventory

[`docs/current-stack-inventory.md`](docs/current-stack-inventory.md) describes the current public-safe shape of the stack: entrypoints, adapter roles, skill categories, review policy, worktree policy, and the boundary between reusable public workflow and private operational details.

## External Workflow Research

The stack includes two research documents:

- [`docs/external-workflow-integrations.md`](docs/external-workflow-integrations.md): records external workflow ideas already integrated or rejected, including the jnsahaj gists that motivated the first skills.
- [`docs/external-account-research.md`](docs/external-account-research.md): tracks public GitHub accounts and repositories worth monitoring, such as Vercel Labs agent-skill work, agent-agnostic repository guides, and multi-agent coordination catalogs.

Research notes are not automatically adopted rules. Changes to the stack should still go through a focused PR.

## How To Use This Stack

### In A Repository

For a repo that should follow this stack:

1. Copy or symlink the root entrypoint files your tools need:
   - `AGENTS.md`
   - `CLAUDE.md`
   - `GEMINI.md`
2. Keep `docs/canon.md` and the corresponding `adapters/` files available at the relative paths referenced by those entrypoints, or adjust the paths after copying.
3. Copy only the skills that are relevant to that repo.
4. Keep private local overrides outside the public repository.

### Globally On A Machine

For machine-global use, install the canon and adapters into the relevant tool config locations for that machine. Back up existing files before replacing them.

Typical targets are:

- `~/AGENTS_GLOBAL.md`
- `~/.codex/AGENTS.md`
- `~/.claude/CLAUDE.md`
- `~/.gemini/GEMINI.md`
- `~/.codex/skills/<skill-name>/`
- `~/.claude/skills/<skill-name>/`
- `~/.gemini/skills/<skill-name>/` when the local Gemini setup supports skills there;
- `~/.agents/skills/<skill-name>/` as a shared compatibility location for tools that read common agent skills.

Do not commit machine-global install scripts or paths here if they contain private hostnames, usernames, or local infrastructure details.

## How To Change This Stack

Use the same workflow this stack recommends:

1. Create a branch.
2. Keep the change scoped.
3. Update docs and skills together when their behavior changes.
4. Run public-safety checks.
5. Open a pull request.
6. Address agent and human review.
7. Merge only after review is satisfactory.

For new skills, keep `SKILL.md` concise and public-safe. Put detailed reference material in a linked `references/` file only when needed.

## Current Status

The current stack includes:

- shared canon and root entrypoints;
- Codex, Claude, and Gemini / Antigravity adapters;
- three workflow skills;
- PR-review and public-safety documentation;
- external workflow and account research notes.

Private project skills, local credentials, cache state, and client-specific operations are deliberately outside this repository.
