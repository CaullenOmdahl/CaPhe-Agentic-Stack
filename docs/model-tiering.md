# Model Tiering Across Environments

Use frontier models where reasoning quality protects production accuracy, and route exploration and well-scoped code writing to faster, cheaper tiers.

## Role Matrix

| Role | Purpose | Claude Code | OpenAI Codex | Gemini / Antigravity |
| --- | --- | --- | --- | --- |
| **Orchestrator** | Planning (Plan Mode), architecture, tricky debugging, final sign-off | `opus` (`effort: medium`, raise to `high` only when needed) | Frontier model (`medium`, raise to `high` when needed) | Frontier (`pro` / default) |
| **Explorer** | Read-only codebase search, doc lookup, log triage | `haiku` (`~/.claude/agents/explorer.md`) | Light tier (`~/.codex/agents/explorer.toml`) | `flash` |
| **Worker** | Well-scoped implementation & unit tests | `sonnet` (`~/.claude/agents/worker.md`, plus `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`) | Standard coding tier (`~/.codex/agents/worker.toml`) | `flash` / standard |
| **Reviewer** | Read-only production-risk & security diff audit | `opus` (`~/.claude/agents/reviewer.md`) | Frontier tier (`~/.codex/agents/reviewer.toml`) | `pro` |

## Preventing Frontier Subagent Leaks
- **Claude Code:** Set `"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"` in `~/.claude/settings.json` under `"env"` so subagents never default to `opus` via `inherit`. Use `templates/claude/agents/*.md` for explicit per-role routing.
- **OpenAI Codex:** Configure `[agents]` in `~/.codex/config.toml` with explicit `default_subagent_model`, `default_subagent_reasoning_effort`, and a sensible concurrency cap (`max_concurrent_threads_per_session = 6`). Use `templates/codex/agents/*.toml` for per-role routing.
- **Gemini / Antigravity:** Pass `Model: "flash"` when invoking research/exploration subagents; reserve `inherit`/`pro` for complex work.

> Do not hardcode retiring snapshot IDs into shared policies. Prefer client aliases (`opus`, `sonnet`, `haiku`, `flash`, `pro`) or update model names only in local client config.
