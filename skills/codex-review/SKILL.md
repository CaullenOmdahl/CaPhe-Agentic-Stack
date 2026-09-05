---
name: codex-review
description: Run Codex CLI review for a non-Codex author, or an explicitly requested same-family Codex audit, without mistaking it for independent PR review.
---

# Codex Review

Codex reviewing Codex is not an independent audit gate. Do not auto-run this after ordinary Codex
implementation work. Use it for a non-Codex author or when the user explicitly requests a same-family
audit, and label the result accurately. It never replaces pull-request implementation review.

## Capability check

Check `codex --version`, resolve the model from `~/.config/caphe/review-models.conf`, and require a successful non-empty headless
invocation on the current machine. Reject missing, unknown, or lightweight model tiers for review. Do not
pin a versioned model in this public skill. If the user or an environment override requests a model, probe
that exact model with this client before the review. Record the resolved model with the result.

Model rejection or a message that the model requires a newer CLI means the route is unavailable until
the client/configuration is corrected. Do not reinterpret it as a completed review.

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
