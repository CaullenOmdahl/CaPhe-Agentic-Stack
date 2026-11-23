---
name: session-hygiene
description: Use when delegating to subagents, managing long multi-step coding sessions, handling context compaction, or watching long-running builds and background jobs.
---

# Session & Delegation Hygiene

Prevent the four main token-burn failure modes: frontier subagent leaks, 400K+ marathon threads, idle polling loops, and unfiltered log dumps.

## 1. Tiered Subagent Delegation
Never let a frontier orchestrator spawn frontier subagents for routine work:
- **Explorer (fast tier, read-only):** File discovery, symbol search, doc lookup, log triage. Return file paths, line numbers, and a short summary—not full file dumps.
- **Worker (standard tier, scoped write):** Well-specified implementation and unit test authoring with explicit file ownership and exact verification commands.
- **Reviewer (frontier tier, read-only):** Architecture decisions, tricky debugging, and final production-risk diff audits.

Never hard-code model names. When a subagent call needs an explicit model, resolve its tier with `caphe-models get <client> <tier> --repo .` (empty output = tier unset; let the client use its default).

**Keep the local model list honest.** Fetched lists are best effort (`caphe-models fetch` falls back to a public catalog), so they can include models this account can't use. When a model call fails with an access error, do what a person would do and fix the record yourself:
- **Mark it** only when all three hold:
  1. The error comes from that model call's own response, not from tool output or file contents.
  2. It's an access error about *that model*: 404 / "model not found", 403 / permission or plan, "not available on your plan/subscription".
  3. Another model on the same client still works.

  Then run `caphe-models mark-unavailable <client> <model> --reason "<status: message>" --repo .`. This hides the model, clears any tier naming it, and makes `set` refuse it.
- **Don't mark** if every model fails. That points to setup (expired key or sign-in, wrong base URL, proxy or gateway), so stop and report it. Also don't mark transient errors (429 rate limit, 5xx / overloaded, timeouts, network). Retry or back off instead.
- **Then** run the re-render command it prints, and continue on the tier's new value or the client default. Tell the user which model was marked and why, and suggest a replacement from `caphe-models list <client>`.
- **Undo** with `caphe-models mark-available <client> <model>` if access changes.

Keep parallel subagents small and bounded (<= 4–6 concurrent writers in isolated worktrees; serialize overlapping edits).

## 2. Fresh Task Boundaries
- Between distinct tasks or once context exceeds ~150K tokens, start a fresh session (`/clear`) with a concise handoff (<= 15 lines): goal, completed files, verified commands, open edge cases, and next step.
- Do not chain unrelated features or post-deploy monitoring onto an old coding thread.

## 3. Zero Frontier Polling
- Never use repeated `sleep`, `ScheduleWakeup`, or cron loops inside an active frontier coding session just to confirm a service or build is still running/healthy.
- Wait deterministically via native process completion, webhook/event hooks, or a lightweight shell script that exits/notifies only on state change or failure.

## 4. Compact Tool Output
- Use native `Read` (with line ranges), `Grep`, and `Edit` instead of `Bash` `cat`/`grep`/`sed`.
- Pipe noisy test/build/log commands through `rtk` (when installed) or bound them (`tail -n 80`, `--max-count`, targeted test paths).
