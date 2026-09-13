---
name: second-opinion
description: Obtain an independent AI assessment for code, architecture, writing, or ship-readiness when the user asks for another model's view or local review preparation is useful.
---

# Second Opinion

Use another model family for independent assessment. In a Codex session, prefer Claude Code for
correctness-focused code review and agy for Gemini-family product, architecture, or writing review.
Codex is a same-family fallback and must be labeled that way. Local review never substitutes for the
repository's pull-request implementation-review gate.

## Capability check

Treat availability as machine-local and current:

1. Check the executable and version.
2. Use an authenticated headless invocation and require non-empty output.
3. Resolve and record the actual model from `~/.config/caphe/review-models.conf`. Require a review-grade
   capability tier: Gemini Pro High through agy, Claude Sonnet or stronger, or a non-lightweight current
   Codex model with high reasoning. Do not float to the newest inventory result.
4. Treat missing tools, expired authentication, missing/unknown/lightweight models, empty output, timeout,
   or model rejection as unavailable.

Direct Gemini CLI is not the default Gemini-family route. Use `agy`; it is the supported headless route
when its live probe succeeds.

## Tool-server isolation for local reviews

Start source/diff reviews with no MCP servers. For Claude Code, pass
`--strict-mcp-config --mcp-config '{"mcpServers":{}}'` on each review invocation.
`--tools` controls built-in tools; it does not prevent MCP server startup. Use
`--tools 'Read,Glob,Grep'` for file inspection, or `--tools ''` when the complete
review material is supplied in the prompt. If a review actually needs an external
service, keep strict mode and pass a minimal explicit MCP configuration for only
that service. Never delete or rewrite the user's normal MCP configuration.

For other reviewer CLIs, verify their current isolation flags or use the existing
isolated `strict-confer` boundary; do not assume Claude flags are portable. Keep
model authentication available through the supported client mechanism without
copying credential files into the review input. Do not disable repository hooks
or completion gates to speed up review. Claude's broader `--safe-mode` also drops
instructions and hooks, so it is not a substitute for MCP-only isolation in an
ordinary repository review.

Use a bounded headless probe before a long review. On a stall, inspect stderr and
child-process startup for unrelated servers or hooks. Empty output and timeout
are failed reviews, never approval. MCP isolation removes that startup path; it
does not prove that every delay was caused by MCP. Preserve the repository's PR
review requirement instead of repeatedly waiting on an unavailable local route.

## Commands

### Claude Code

```bash
out=$(mktemp "${TMPDIR:-/tmp}/second-opinion-claude.XXXXXX")
claude_model=$(awk -F= '$1 == "STRICT_CONFER_CLAUDE_MODEL" {sub(/^[^=]*=/, ""); print; exit}' ~/.config/caphe/review-models.conf)
test -n "$claude_model"
claude -p "PROMPT" --model "$claude_model" --no-session-persistence --permission-mode plan --add-dir "$PWD" \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools 'Read,Glob,Grep' \
  > "$out" 2> "${out}.err"
```

### agy (Gemini family)

```bash
out=$(mktemp "${TMPDIR:-/tmp}/second-opinion-agy.XXXXXX")
agy_model=$(awk -F= '$1 == "STRICT_CONFER_AGY_MODEL" {sub(/^[^=]*=/, ""); print; exit}' ~/.config/caphe/review-models.conf)
test -n "$agy_model"
agy --sandbox --mode plan --dangerously-skip-permissions --effort high --add-dir "$PWD" \
  --model "$agy_model" --print="PROMPT" > "$out" 2> "${out}.err"
```

The permission skip is bounded by agy's sandbox and plan mode. Do not remove either boundary.

### Codex same-family fallback

Use only when the current agent is not Codex, or after independent families are unavailable and the
result is explicitly labeled same-family:

```bash
out=$(mktemp "${TMPDIR:-/tmp}/second-opinion-codex.XXXXXX")
codex_model=$(awk -F= '$1 == "STRICT_CONFER_CODEX_MODEL" {sub(/^[^=]*=/, ""); print; exit}' ~/.config/caphe/review-models.conf)
test -n "$codex_model"
codex exec review --uncommitted --skip-git-repo-check --ephemeral -m "$codex_model" -o "$out" \
  -c 'model_reasoning_effort="high"' \
  2> "${out}.err"
```

## Review discipline

- Send a neutral task description, not your preferred conclusion.
- Verify findings against current code before acting.
- Report the reviewer, executable version, resolved model, whether the headless call succeeded, and any
  fallback used.
- Empty output is failure, not approval.
- Do not call a Codex-on-Codex result independent review.
