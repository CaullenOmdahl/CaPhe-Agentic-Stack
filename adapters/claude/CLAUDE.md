# Claude Entry Point

You are Claude, one coding agent using the shared agentic stack.

Before acting, read `../../docs/canon.md` and treat it as binding unless the user gives a more specific instruction.

Claude-specific notes:

- Keep going by default when the next step is clear.
- Use available skills before task execution when they apply.
- For independent review, prefer the pull-request review route described in `../../docs/review-workflow.md`.
- When dispatching subagents under a routing policy, realise routes as described in `ROUTING.md` in this directory: tier via the Agent tool `model` parameter, effort via the dispatched definition's `effort:` frontmatter, service tier always `standard`.
