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

2. Preserve existing target content without leaving persistent backup canons.
   - Read existing target files before replacing them, and merge user-specific instructions instead of blindly overwriting.
   - If replacement is necessary, keep a temporary rollback copy only for the install operation.
   - Remove temporary rollback copies and install staging once verification passes unless the user explicitly asks to keep rollback artifacts.
   - The normal final state is active installed files in agent config locations, with no backup canons or copied stack trees.

3. Install the shared canon.
   - Copy `docs/canon.md` to the machine-level canon location, usually `~/AGENTS_GLOBAL.md`.
   - Expand the final path before writing references. For example, resolve `$HOME` first and write the resulting absolute canon path rather than relying on `~` expansion inside agent runtimes.
   - If the local machine uses a different canon path, update the installed entrypoints and skills to reference that expanded path.

4. Install tool entrypoints.
   - Codex: install an `AGENTS.md` in the Codex global config location, usually `~/.codex/AGENTS.md`.
   - Claude: install a `CLAUDE.md` in the Claude global config location, usually `~/.claude/CLAUDE.md`; some Claude environments read a home-level Markdown file directly, so verify and use the path the installed tool actually loads.
   - Gemini / Antigravity: install a `GEMINI.md` in the Gemini global config location, usually `~/.gemini/GEMINI.md`.
   - Merge or copy the relevant adapter instructions from `adapters/`.
   - Rewrite repo-relative references such as `docs/canon.md` or `../../docs/canon.md` so they point to the installed machine-level canon.
   - Rewrite every other copied repo-relative support reference, such as `../../docs/review-workflow.md`, to an installed local path, or convert the link to plain text or a public repository URL if that support document is not installed.

5. Install skills.
   - Copy the entire skill directory for each selected skill, not only `SKILL.md`.
   - Preserve subdirectories such as `references/` because skills may link to them.
   - Install only skills that are useful for that machine and agent into their respective skill directories, such as `~/.codex/skills/`, `~/.claude/skills/`, `~/.gemini/skills/`, or `~/.agents/skills/`.
   - Rewrite installed skill canon references from `docs/canon.md` to the machine-level canon path.

6. Install strict-mode source when selected.
   - Copy the checked-in `strict-mode/` tree to the machine's deployed strict-mode location.
   - Preserve executable modes under `strict-mode/bin/` and `strict-mode/test/`.
   - Run `strict-init.sh` only for repositories whose scaffold is absent or on an older
     `.agent/.strict-version`; ordinary skill invocation should not refresh files repeatedly.
   - Treat `FAST GREEN` as focused feedback. Completion requires `--mode completion`.

7. Configure local memory retrieval only when requested.
   - Keep private domain mappings, sanitized exports, physical palaces, and benchmark fixtures outside
     this public repository with owner-only permissions.
   - Use separate physical domain roots for separate security domains and a distinct palace directory
     for every index generation. Read the owner-only `active-generation` pointer instead of guessing
     which generation is current.
   - Pin the reviewed MemPalace version and keep embeddings local unless a separate human-gated decision
     authorizes a remote backend.
   - Do not enable automatic ingestion until the private adoption benchmark passes.
   - After a domain passes, use `memory/sync_mempalace.py` for bounded local-only updates. It advances
     `active-generation` only after the new generation completes successfully. If recurring sync is
     useful, schedule that deterministic command at the OS layer instead of waking a model.
   - A new index generation must rebuild every current export. Use `--limit 0` for that unlimited pass;
     bounded generation transitions fail before changing export state.
   - Mapping changes also require complete reconciliation when they exceed the configured limit; do not
     delete or hand-edit the owner-only mapping-state marker to bypass this gate.
   - Re-run owner-only hardening and the tree permission audit after every index write.

8. Create or update private local notes when useful.
   - Local notes may include exact paths, available CLIs, account names, hostnames, project names, and operating facts.
   - Keep those notes outside this repository.
   - Do not commit them to the public stack.

9. Verify the install.
   - Confirm the machine-level canon is readable.
   - Confirm each installed entrypoint points to the machine-level canon.
   - Confirm each installed skill has its supporting files.
   - Confirm no runtime checkout of this repository is required for normal agent use.
   - Confirm strict-mode source tests and the completion gate pass.
   - Confirm memory indexes are outside Git trees, owner-only, and citation-resolvable.

## Tool Inventory Guidance

When taking stock of a machine, prefer local commands before integrations:

```bash
for cmd in git gh rg jq python3 node npm yarn pnpm make docker ssh rsync; do
  echo "$cmd: $(command -v "$cmd" 2>/dev/null || echo "not found")"
done
command -v git >/dev/null && git --version || true
command -v gh >/dev/null && gh auth status || true
```

Store detailed results in local private notes if they help future agents. Promote only generalized, public-safe rules back to this repository.
