---
name: strict-mode
description: Govern non-trivial or high-risk repository work with evidence-preserving lanes, human gates, test evidence, PR review, and full completion verification. Use when the user says strict mode or when a repository declares it.
---

# Strict Mode

Read `~/strict-mode/methodology.md`. Check `.agent/.strict-version`; run
`~/strict-mode/bin/strict-init.sh` only when scaffolding is absent or the installed version changed.

Classify from deterministic evidence:

- mechanically proven;
- scoped behavior;
- full risk.

Never self-attest a mechanical exemption. Pause at `.agent/OWNERS.md` gates. Use failing regression or
equivalent defect-detection evidence before production behavior changes. Implementation review is the PR
on the actual diff; local peer review is design help or a recorded fallback.

Pre-commit `FAST GREEN` is focused feedback only. Before completion, run
`~/strict-mode/bin/strict-green-gate.sh --mode completion`, verify the real artifact when tests cannot,
and write compact `.agent/evidence/` provenance with the PR evidence.
