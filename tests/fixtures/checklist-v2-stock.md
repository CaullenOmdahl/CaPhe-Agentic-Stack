# Definition of Done — strict-mode

- [ ] Evidence lane is mechanically proven, scoped behavior, or full risk.
- [ ] Observable behavior contract/abstraction exists where required; no blocking unknowns.
- [ ] ADR and adversarial design review exist for non-trivial decisions.
- [ ] Defect-detection evidence proves tests/checks can catch the problem.
- [ ] Behavioral implementation diff has independent PR review evidence.
- [ ] Formatting, lint, tests, docs, and real-artifact verification are green for the affected surface.
- [ ] Full declared matrix passed in authoritative CI, or locally uncached when CI is absent/incomplete.
- [ ] Named human approval is recorded for every gated area.
- [ ] Per-change evidence and generated traceability index are current.
- [ ] `~/strict-mode/bin/strict-green-gate.sh --mode completion` returns `GREEN`.

A pre-commit `FAST GREEN` is useful feedback but is never completion.
