# OWNERS — approval tiers (strict-mode human gates)

Edit the gated areas + approvers for this project. Nothing self-merges past a gate.

## High-risk → named human sign-off required
Mandatory explicit approval (record approver + date in the ADR):
- Core domain/rules/scoring engine; anything affecting correctness invariants
- Auth / security / secrets / key custody
- Releases, update/rollback, deploy order
- Data/schema migrations; event-schema or wire-format changes
- The "model"/architecture or language choice (ADR phase 2)
- Any claim of production / hardware / external readiness

**Approver(s):** Caullen Omdahl

## Lower-risk behavioral work

May proceed after independent pull-request review of the actual diff and the full completion gate.
Local peer review may prepare a design or be recorded as a fallback, but it is not implementation-review
approval. Any material dissent escalates to the human approver.

## Notes
- Approvals are per-decision and recorded in the ADR `Approver` + `Status` fields.
- When unsure whether something is gated, treat it as gated and ask.
