# OWNERS — approval tiers (strict-mode human gates)

Edit the gated areas + approvers for this project. Nothing self-merges past a gate.

## High-risk → named human sign-off required
Scoped human approval required (record the decision, approver, and scope in the PR or an ADR):
- Core domain/rules/scoring engine; anything affecting correctness invariants
- Auth / security / secrets / key custody
- Releases, update/rollback, deploy order
- Data/schema migrations; event-schema or wire-format changes
- Architecture, language, or model-policy choices, including changes to pinned owner or
  reviewer routes. Routine native worker model/effort selection under the approved delegation rules is
  already authorized and does not require a new per-worker approval.
- Any claim of production / hardware / external readiness

**Approver(s):** Caullen Omdahl

## Lower-risk behavioral work

Use relevant checks and actual-result verification; a separate diff review helps substantial or risky
changes. Follow the canon and actual repository requirements.
Prefer remote PR review; independent local fallback is sufficient when remote is unavailable.
Do not require both routes. Preserve branch protections; material dissent escalates to the human approver.

## Notes
- Approvals are per-decision; reuse existing scoped authorization and record any remaining approval.
- Clarify uncertainty about a consequential human gate; routine reversible edits follow the canon.

Workflow classification and closure follow the shared `docs/canon.md`; this file names project gates.
Routine small reversible changes need implementation and relevant checks. Optional QA does not block
a resolved defect. Existing scoped human authorization satisfies only the decision/action it covers.
