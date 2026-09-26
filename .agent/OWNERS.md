# OWNERS — approval tiers (strict-mode human gates)

Edit the gated areas + approvers for this project. Nothing self-merges past a gate.

## High-risk → named human sign-off required
Mandatory explicit approval (record approver + date in the ADR):
- Core domain/rules/scoring engine; anything affecting correctness invariants
- Auth / security / secrets / key custody
- Releases, update/rollback, deploy order
- Data/schema migrations; event-schema or wire-format changes
- Architecture, language, or model-policy choices (ADR phase 2), including changes to pinned owner or
  reviewer routes. Routine native worker model/effort selection under the approved delegation rules is
  already authorized and does not require a new per-worker approval.
- Any claim of production / hardware / external readiness

**Approver(s):** Caullen Omdahl

## Lower-risk behavioral work

May proceed after one independent implementation review of the actual diff and the full completion gate.
Prefer remote PR review; independent local fallback is sufficient when remote is unavailable.
Do not require both routes. Preserve branch protections; material dissent escalates to the human approver.

## Notes
- Approvals are per-decision and recorded in the ADR `Approver` + `Status` fields.
- When unsure whether something is gated, treat it as gated and ask.
