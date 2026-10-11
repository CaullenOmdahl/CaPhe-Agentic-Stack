---
name: codex-review
description: Run a separately performed Codex CLI diff review as the selected local fallback or an explicitly requested assessment.
---

# Codex Review

Follow the shared `docs/canon.md` and `docs/review-workflow.md`. A separately performed Codex review
can satisfy the selected implementation-review route for any author, including Codex. The author
merely asserting its own work is reviewed does not qualify. Prefer remote review; use this route when
remote is unavailable or local review is explicitly requested. Do not routinely duplicate remote review.
Different-family review is optional for concrete risk, conflicting evidence, or an explicit owner rule.

## Capability check

Check `codex --version`, resolve the model from `~/.config/caphe/review-models.conf`, and require a successful non-empty headless
invocation on the current machine. Reject missing, unknown, or lightweight model tiers for review. Do not
pin a versioned model in this public skill. If the user or an environment override requests a model, probe
that exact model with this client before the review. Record the resolved model with the result.

Model rejection or a message that the model requires a newer CLI means the route is unavailable until
the client/configuration is corrected. Do not reinterpret it as a completed review.

## Tool servers

Keep source/diff reviews free of unrelated MCP servers using a verified,
process-scoped CLI configuration or the existing isolated review boundary.
`--ephemeral` prevents session persistence; it is not evidence of MCP isolation.
Do not delete normal server configuration or copy credentials into a review
snapshot. Check the installed CLI's supported controls before choosing flags.
A stalled or empty run is unavailable, not approval. See the installed
`second-opinion` skill for the tested Claude MCP-only isolation command when
using that independent reviewer instead.

## Review commands

```bash
codex_model=$(awk -F= '$1 == "STRICT_CONFER_CODEX_MODEL" {sub(/^[^=]*=/, ""); print; exit}' ~/.config/caphe/review-models.conf)
test -n "$codex_model"

# Uncommitted work
codex exec review --uncommitted --ephemeral -m "$codex_model" -c 'model_reasoning_effort="high"' -o /tmp/codex-review.md

# Branch diff
codex exec review --base main --ephemeral -m "$codex_model" -c 'model_reasoning_effort="high"' -o /tmp/codex-review.md

# Specific commit
codex exec review --commit <SHA> --ephemeral -m "$codex_model" -c 'model_reasoning_effort="high"' -o /tmp/codex-review.md
```

For a focused prompt, current Codex CLI review accepts an optional prompt:

```bash
codex exec review --uncommitted --ephemeral -m "$codex_model" -c 'model_reasoning_effort="high"' -o /tmp/codex-review.md \
  "Review only <scope>. Report concrete P1/P2/P3 bugs with file and line references."
```

Inspect stderr when the command fails or produces no output. Verify every finding against current code,
state agreements and disagreements with evidence, and report the client version and review scope.
