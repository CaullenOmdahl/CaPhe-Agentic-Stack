---
name: strict-mode
description: Govern non-trivial or high-risk repository work with evidence-preserving lanes, human gates, test evidence, PR review, and full completion verification. Use when the user says strict mode or when a repository declares it.
---

# Strict Mode

Read `~/strict-mode/methodology.md`. Check `.agent/.strict-version`; run
`~/strict-mode/bin/strict-init.sh` only when scaffolding is absent, its version changed, or the effective
hook/source probe shows drift. A version marker alone does not prove activation. Preserve custom hooks,
project instructions, dirty work, and explicit user disable.

Classify from deterministic evidence:

- mechanically proven;
- scoped behavior;
- full risk.

Never self-attest a mechanical exemption. Pause at `.agent/OWNERS.md` gates. Use failing regression or
equivalent defect-detection evidence before production behavior changes. Implementation review is the PR
on the actual diff; local peer review is design help or a recorded fallback.

Pre-commit `FAST GREEN` is focused feedback only. Before completion, run
`~/strict-mode/bin/strict-green-gate.sh --mode completion`, verify the real artifact when tests cannot,
and write immutable v2 `.agent/evidence/` snapshots with the PR evidence. Keep continuation and scoped
authorization private outside Git. Use the installed runtime tools for bounded context, declared
preparation, status polling, and explicit model/effort routing; read `docs/efficiency-runtime.md` in that
runtime only when those operations are needed. Retain the incumbent until paired workflow evidence
qualifies a cheaper route, and include parent, retry, and child cost in the comparison.
