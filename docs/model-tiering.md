# Model Tiering

CaPhe never names a model. Roles map to three **tiers**, and you decide which model each tier means for each client. Model lineups change constantly and differ per provider, so the stack stays correct without edits when a new model ships.

## Roles → tiers

| Role | Tier | Purpose |
| --- | --- | --- |
| **Explorer** | `fast` | Read-only codebase search, doc lookup, log triage |
| **Worker** | `standard` | Well-scoped implementation and unit tests |
| **Reviewer** | `frontier` | Read-only production-risk and security diff audit |
| **Orchestrator** | `frontier` | Planning, architecture, tricky debugging, final sign-off (your main session) |

## Choosing models: `caphe-models`

```bash
caphe-models fetch                              # pull live model lists from each provider with an API key set
caphe-models list claude                        # see what's available
caphe-models set claude fast <model-id>         # map a tier to a model
caphe-models show                               # every client x tier, and where each value comes from
./install.sh                                    # re-render agent profiles with the new mapping
```

| Client | Model list source | Key |
| --- | --- | --- |
| `claude` | Anthropic `GET /v1/models` (active models only) | `ANTHROPIC_API_KEY` |
| `codex` | OpenAI `GET /v1/models` | `OPENAI_API_KEY` |
| `gemini` | Gemini API `GET /v1beta/models` (models that support `generateContent`) | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |

Providers without a key are skipped. A value doesn't have to come from the fetched list: anything the client itself accepts (such as a client-side alias) works, and `set` only warns when it can't validate one. Keys are read from the environment and never stored.

## Where the mapping lives

| File | Scope |
| --- | --- |
| `~/.config/caphe/models.toml` | Machine-wide tiers, written by `caphe-models set` |
| `.caphe.toml` → `[models.<client>]` | Per-repo override (committed) |
| `.caphe.local.toml` → `[models.<client>]` | Personal override (gitignored) |
| `~/.local/state/caphe/models/<client>.json` | Fetched model lists (cache; re-fetch any time) |

Precedence: `.caphe.local.toml` > `.caphe.toml` > global. `caphe-models get <client> <tier> --repo .` prints the resolved value.

## How each client uses tiers

- **Claude Code:** agent profiles in `templates/claude/agents/` carry `model: {{tier:…}}`. The installer renders the configured model into `~/.claude/agents/`. With `--apply-settings`, `CLAUDE_CODE_SUBAGENT_MODEL` is set to the standard tier, so subagents without an explicit model don't inherit the frontier orchestrator.
- **OpenAI Codex:** agent profiles in `templates/codex/agents/` carry `model = "{{tier:…}}"` plus `model_reasoning_effort` (low / medium / high per role). They are rendered into `~/.codex/agents/`.
- **Gemini:** no agent profiles. The entrypoint tells the agent to use fast-tier subagents for lookups, and to resolve the tier with `caphe-models get gemini fast`.

**Unset tier:** the installer drops the `model` line, so the agent runs on the client's default model, and the install output lists every unset tier. Tiering only takes effect once the tiers are set.
