# OWNERS — strict-mode human gates

Record project-specific approvers. Explicit human acceptance is required for:

- domain correctness invariants;
- auth, security, secrets, or key custody;
- releases, update/rollback, or deploy order;
- data/schema migrations and wire formats;
- architecture, model, language, or platform decisions;
- production, hardware, financial, legal, payroll, or external-readiness claims;
- irreversible or outward-facing actions.

Lower-risk behavioral work may proceed after its independent PR review and full completion gate.
Nothing self-merges past a named gate.

**Approver(s):** <name>
