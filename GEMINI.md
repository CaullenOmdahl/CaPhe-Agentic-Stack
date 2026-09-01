# Gemini / Antigravity Entry Point

You are Gemini or Antigravity, one coding agent using this repository's shared agentic stack.

Read `adapters/gemini/GEMINI.md`, then read `docs/canon.md`.

<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->
## Strict Mode

Use `~/strict-mode/methodology.md` as canon. Classify work from evidence:

- Mechanically proven: byte-identical rename, declared docs, validated generation, or a declared
  semantic-equivalence check.
- Scoped behavior: observable contract, defect-detection evidence, focused checks, PR review, full CI.
- Full risk: abstraction, ADR, adversarial design review, human approval, TDD, PR review, full checks,
  and real-artifact verification.

Named human gates in `.agent/OWNERS.md` never relax. Behavioral diffs require PR review. Pre-commit
`FAST GREEN` is focused feedback only; completion requires
`~/strict-mode/bin/strict-green-gate.sh --mode completion` and PR evidence. Never self-classify an
uncertain change as mechanical. Record compact evidence under `.agent/evidence/`; the traceability index
is generated. Prototype relaxation is per-command and logged. Persistent disable remains user-only.
<!-- STRICT-MODE:END -->
