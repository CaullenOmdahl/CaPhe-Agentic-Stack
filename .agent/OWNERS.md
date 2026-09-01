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

## Lower-risk → tri-AI agreement
May proceed on agreement of the three agents (author + adversarial review by the other
two); any dissent escalates to the human approver:
- Routine ADRs, refactors, tests, docs, dependency bumps

## Notes
- Approvals are per-decision and recorded in the ADR `Approver` + `Status` fields.
- When unsure whether something is gated, treat it as gated and ask.
