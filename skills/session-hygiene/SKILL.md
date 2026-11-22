---
name: session-hygiene
description: Use when delegating to subagents, managing long multi-step coding sessions, handling context compaction, or watching long-running builds and background jobs.
---

# Session & Delegation Hygiene

Prevent the four main token-burn failure modes: frontier subagent leaks, 400K+ marathon threads, idle polling loops, and unfiltered log dumps.

## 1. Tiered Subagent Delegation
Never let a frontier orchestrator spawn frontier subagents for routine work:
- **Explorer (`haiku` / `luna` / `flash`, read-only):** File discovery, symbol search, doc lookup, log triage. Return file paths, line numbers, and a short summary—not full file dumps.
- **Worker (`sonnet` / `terra`, scoped write):** Well-specified implementation and unit test authoring with explicit file ownership and exact verification commands.
- **Reviewer (`opus` / `astra` / `pro`, read-only):** Architecture decisions, tricky debugging, and final production-risk diff audits.

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
