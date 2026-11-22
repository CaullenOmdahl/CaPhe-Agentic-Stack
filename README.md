# CaPhe Agentic Stack (v2)

A lean, public-safe, cross-agent operating stack for **Claude Code**, **OpenAI Codex**, and **Gemini / Antigravity**—designed for **production accuracy**, **progressive context loading**, and **minimal token overhead**.

> Looking for the legacy Strict Mode v3 / Python harness stack? It is preserved on the `v1-archive` git tag.

## Why v2?
Modern frontier models absorb heavy orchestration glue natively. v2 strips ~10,500 lines of legacy scaffolding down to a thin, progressive-disclosure setup:

- **~55-line always-loaded canon** ([docs/canon.md](docs/canon.md)): Static and cache-friendly (~450 tokens). Encodes Karpathy's coding principles, Ponytail's framework-first minimalism, hard production stops, and native-tool hygiene.
- **Per-repo & per-person config** ([`.caphe.toml`](templates/repo/.caphe.toml) + gitignored `.caphe.local.toml`): Keep the stack identical across projects while toggling repo-specific rules (e.g., disable paid GitHub Actions on private repos, set push/PR policies, pin exact verification commands, toggle optional features). Missing `.caphe.toml` triggers a one-time `repo-init` setup interview.
- **6 bite-sized, on-demand skills** (`skills/`): Loaded only when a task matches—never dumped into every prompt:
  - [`repo-init`](skills/repo-init/SKILL.md) — first-run repo interview & `.caphe.toml` / `.caphe.local.toml` generator
  - [`ponytail`](skills/ponytail/SKILL.md) — 7-step framework-first / YAGNI ladder (never cuts validation, types, or security)
  - [`verify-ship`](skills/verify-ship/SKILL.md) — native typecheck -> lint -> test -> build gate + prod-risk diff audit
  - [`git-github`](skills/git-github/SKILL.md) — branch, commit, push, PR, CI, and review flow via `git` + `gh`
  - [`intended-behavior`](skills/intended-behavior/SKILL.md) — brief UX/API contract before non-trivial user-facing work
  - [`session-hygiene`](skills/session-hygiene/SKILL.md) — tiered subagents, `/clear` handoffs, and zero frontier polling
- **Native model tiering** (`templates/`): Ready-to-use configs and `explorer` / `worker` / `reviewer` agent profiles so frontier orchestrators stop spawning frontier subagents.
- **Zero `Stop` hooks, minimal MCPs**: Deterministic verification runs via native commands, non-discretionary CVE scanning ([`hooks/cve-check.sh`](hooks/cve-check.sh) installed as `caphe-cve-check`), and opt-in [`hooks/pre-push-check.sh`](hooks/pre-push-check.sh)—never blocking every turn.
- **Ecosystem-ready** ([docs/token-stack.md](docs/token-stack.md)): Pairs cleanly with **Ponytail**, **RTK**, and optional **Caveman**.

## Quick Install (Machine-Global)

```bash
./install.sh --apply-settings
```

`install.sh` is idempotent and non-destructive:
- Copies `docs/canon.md` to `~/AGENTS_GLOBAL.md`.
- Adds a small managed pointer block (`<!-- CAPHE:V2:BEGIN -->` ... `<!-- CAPHE:V2:END -->`) to `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and `~/.gemini/GEMINI.md` without overwriting your personal machine rules.
- Installs the 6 on-demand skills into `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/config/skills/`, and `~/.agents/skills/`.
- Installs tiered `explorer`, `worker`, and `reviewer` subagent definitions for Claude Code and Codex.
- `--apply-settings` merges non-destructive tiered subagent defaults into `~/.claude/settings.json` and `~/.codex/config.toml` (creating backups first).

## Using in a Production Repository

Copy [`templates/repo/AGENTS.md`](templates/repo/AGENTS.md) and [`templates/repo/.caphe.toml`](templates/repo/.caphe.toml) to your repo root (or let the agent run `repo-init` on first use), and optionally symlink `CLAUDE.md` and `GEMINI.md` to `AGENTS.md`:

```bash
ln -s AGENTS.md CLAUDE.md
ln -s AGENTS.md GEMINI.md
```

For an optional git pre-push verification hook (reads `[verify]` from `.caphe.toml`):

```bash
cp hooks/pre-push-check.sh /path/to/repo/.git/hooks/pre-push
chmod +x /path/to/repo/.git/hooks/pre-push
```

## Public-Safety Rule
This repository is public. Never commit credentials, tokens, `.env*` files, `.caphe.local.toml`, private hostnames, local usernames/paths, or private project notes. Run `bash tests/test_v2.sh` before pushing.
