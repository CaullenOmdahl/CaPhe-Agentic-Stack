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

**No API key needed.** Most people sign in to their client with a subscription or coding plan (Claude Code, Codex, Gemini CLI / Antigravity, DeepSeek, Kimi, MiniMax, …), and those don't expose a model-list API. You don't need one: set each tier to a model alias or ID your client accepts (usually documented under its `--model` option). Aliases resolve to the client's newest models, so they never go stale:

```bash
caphe-models set claude fast <alias>     # repeat for standard and frontier
caphe-models set kimi standard <model>   # any client name works, not just the built-in three
./install.sh
```

**To see real model IDs without a key**, `caphe-models fetch` reads the public [models.dev](https://models.dev) catalog. It's best effort: it lists what a provider offers, not what your plan includes. It keeps only current models that support tool calls and text output, which coding agents need. With a provider **API key**, `fetch` uses that provider's own API instead, which reflects your account:

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
| `gemini` (also Antigravity) | Gemini API `GET /v1beta/models` (models that support `generateContent`) | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| `deepseek`, `kimi`, `minimax` | models.dev catalog (`deepseek`, `moonshotai`, `minimax`) | — |
| any other client | `caphe-models fetch <client> --catalog-provider <models.dev id>`, or set aliases/IDs directly | — |

With no key, every client above falls back to the models.dev catalog (`claude` → `anthropic`, `codex` → `openai`, `gemini` → `google`).

Providers without a key are skipped. A value doesn't have to come from the fetched list: anything the client accepts works, and `set` only warns when it can't validate a value. Keys are read from the environment and never stored. `caphe-models` never reads a client's sign-in credentials.

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
- **Gemini / Antigravity:** no agent profiles. The entrypoint tells the agent to use fast-tier subagents for lookups, and to resolve the tier with `caphe-models get gemini fast`.

- **Other clients** (DeepSeek, Kimi, MiniMax, your own harness): no profiles are installed for them, but `caphe-models get <client> <tier>` gives any script or agent the model to use.

## When a model isn't available to your account

Catalog lists are best effort, so sometimes a listed model turns out to be unavailable to your account. When a model call's own error says the account can't use *that model* (404 model not found, 403 permission/plan) and other models on the same client still work, agents run the command below. If every model fails, that's a setup problem (key, sign-in, base URL, gateway), so agents report it instead of marking anything:

```bash
caphe-models mark-unavailable <client> <model> --reason "404 not_found_error: ..."
```

That records the model in `~/.local/state/caphe/models/unavailable.json`. The model is then hidden from `list`, refused by `set`, ignored if a repo override still names it, and not brought back by a later `fetch`. Any tier that named it is cleared, falling back to the client default, and the command prints how to re-render the agent profiles. Matching is exact: marking a full model ID doesn't affect a tier set to an alias of it, and vice versa. The state file is written atomically, so parallel agents can't corrupt it, and a damaged file is ignored with a warning rather than breaking installs. Transient errors (429, 5xx, timeouts) are never grounds for marking. `caphe-models mark-available <client> <model>` undoes it.

**Unset tier:** the installer drops the `model` line, so the agent runs on the client's default model, and the install output lists every unset tier. Tiering only takes effect once the tiers are set.
