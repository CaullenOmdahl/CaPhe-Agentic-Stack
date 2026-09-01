# Review Workflow

This stack treats pull requests as the canonical implementation-review path.

## Default Route

1. Start from the real local repository state.
2. Create or switch to a scoped branch.
3. Inspect the diff before staging.
4. Commit only intended files.
5. Run relevant verification.
6. Push the branch.
7. Open a pull request.
8. Request or trigger independent agent review where available.
9. Address actionable findings in follow-up commits.
10. Leave merge approval to a human maintainer.

## Review Agents

When a repository is connected to review agents, discover which integrations are currently active from
recent workflow runs, checks, and review responses, then use that repository's normal pull-request path.
Do not hard-code or wait on a retired or unresponsive reviewer. Record the reviewers that actually ran.

Do not claim review is complete unless the relevant review path actually ran or the user explicitly accepted a fallback.

## Local Review

Local review prompts and skills are preparation aids. They are useful for catching issues before PR review, especially:

- reuse of existing code,
- consistency with local patterns,
- composition and boundaries,
- unnecessary helper or type extraction,
- redundant effects, memoization, or callback plumbing,
- scope and diff churn.

Local review does not replace independent PR review.
