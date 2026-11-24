# CaPhe Agentic Stack

**A small, always-on rulebook plus six on-demand skills that make Claude Code, OpenAI Codex, and Gemini work like a careful senior engineer: verify before claiming, keep diffs surgical, check dependencies for known CVEs before shipping, and spend frontier tokens only where they matter.**

One install gives all three agents the same operating rules. The rules cost about 1k tokens of context, and the specialized playbooks load only when a task needs them.

The rules and skills are instructions agents are asked to follow, not enforcement. See [what's enforced vs. what's guidance](#whats-enforced-vs-whats-guidance) for exactly what the stack does and does not guarantee.

```bash
git clone https://github.com/CaullenOmdahl/CaPhe-Agentic-Stack.git
cd CaPhe-Agentic-Stack
./install.sh
```

---

## Why this exists

Coding agents tend to fail in the same few ways:

| Failure | What CaPhe does about it |
| --- | --- |
| **Instruction bloat.** Giant `CLAUDE.md` / `AGENTS.md` files get re-read on every turn, crowding out the actual code. | A ~40-line [canon](docs/canon.md) is always loaded. Everything else is a [skill](skills/) that loads only when the task matches. |
| **"It's fixed" without running anything.** Agents reason about code instead of executing it. | The canon requires *oracles over prose*: typecheck → lint → targeted tests → build, plus a look at the real rendered output or response. |
| **Over-engineering.** Custom wrappers and abstractions where the framework already has a primitive. | The [`ponytail`](skills/ponytail/SKILL.md) ladder: needed at all? already in the repo? stdlib? framework? existing dependency? Write custom code only as a last resort, and never cut validation, types, or auth checks to get there. |
| **Frontier models doing intern work.** An expensive orchestrator spawns expensive subagents to grep files. | Ready-made `explorer` (fast tier), `worker` (standard tier), and `reviewer` (frontier tier) agent profiles for Claude Code and Codex. The stack never hard-codes a model name: you map each tier to a model from the provider's live list. See [model tiers](#model-tiers). |
| **Silent vulnerable deploys.** Dependency audits get skipped because nobody asked. | The canon instructs agents to run `caphe-cve-check`, an installed tool that is cached and uses no LLM tokens. When run, it flags high/critical CVEs and never reports a failed scan as clean. The optional, bypassable pre-push hook can fail a push on findings. Neither is a release gate by itself. |
| **Agents acting on irreversible things.** Prod deploys, migrations, force-pushes, auth changes. | The canon defines hard human stops that apply unless the repo's `.caphe.toml` or the user explicitly authorizes the action. |

## How context stays small

```
Always loaded   ~/AGENTS_GLOBAL.md (the canon) ··············· ~1k tokens, static, prompt-cache friendly
                + a 3-line pointer in CLAUDE.md / AGENTS.md / GEMINI.md

Session start   6 skill headers (name + one-line description) ··· ~50 tokens each

On demand       a skill's body, only when the task matches it
                e.g. git-github on "open a PR", verify-ship on "ship this"

Never loaded    docs/ and templates/: reference for humans and the installer
```

Because the canon never changes between turns, providers can serve it from the prompt cache. Details are in [docs/token-stack.md](docs/token-stack.md).

## What's inside

### The canon: [`docs/canon.md`](docs/canon.md)

The one file every agent always reads. Six short sections:

1. **Per-repo config.** Honor `.caphe.toml`. If it's missing, run `repo-init` once.
2. **Accuracy & code discipline.** State assumptions, go framework-first, keep diffs surgical, check API freshness instead of trusting memory.
3. **Production verification.** Real checks in order, the required CVE check (an instruction), inspection of real artifacts, a diff audit before shipping.
4. **Hard human stops.** Prod deploys, migrations, auth/secrets/billing, and irreversible or outward-facing actions.
5. **Token & tool hygiene.** Native tools first, bounded shell output, tiered delegation, no idle polling.
6. **Skill index.** Which skill to load for which task.

### Skills: [`skills/`](skills/)

| Skill | Loads when you're… | What it asks of the agent |
| --- | --- | --- |
| [`repo-init`](skills/repo-init/SKILL.md) | starting work in a repo with no `.caphe.toml` | Detects the toolchain, asks the per-repo judgment calls in one batch, writes `.caphe.toml` |
| [`ponytail`](skills/ponytail/SKILL.md) | designing, implementing, or refactoring | The 7-rung framework-first ladder plus production guardrails |
| [`verify-ship`](skills/verify-ship/SKILL.md) | verifying before commit, PR, merge, or deploy | Cheapest-first checks, the CVE gate, and a production-risk diff audit |
| [`git-github`](skills/git-github/SKILL.md) | branching, committing, pushing, opening PRs | Scoped branches, atomic commits, `gh`-based PRs, no self-merge without authorization |
| [`intended-behavior`](skills/intended-behavior/SKILL.md) | building user-facing UI, flows, or API behavior | A 5–10 line observable-behavior contract before code, then one real artifact checked |
| [`session-hygiene`](skills/session-hygiene/SKILL.md) | delegating or running long sessions | Tiered subagents, fresh-session handoffs, no frontier polling |

### What's enforced vs. what's guidance

Installing this stack changes what agents are *told* and gives them tools to run. It does not make them obey, and it does not gate releases.

| Layer | What it is | What it does and doesn't do |
| --- | --- | --- |
| **Instructions** (canon, skills) | Text agents are asked to follow | Nothing enforces compliance. An agent can skip or misapply a rule. |
| **Installed tools** (`caphe-cve-check`, `caphe-models`) | Scripts in `~/.local/bin`, run when invoked | Deterministic when run; nothing runs them automatically. |
| **Optional hook** (`hooks/pre-push-check.sh`) | A git pre-push hook you copy in yourself | Opt-in per repo. Bypassed by `CAPHE_SKIP_PRE_PUSH=1` or `git push --no-verify`. Runs `caphe-cve-check --if-stale 24`, then the `[verify]` commands. |
| **Repo-configured commands** (`.caphe.toml` `[verify]`) | Commands your repo declares | Only as strong as the commands you put there. |
| **External release controls** (branch protection, required reviews, CI gates) | Your platform's settings | **Not provided by this stack.** Setting them up is the operator's job. |

Caveats on the CVE check:

- **Cache window.** With `--if-stale 24`, a clean result is reused for up to 24 hours while the dependency files are unchanged. A new advisory published for unchanged dependencies in that window is not seen until the next real scan. Run `caphe-cve-check` without `--if-stale` before a release.
- **Scan incomplete (exit `2`).** A scanner error, no scanner, or partial coverage (any discovered manifest that no installed tool can audit) reports "SCAN INCOMPLETE" and is never cached as clean. The operator must resolve it, typically by installing `osv-scanner` or `trivy`; it is not a pass. The native fallbacks cover only some ecosystems (no yarn, bun, Maven/Gradle, Poetry/uv, Pipfile, Dart, or Ruby).
- **Not a guarantee.** A clean result means the scanner found no high/critical advisories it knows about in the files it scanned. It does not mean zero vulnerabilities.

### Agent profiles: [`templates/`](templates/)

| Role | Tier | Claude Code | Codex | Used for |
| --- | --- | --- | --- | --- |
| `explorer` | `fast` | read-only tools | low reasoning effort | File discovery, symbol search, log triage |
| `worker` | `standard` | full tools | medium reasoning effort | Well-scoped implementation and tests |
| `reviewer` | `frontier` | read-only tools | high reasoning effort | Production-risk and security diff review |

Profiles are templates with `{{tier:…}}` placeholders. The installer fills them in from your model tiers.

### Model tiers: [`bin/caphe-models`](bin/caphe-models)

No model names are hard-coded anywhere in this repo. Lineups change constantly and differ per provider, so you map each tier to a model once:

```bash
# No API key needed: on a subscription or coding plan, use the model aliases or IDs your client accepts.
# Aliases resolve to the client's newest models, so they never go stale.
caphe-models set claude fast <alias>     # repeat for standard and frontier
caphe-models set kimi fast <model>       # any client: deepseek, kimi, minimax, your own harness...

# Real model IDs, no key needed: the public models.dev catalog (best effort), or a provider API if a key is set.
caphe-models fetch                       # claude, codex, gemini, deepseek, kimi, minimax
caphe-models list kimi
caphe-models set claude fast <model-id>

./install.sh                             # re-render the agent profiles
```

Tiers live in `~/.config/caphe/models.toml`. A repo can override them under `[models.<client>]` in `.caphe.toml`, or under `.caphe.local.toml` for personal settings. Until a tier is set, its agents simply run on the client's default model, and the installer tells you which tiers are unset. If a model turns out to be unavailable to your account, agents record that themselves with `caphe-models mark-unavailable`, so it's hidden and any tier using it is cleared. Rate limits and outages never trigger this. Details are in [docs/model-tiering.md](docs/model-tiering.md).

### CVE gate: [`hooks/cve-check.sh`](hooks/cve-check.sh), installed as `caphe-cve-check`

Finds your manifests and lockfiles at the repo root and in nested workspaces (up to 6 levels deep, skipping dependency and build directories such as `node_modules`, `vendor`, `target`, and `.venv`; add more with `--exclude DIRNAME`), then scans them with `osv-scanner` (preferred, covers most ecosystems), or `trivy`, or falls back to native audits (`pnpm`/`npm audit`, `composer audit`, `cargo audit`, `pip-audit`, `govulncheck`).

```bash
caphe-cve-check                    # scan the current repo now
caphe-cve-check --if-stale 24      # skip if a clean scan ran in the last 24h and lockfiles haven't changed
caphe-cve-check --repo ../api --quiet-ok
```

| Exit | Meaning |
| --- | --- |
| `0` | No high/critical CVEs found by the scanner (or a clean result reused from the cache) |
| `1` | CVEs flagged: fix before deploying |
| `2` | Scan incomplete: a scanner error, no scanner installed, or any discovered manifest that no installed tool can audit (for example a `pom.xml` when only `npm` is available). Never cached as clean; the operator must resolve it |

Only clean scans are cached. Changing a lockfile invalidates the cache immediately, but a new advisory against unchanged dependencies is not seen until the cache expires (24h with `--if-stale 24`). Omit `--if-stale` for a fresh scan before a release.

## Install

**Requirements:** `bash`, `git`, Python **3.11+**. Recommended: [`osv-scanner`](https://github.com/google/osv-scanner) for universal CVE coverage. **No API key required**: `caphe-models fetch` uses the public models.dev catalog, and aliases always work. A provider key only makes `fetch` reflect your exact account.

```bash
./install.sh                    # rules, skills, agent profiles, CVE checker
./install.sh --apply-settings   # also merge tiered-subagent defaults into Claude & Codex settings
```

What lands where:

| Path | What |
| --- | --- |
| `~/AGENTS_GLOBAL.md` | The canon |
| `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md` | A small pointer block between `<!-- CAPHE:V2:BEGIN/END -->` markers. The rest of each file is left alone |
| `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/config/skills/`, `~/.agents/skills/` | The six skills |
| `~/.claude/agents/`, `~/.codex/agents/` | `explorer`, `worker`, `reviewer`, rendered with your model tiers |
| `~/.local/bin/caphe-cve-check`, `~/.local/bin/caphe-models` | The CVE gate and the model-tier tool |
| `~/.claude/settings.json`, `~/.codex/config.toml` | Only with `--apply-settings`: merged in, existing keys kept, backed up first |

### It won't clobber your setup

Re-running the installer is safe, because it keeps a record of everything it writes (`~/.local/state/caphe/install-manifest.tsv`):

- **Files you haven't touched** are upgraded in place.
- **Files you've customized**, or same-named files from another tool, are **kept** and listed in the output.
- **Agent profiles** are re-rendered whenever your model tiers change, so a new mapping takes effect on the next run.
- **`--force`** replaces the kept files with the stack version, saving each original first under `~/.local/state/caphe/backups/<timestamp>/` (same paths relative to `$HOME`). To restore one, copy it back.

<details>
<summary><strong>Uninstall</strong></summary>

Every path the installer wrote is in the manifest. Review the list, then remove:

```bash
cut -f1 ~/.local/state/caphe/install-manifest.tsv          # review
cut -f1 ~/.local/state/caphe/install-manifest.tsv | xargs -d '\n' rm -rf
rm -rf ~/.local/state/caphe ~/.config/caphe
```

Then delete the `<!-- CAPHE:V2:BEGIN -->` … `<!-- CAPHE:V2:END -->` block from `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and `~/.gemini/GEMINI.md`.

</details>

## Use it in a repository

The global stack stays identical everywhere. Per-repo judgment calls live in a small committed `.caphe.toml`, and personal overrides go in a gitignored `.caphe.local.toml`:

```toml
[git]
push_policy = "ask"            # ask | branch_auto | manual_only
allow_merge = false            # agents never merge unless the repo says so
github_actions = "disabled"    # disabled | manual_only | auto

[verify]
test = "pnpm test"             # the exact commands agents are told to run (and the pre-push hook runs)
typecheck = "pnpm typecheck"
```

You don't have to write it by hand. The first time an agent does non-trivial work in a repo without one, `repo-init` detects your toolchain and asks once. See the full [template](templates/repo/.caphe.toml).

You can also adopt the [`AGENTS.md` template](templates/repo/AGENTS.md) for repo-specific constraints, and point the other agents at it:

```bash
ln -s AGENTS.md CLAUDE.md && ln -s AGENTS.md GEMINI.md
```

**Optional pre-push hook (opt-in).** It runs `caphe-cve-check --if-stale 24`, then the `[verify]` commands from `.caphe.toml`. It is not installed by `install.sh`, and `CAPHE_SKIP_PRE_PUSH=1` or `git push --no-verify` bypasses it:

```bash
cp hooks/pre-push-check.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
```

## Repository layout

```
docs/canon.md            the always-loaded rulebook (installed as ~/AGENTS_GLOBAL.md)
docs/                    reference: model tiering, production safety, token stack
skills/                  six on-demand SKILL.md playbooks
templates/               tier-placeholder agent profiles, settings baselines, per-repo AGENTS.md + .caphe.toml
bin/caphe-models         fetch provider model lists, map tiers, render agent profiles
hooks/                   cve-check.sh (caphe-cve-check) and pre-push-check.sh
install.sh               idempotent, collision-safe installer
tests/test_v2.sh         the full verification suite
AGENTS.md, CLAUDE.md, GEMINI.md   entrypoints for agents working on this repo itself
```

## Development

All verification runs locally:

```bash
bash tests/test_v2.sh
```

The suite tests the installer and tools. It does **not** show that agents follow the canon or skills. The cheaper, fewer-defects, and fewer-tokens benefits described above are design intent, not measured results; the planned measurement is in [docs/evaluation.md](docs/evaluation.md).

The suite checks:

- **Syntax & validity.** Shell syntax, JSON, TOML, and skill frontmatter.
- **Context budgets.** The canon stays ≤ 70 lines, each skill ≤ 60, each entrypoint ≤ 15.
- **Installer, in a throwaway `$HOME`.** Idempotency, settings merges that keep existing keys, customizations preserved, `--force` backups, untouched files upgraded.
- **CVE gate, with a mocked scanner on a restricted `PATH`.** Clean scans are cached, lockfile changes invalidate the cache, a scanner error returns `2` and is never cached, findings return `1`, a missing scanner returns `2`.
- **Model tiers, against a local mock of the provider APIs and the models.dev catalog.** Keyless catalog fallback and filters, paginated API fetches, `set`/`get` precedence, `mark-unavailable` / `mark-available`, and rendering with tiers set and unset.
- **No model names.** Fails if any model name is hard-coded outside `tests/`.
- **Public safety.** No credentials, tokens, private keys, local user paths, or sensitive filenames are committed.

This repository is public. Never commit `.env*`, credentials, `.caphe.local.toml`, private hostnames, or local paths.
