# Agentic Development Canon

This is the shared operating model for coding agents working in this stack. Agent-specific files should be thin adapters that point back here.

## Prime Directive

Ship software that is correct, working, and verified. Prefer evidence over plausible summaries. For non-trivial work, capture intended behavior before implementation and verify the real artifact before calling the task done.

## Autonomy

Keep going by default when the next step is clear. Do not stop just to ask whether to continue.

Stop for a human only when one of these applies:

- Auth, secrets, releases, deploy order, data migrations, infrastructure rules, money, legal, payroll, or customer-visible risk.
- A real product or architecture fork with materially different outcomes.
- Missing access, credentials, or an action only a human can perform.
- Irreversible or outward-facing actions such as publishing, sending, spending, deleting, force-pushing, or merging.
- Repeated failure after credible alternatives have been tried.

## Scope Triage

- Trivial or mechanical changes: make the change directly.
- Small, low-risk changes: implement with focused verification.
- Non-trivial or behavior-changing work: define intended behavior, write a short plan, then implement with tests and verification.

## Intended Behavior First

Before changing behavior, identify:

- Actor: who triggers the behavior.
- Object: what state or resource changes.
- Trigger: what action starts the flow.
- Current and terminal state.
- Reversibility and recurrence.
- Existing product and codebase patterns.

State the contract in observable terms before coding when the work is non-trivial.

## Tool Selection

Use the developer's existing environment before reaching for auth-dependent integrations.

- Prefer local CLI tools and repository-native commands when they are available: `git`, `gh`, `rg`, language package managers, test runners, build tools, shell scripts, device CLIs, and browser or platform CLIs.
- Check what exists before choosing a tool. A quick `command -v`, version check, repo script inspection, or `git status` is usually better than assuming an MCP or hosted connector is needed.
- Use MCP servers, hosted connectors, browser sessions, or app integrations when they provide unique access, safer structured data, or the user explicitly asks for them. Do not sign in, install, publish, or change external state through those surfaces without the normal human gates.
- Prefer `gh` for GitHub work when it is authenticated and sufficient. Use GitHub MCP or app integrations for data the CLI cannot fetch cleanly, or when the connector is the safer read path.
- Record reusable tool-selection rules in this public canon. Keep private paths, account names, hostnames, tokens, and machine-specific inventories out of the public stack.

## Analysis Artifacts

High-quality code starts with a non-code model of the work.

- For ambiguous product behavior, write the intended behavior contract before implementation.
- For UX or operator workflows, map current and desired flows before naming files.
- For inherited branches, build branch context before editing.
- For implementation choices, prefer small decision notes, flow maps, state contracts, or review findings over premature code changes.
- Keep code human-readable: use domain concepts, clear boundaries, and comments that explain intent, invariants, or tradeoffs. Avoid comments that merely restate syntax.

## Build Process

Use a lightweight strict sequence for non-trivial work:

1. Abstract the goal as a language-agnostic spec.
2. Decide deliberately and record meaningful tradeoffs.
3. Write or update tests before production code where practical.
4. Keep changes scoped and proportional.
5. Run formatting, linting, tests, and artifact verification appropriate to the change.

## Review Rule

Do not treat local self-review as the canonical implementation-review path. Real code changes should go through a pull request with independent review.

Local review tools are useful for preparation and cleanup. They do not replace pull-request review.

## Git Discipline

- Work on a branch.
- Keep commits scoped.
- Do not silently stage unrelated user changes.
- Do not self-merge.
- Preserve a clean distinction between tracked changes, untracked files, staged changes, and unpushed commits.

## Environment Boundaries

Keep environment-specific details out of the canon. Hostnames, private repo names, client operations, credentials, tokens, signing assets, and local cache paths belong in private operator notes, not in this public stack.
