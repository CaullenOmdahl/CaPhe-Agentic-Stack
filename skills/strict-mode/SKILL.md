---
name: strict-mode
description: Read the shared development guidance and select relevant verification tools without adding acceptance gates.
---

# Development and verification

The shared `docs/canon.md` in the source checkout or installed runtime is the workflow authority.
Apply judgment: implement a coherent change, run relevant checks, inspect the actual result, and add
regression coverage where it protects behavior. A short plan or separate diff review helps substantial
or risky work; neither calls for an elaborate framework. A separately performed same-family review is
allowed. Different-family review is optional for concrete risk, conflicting evidence, or an owner rule.

Use `strict-mode/methodology.md` for runner commands only when helpful. It adds no acceptance gates.
Optional QA does not hold a resolved defect open. Extra tests/reviews need a distinct reason. Preserve
real GitHub requirements and safeguards for secrets, destructive actions, releases, private memory,
and permission isolation. Reuse existing scoped authorization and valid results for unchanged material.

Do not initialize/update an installed workflow just because this skill or repository declares it.
Only perform an authorized installation/refresh, preserve custom hooks/instructions/dirty work and
explicit disable, and inspect actual installed artifacts. Installer tests use temporary task-specific
HOME and XDG directories and disposable targets, never the executing agent's real HOME.
This stack is a product to evaluate; its refactors do not need to bootstrap its own review/runtime rules.
