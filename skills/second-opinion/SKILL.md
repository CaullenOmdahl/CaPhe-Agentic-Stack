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

## Commands

### Claude Code

```bash
out=$(mktemp "${TMPDIR:-/tmp}/second-opinion-claude.XXXXXX")
claude_model=$(awk -F= '$1 == "STRICT_CONFER_CLAUDE_MODEL" {sub(/^[^=]*=/, ""); print; exit}' ~/.config/caphe/review-models.conf)
test -n "$claude_model"
claude -p "PROMPT" --model "$claude_model" --no-session-persistence --permission-mode plan --add-dir "$PWD" \
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
