# Install For Agents

This document tells an AI agent how to install this stack onto a developer machine.

The direction is one-way:

```text
this repository -> local agent config
```

Do not sync local machine inventory, private prompts, credentials, caches, histories, or operational notes back into this repository.

## Install Contract

The goal is to make the stack available from the locations each agent already reads:

- a machine-level canon;
- tool-specific global entrypoints;
- tool-readable skill directories;
- optional private local notes outside this repository.

The repository is the distribution source. The local machine is the runtime environment.

## Steps

1. Inspect the destination machine.
   - Identify which agents are installed.
   - Identify their normal config and skill directories.
   - Prefer existing CLI tools for inspection.

2. Back up existing target files.
   - Back up entrypoints before replacing or merging them.
   - Back up existing skill directories before overwriting public stack skills.

3. Install the shared canon.
   - Copy `docs/canon.md` to the machine-level canon location, usually `~/AGENTS_GLOBAL.md`.
   - If the local machine uses a different canon path, update the installed entrypoints and skills to reference that path.

4. Install tool entrypoints.
   - Codex: install an `AGENTS.md` in the Codex global config location, usually `~/.codex/AGENTS.md`.
   - Claude: install a `CLAUDE.md` in the Claude global config location, usually `~/.claude/CLAUDE.md`.
   - Gemini / Antigravity: install a `GEMINI.md` in the Gemini global config location, usually `~/.gemini/GEMINI.md`.
   - Merge or copy the relevant adapter instructions from `adapters/`.
   - Rewrite repo-relative references such as `docs/canon.md` or `../../docs/canon.md` so they point to the installed machine-level canon.

5. Install skills.
   - Copy the entire skill directory for each selected skill, not only `SKILL.md`.
   - Preserve subdirectories such as `references/` because skills may link to them.
   - Install only skills that are useful for that machine and agent into their respective skill directories, such as `~/.codex/skills/`, `~/.claude/skills/`, `~/.gemini/skills/`, or `~/.agents/skills/`.
   - Rewrite installed skill canon references from `docs/canon.md` to the machine-level canon path.

6. Create or update private local notes when useful.
   - Local notes may include exact paths, available CLIs, account names, hostnames, project names, and operating facts.
   - Keep those notes outside this repository.
   - Do not commit them to the public stack.

7. Verify the install.
   - Confirm the machine-level canon is readable.
   - Confirm each installed entrypoint points to the machine-level canon.
   - Confirm each installed skill has its supporting files.
   - Confirm no runtime checkout of this repository is required for normal agent use.

## Tool Inventory Guidance

When taking stock of a machine, prefer local commands before integrations:

```bash
command -v git gh rg jq python3 node npm yarn pnpm make docker ssh rsync
git --version
gh auth status
```

Store detailed results in local private notes if they help future agents. Promote only generalized, public-safe rules back to this repository.
