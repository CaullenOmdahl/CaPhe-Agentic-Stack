# Strict Mode v2

Version-controlled source for the evidence-preserving strict workflow. Install from this repository into
`~/strict-mode`; edit and review this source, not the deployed copy.

Key commands:

```bash
strict-mode/bin/strict-init.sh
strict-mode/bin/strict-green-gate.sh --mode affected
strict-mode/bin/strict-green-gate.sh --mode completion
strict-mode/bin/strict_evidence.py evidence.json --root .
strict-mode/bin/strict-confer.sh codex --adversarial --save design-v1 "Review the ADR"
```

The affected gate optimizes feedback. The completion gate and independent PR review remain authoritative.

`strict-confer` is for design/ADR review or an explicitly recorded fallback when PR review is genuinely
unavailable; it is not normal implementation-review evidence. Its local peer set is Claude Code, agy
(Gemini-family), and Codex. A direct Gemini CLI install is not automatically equivalent to agy. The
wrapper pins reviewer models that may be overridden only after the installed clients verify them.

Confer snapshots exclude ignored local state such as `.env`, but include tracked and non-ignored generated
assets. Snapshot creation can therefore be slow in large repository roots.
