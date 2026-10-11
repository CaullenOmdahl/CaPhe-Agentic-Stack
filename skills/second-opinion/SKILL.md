---
name: second-opinion
description: Obtain an independent assessment when requested or as the selected implementation-review fallback.
---

# Second Opinion

Use a separately performed assessment of the actual diff under the shared `docs/canon.md`. The
reviewer may use the author’s model family; self-attestation by the author is not review. Different-family
review is optional for concrete risk, conflicting evidence, or an explicit owner requirement, not a
mandatory discovery or acceptance prerequisite. Choose a working existing capability with suitable
review quality and verified isolation. No model is assumed error-free.

For implementation review, use `docs/review-workflow.md`: remote preferred, one local fallback only
when unavailable/quota-limited or explicitly requested. Successful local review satisfies this route;
do not add a remote or different-family duplicate. Explicit design/writing requests remain separate.

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
copying credential files into the review input. Preserve actual required repository checks and custom hooks; optional CaPhe helpers are not
review prerequisites. Claude's broader `--safe-mode` also drops
instructions and hooks, so it is not a substitute for MCP-only isolation in an
ordinary repository review.

Use a bounded headless probe before a long review. On a stall, inspect stderr and
child-process startup for unrelated servers or hooks. Empty output and timeout
are failed reviews, never approval. MCP isolation removes that startup path; it
does not prove that every delay was caused by MCP. If the selected independent local fallback is
unavailable, report the review blocker instead of repeatedly launching unavailable reviewers.

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

### OpenCode (family of its configured provider)

A separately performed review is eligible regardless of provider family; confirm model capability
and isolation rather than requiring family diversity. Run `python3 <runtime>/tools/stack_setup.py review-routes
--current <agent>` to see which installed reviewers qualify on this machine.

OpenCode has no MCP-isolation flag, so point `XDG_CONFIG_HOME` at an empty directory: that loads no
global config, MCP servers, or plugins, while provider credentials (its data directory and environment)
still apply. Use the read-only `plan` agent, `--pure`, and attach the diff instead of letting the
reviewer run commands:

```bash
out=$(mktemp "${TMPDIR:-/tmp}/second-opinion-opencode.XXXXXX")
opencode_model=$(awk -F= '$1 == "STRICT_CONFER_OPENCODE_MODEL" {sub(/^[^=]*=/, ""); print; exit}' ~/.config/caphe/review-models.conf)
test -n "$opencode_model"
empty_config=$(mktemp -d)
git diff "$BASE"...HEAD > "${out}.diff"
XDG_CONFIG_HOME="$empty_config" opencode run --pure --agent plan -m "$opencode_model" \
  -f "${out}.diff" "PROMPT" > "$out" 2> "${out}.err"
```

The model uses OpenCode's `provider/model` form. Treat empty output or a non-zero exit as a failed
review, never approval.

### Codex separate review

Use as the selected separate local review when appropriate, including for a Codex author:

```bash
out=$(mktemp "${TMPDIR:-/tmp}/second-opinion-codex.XXXXXX")
codex_model=$(awk -F= '$1 == "STRICT_CONFER_CODEX_MODEL" {sub(/^[^=]*=/, ""); print; exit}' ~/.config/caphe/review-models.conf)
test -n "$codex_model"
codex exec review --uncommitted --skip-git-repo-check --ephemeral -m "$codex_model" -o "$out" \
  -c 'model_reasoning_effort="high"' \
  2> "${out}.err"
```

## Review discipline

Do not impose an overall deadline on a running review. Bounded capability probes and
short polling calls are operational checks, not review-duration limits. Elapsed time
alone does not justify killing the reviewer or switching routes.

- Send a neutral task description, not your preferred conclusion.
- Verify findings against current code before acting.
- Report the reviewer, executable version, resolved model, whether the headless call succeeded, and any
  fallback used.
- Empty output is failure, not approval.
- Require a separately performed actual-diff review; author self-attestation does not qualify.
