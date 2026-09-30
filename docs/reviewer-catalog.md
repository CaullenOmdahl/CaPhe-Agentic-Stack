# Reviewer catalog

Routes that can provide the single independent implementation review required by
[`review-workflow.md`](review-workflow.md), on any machine and any mix of installed agents.
Choose one route per change; this catalog only widens the set of routes to choose from.

Researched 2026-09-30. Vendor features, prices, and flags change often: check the source before
relying on an entry, and prefer entries marked **verified**.

- **verified**: invocation tested on a stack machine; exact commands live in the `second-opinion` skill.
- **documented**: taken from vendor documentation; test it on the machine, then promote it.

Run `python3 <runtime>/tools/stack_setup.py review-routes --current <agent>` to see which local
reviewers a machine has, their model family, and whether each is independent of the current agent.

## Independence

A reviewer is independent when its model family differs from the author's. Same-family review is
never independent fallback. "Configured-provider" tools (OpenCode, Copilot CLI, Cursor CLI, PR-Agent)
take the family of the model you configure, so confirm the model before counting them as independent.
Hosted review services run the vendor's own model mix; treat them as independent of a local author
only when the owner policy accepts vendor-managed reviewers.

## Who pays for the compute

Never set up a route that bills cloud compute to someone who did not choose it. Every route falls
into one of four groups:

1. **Your machine**: local CLIs and PR-Agent's CLI run locally. Only the model provider is billed,
   under the key or plan the operator already chose. **Default.**
2. **An existing subscription**: the Codex connector runs on OpenAI's side under the owner's ChatGPT
   plan and uses no GitHub Actions minutes.
3. **Third-party review services**: CodeRabbit, Greptile, and Cursor Bugbot run on the vendor's
   cloud. Use only when the owner opts in, and prefer free tiers.
4. **The repository's GitHub Actions minutes**: the Claude Code Action, PR-Agent as an Action, and,
   since 2026-06-01, Copilot code review on private repositories. These bill the repository owner's
   Actions minutes (plus model or Copilot usage). **Never add or trigger one by default**; only with
   the repository owner's explicit opt-in for that repository.

## Remote reviewers (on the pull request)

| Reviewer | Trigger | Family | Compute | Cost and limits | Notes |
|---|---|---|---|---|---|
| Codex code review (ChatGPT Codex connector) | `@codex review` comment, or automatic reviews | OpenAI | Subscription (OpenAI) | Included on ChatGPT plans; subject to Codex usage limits | Replies with a quota message when limits are reached; record that as unavailability. |
| PR-Agent run locally (`The-PR-Agent/pr-agent`, open source) | CLI `pr-agent --pr_url <url> review` from any machine | Any LiteLLM model (OpenAI, Anthropic, Gemini, MiniMax, DeepSeek, OpenRouter, local) | Your machine | The model provider only | Posts to the PR without Actions. One completion over the diff, no tools. A portable independent route using whichever provider key the operator already has. |
| CodeRabbit | Automatic on PRs after installing the app | Vendor-managed | Third-party service | Free plan, rate-limited (about 4 PR reviews an hour) | Opt-in only. Also has a CLI (below). |
| Greptile | Automatic on PRs after installing the app | Vendor-managed | Third-party service | Free tier of 50 reviews a month; then per-review billing | Opt-in only. GitHub and GitLab only. |
| Cursor Bugbot | Automatic or on demand from Cursor | Vendor-managed | Third-party service | Usage-billed, roughly $1 to $1.50 per run | Opt-in only. |
| GitHub Copilot code review | `gh pr edit <n> --add-reviewer @copilot` | GitHub-selected models | **Repository Actions minutes** on private repos (since 2026-06-01), plus Copilot usage | Copilot plan with code review | Explicit owner opt-in only. |
| Claude Code GitHub Action (`anthropics/claude-code-action`) | Workflow on `pull_request` or an `@claude` comment | Anthropic | **Repository Actions minutes** | `ANTHROPIC_API_KEY`, or a Pro/Max subscription via `CLAUDE_CODE_OAUTH_TOKEN` | Explicit owner opt-in only. |
| PR-Agent as a GitHub Action | Workflow on `pull_request` | Any LiteLLM model | **Repository Actions minutes** | Model provider plus Actions | Explicit owner opt-in only; prefer running the CLI locally. |
| Gemini Code Assist on GitHub | Enterprise app only | Google | Google Cloud enterprise | Enterprise subscription | The consumer app shut down on 2026-07-17: never request it. The enterprise app requires current installation evidence. |

## Local command-line reviewers

Run local reviewers read-only, on the implementation diff, with unrelated tool servers (MCP)
disabled, and treat empty output or a non-zero exit as a failed review.

| Reviewer | Binary | Family | Status | Headless read-only invocation |
|---|---|---|---|---|
| Claude Code | `claude` | Anthropic | verified | `claude -p` with plan permission mode, read-only tools, and an empty strict MCP config; see `second-opinion`. |
| agy (Antigravity) | `agy` | Google | verified | `agy --sandbox --mode plan --print`; see `second-opinion`. Direct Gemini CLI is not the Gemini-family route. |
| Codex CLI | `codex` | OpenAI | verified | `codex exec review`; same-family for Codex-authored work. |
| OpenCode | `opencode` | Configured provider | verified | `opencode run --pure --agent plan` with `XDG_CONFIG_HOME` pointed at an empty directory (no MCP servers or plugins) and the diff attached with `-f`; see `second-opinion`. |
| GitHub Copilot CLI | `copilot` | Configured model | documented | `copilot -p "<prompt>" --model <model> -s --no-ask-user`, granting no write or shell tools; `/review` exists interactively. |
| Cursor CLI | `cursor-agent` | Configured model | documented | `cursor-agent -p --mode ask "<prompt>"`; print mode proposes but does not apply changes unless `--force`. |
| Qwen Code | `qwen` | Alibaba (Qwen) by default | documented | `qwen -p "<prompt>" --approval-mode plan`, restricting MCP with `--allowed-mcp-server-names`. |
| Kimi Code CLI | `kimi` | Moonshot | documented, **unsafe headless** | `--print` auto-approves every tool call; use only inside an external sandbox such as a read-only container. |
| CodeRabbit CLI | `coderabbit` | Vendor-managed | documented | `coderabbit review` (plain, agent JSON, or interactive modes); sends the diff to CodeRabbit; free tier about 3 reviews an hour. |

Aider and similar edit-first agents are not listed: they have no read-only review mode.

## Choosing a route by machine

Remote review stays preferred. When it is unavailable, pick the first independent local reviewer:

| Author | Machine has | Suggested fallback |
|---|---|---|
| Codex | Claude or agy | Claude for correctness, agy for design; OpenCode with a non-OpenAI provider |
| Claude | Codex or agy | agy or Codex; OpenCode with a non-Anthropic provider |
| Either | only its own client | PR-Agent's CLI run locally with a model from another family that the operator already pays for (for example a MiniMax plan); for Claude-authored work, Codex review under an existing ChatGPT plan also qualifies. Actions-based reviewers only with the repository owner's opt-in |
| Any | nothing independent | Report the review blocker; never treat missing review as approval |

To promote a **documented** entry: run its read-only invocation on a real diff, confirm it cannot
write or reach unrelated tool servers, confirm non-empty output on success and a non-zero exit on
failure, then add the exact command to `second-opinion` and mark it verified here and in
`tools/stack_setup.py`.

## Sources

- [Copilot code review consumes Actions minutes from 2026-06-01](https://github.blog/changelog/2026-04-27-github-copilot-code-review-will-start-consuming-github-actions-minutes-on-june-1-2026/)
- [Request Copilot code review from GitHub CLI](https://github.blog/changelog/2026-03-11-request-copilot-code-review-from-github-cli/)
- [Copilot CLI agentic code review](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/agentic-code-review)
- [Copilot CLI headless mode](https://www.devleader.ca/2026/07/27/running-github-copilot-cli-in-scripts-and-cicd-pipelines-headless-mode)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
- [claude-code-action setup](https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md)
- [PR-Agent](https://github.com/The-PR-Agent/pr-agent) and [changing its model](https://docs.pr-agent.ai/usage-guide/changing_a_model/)
- [LiteLLM MiniMax provider](https://docs.litellm.ai/docs/providers/minimax)
- [CodeRabbit CLI](https://www.coderabbit.ai/cli)
- [Greptile pricing (2026)](https://gitautoreview.com/compare/greptile-alternative)
- [Cursor Bugbot](https://cursor.com/docs/bugbot) and [2026 pricing change](https://cursor.com/blog/may-2026-bugbot-changes)
- [Gemini Code Assist consumer sunset](https://developers.google.com/gemini-code-assist/docs/deprecations/consumer-code-review)
- [Codex code review on GitHub](https://learn.chatgpt.com/docs/third-party/github)
- [Cursor CLI headless](https://cursor.com/docs/cli/headless)
- [Qwen Code headless mode](https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/) and [approval modes](https://qwenlm.github.io/qwen-code-docs/en/users/features/approval-mode/)
- [Kimi Code CLI print mode](https://moonshotai.github.io/kimi-cli/en/customization/print-mode.html)
