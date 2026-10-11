# OWNERS — strict-mode human gates

Record project-specific approvers. Explicit human acceptance is required for:

- domain correctness invariants;
- auth, security, secrets, or key custody;
- releases, update/rollback, or deploy order;
- data/schema migrations and wire formats;
- architecture, model-policy, language, or platform decisions, including changes to pinned owner or
  reviewer routes;
- production, hardware, financial, legal, payroll, or external-readiness claims;
- irreversible or outward-facing actions.

Use relevant checks and actual-result verification, plus a separate diff review when useful or required.
Prefer remote PR review; successful independent local fallback is sufficient when remote is unavailable.
Do not require both routes; preserve actual repository branch protection requirements.
Nothing self-merges past a named gate.

**Approver(s):** <name>

Harness-managed worker routes come from the reviewed versioned route table. Keep a route disabled until
its provider account, effective model/effort evidence, and filesystem boundary are verified. Explicit
owner route constraints always apply.

Workflow classification and closure follow the shared `docs/canon.md`; this file names project gates.
Routine small reversible changes need implementation and relevant checks. Optional QA does not block
a resolved defect. Existing scoped human authorization satisfies only the decision/action it covers.
