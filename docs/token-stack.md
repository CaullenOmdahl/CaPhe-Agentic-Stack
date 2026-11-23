# Token Optimization Stack & Context Loading

## How Context Loading Works (Progressive Disclosure)
CaPhe v2 avoids loading everything up front:
1. **Always-loaded static base (~1k tokens):** Only the root entrypoint + `docs/canon.md` (installed to `~/AGENTS_GLOBAL.md`). Because it is short and static, providers serve it from the prompt cache, where cached input is billed at a fraction of the normal rate.
2. **On-demand skills (~50 tokens per skill header until matched):** Each skill under `skills/<name>/SKILL.md` exposes only its `name` and 1-line `description` at session start. The body loads **only** when the task matches (e.g., `git-github` loads only for branches/pushes/PRs; `verify-ship` loads only when verifying/shipping).
3. **Reference docs (`docs/*.md`, `templates/`):** Never auto-loaded into agent prompts; read by humans or `install.sh` only.

## Complementary Ecosystem Tools (4 Waste Layers)

| Waste Layer | Tool | How to Install / Use |
| --- | --- | --- |
| **1. Code bloat** *(what the agent writes)* | **Ponytail** (`DietrichGebert/ponytail`) + built-in `skills/ponytail` | Claude Code: `/plugin marketplace add DietrichGebert/ponytail` then `/plugin install ponytail@ponytail`. Codex: `codex plugin marketplace add DietrichGebert/ponytail`. Or rely on CaPhe's built-in `skills/ponytail/SKILL.md`. |
| **2. Terminal noise** *(what the agent reads)* | **RTK** (`rtk-ai/rtk`) | Install `rtk` binary from GitHub Releases or `cargo install --git https://github.com/rtk-ai/rtk`, then run `rtk init -g` (or prefix noisy commands with `rtk git ...`, `rtk test ...`). Compresses verbose CLI logs while preserving errors and exit codes. |
| **3. Chat verbosity** *(what the agent says)* | **Caveman** (`getcaveman.dev`) — optional | CaPhe v2 enforces concise peer tone by default; optionally add `/caveman lite` for ultra-terse sessions. |
| **4. Plugin & MCP bloat** | **Audit & prune regularly** | Disable overlapping process plugins (`superpowers`, `ralph-loop`, `feature-dev`) and unused MCP servers. Prefer local CLIs (`git`, `gh`, `cf`, `railway`, etc.). |
