# Proportionate workflow examples

The [canon](canon.md) defines policy; these examples illustrate its application.

| Trigger | Previous blanket requirement | Intended result |
| --- | --- | --- |
| Correct a small reversible wording error | Prove a mechanical exemption or enter behavioral evidence lanes | Apply the wording and inspect/render the affected output; relevant checks suffice |
| Fix interrupted-download restart behavior | Regression and artifact verification plus full completion/evidence ceremony | Exercise interrupted restart in regression coverage, inspect the resumed output, and obtain one independent final-diff review |
| Close a verified defect while broader exploratory QA is pending | Hold closure for wider optional acceptance | Close the agreed defect after its checks/review; track broader QA separately without claiming it passed |
| Update evidence metadata after a reviewed fix | Bind a fresh snapshot to the latest SHA and potentially restart review | Preserve valid review for unchanged implementation; evidence-only churn adds no review gate |
| Change key custody, migrate production data, publish, or delete irreversibly | Named human gate and verification | Retain scoped human approval and relevant safeguards; previous branch-push approval does not authorize deployment |
| Initialize/update a project's workflow | Add a full-matrix Stop hook in addition to pre-commit/CI checks | Keep relevant pre-commit feedback and real CI; add no Stop hook and remove only the exact known legacy entry on explicit refresh |

A new optional QA result can reveal a real defect. Fix an in-scope defect and verify/review its changed
behavior; do not make every unrelated optional acceptance case mandatory. Additional review is useful
when it answers a distinct unresolved question, rather than reproducing the selected implementation review.

Review means a separately performed examination of the actual diff. A same-family reviewer is eligible;
author self-attestation is not. Different-family review is optional for a concrete risk or owner requirement,
not a prerequisite that blocks otherwise available review. No model is assumed error-free.

This change makes no measured savings or zero-review-value claim. Separate review is useful for substantial or risky
behavior because it can catch real defects; choose it proportionately rather than adding a blanket gate. Historical evidence stays intact.
