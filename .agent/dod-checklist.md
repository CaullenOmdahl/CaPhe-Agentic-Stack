# Definition of Done — checklist (strict-mode)

A change is **done** only when every box is true:

- [ ] **Abstraction** exists/updated for new behaviour (phase 0), reviewed; no open blockers.
- [ ] **ADR** recorded for any non-trivial/architectural/language decision; status set.
- [ ] **Design review** (adversarial, on the ADR) obtained for ADRs + high-risk; verdict logged.
- [ ] **Implementation review** obtained through a PR before "done" for any change touching
      behaviour/logic (purely mechanical changes — fmt/rename/comment/generated — are
      exempt; **when unsure, review**). **Re-review a behaviour-changing fix** by pushing it
      to the PR and letting review run again; unresolved review deadlock escalates to the
      human approver. **Evidence is the PR URL plus review checks/comments** — not a
      self-written verdict or local `strict-confer` transcript.
- [ ] **Tests first** — a failing test was written and watched fail before the code.
- [ ] **Property tests + golden replays** cover core-logic invariants.
- [ ] **Artifact verified, not just tests** — for model-produced / non-deterministic output,
      the *real artifact* was checked (golden / vision / human) and the pipeline fails fast on
      the first (anchor) output. (Tests + design review cannot prove a generator rendered correctly.)
- [ ] **Formatted** and **lint clean at deny** (no warnings).
- [ ] **All tests pass** (full cross-consumer matrix for core/protocol/rules changes).
- [ ] **Docs / ADR / traceability** updated; public items doc-commented with the *why*.
- [ ] **Human sign-off** recorded for any gated area (`OWNERS.md`).
- [ ] **Provenance** — ADR id cited inline; decision/approver/reviewer in commit metadata.
- [ ] **Completion gate passes** (`~/strict-mode/bin/strict-green-gate.sh --mode completion`
      → `GREEN`; a scoped pre-commit `FAST GREEN` is not completion).
