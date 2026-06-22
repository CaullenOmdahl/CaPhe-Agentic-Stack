---
name: ux-flow-plan
description: Create UX-first plans for product or interface changes by mapping current and desired flows before implementation anchors. Use when planning non-trivial UX, product behavior, screen flows, operator workflows, or UI architecture changes.
---

# UX Flow Plan

Start from user experience and system behavior before naming implementation files.

## Precedence

User instructions and `docs/canon.md` are authoritative.

Use this before implementation planning. If code changes are required after the flow is clear, hand off to the stack's normal implementation-plan workflow.

## Workflow

1. Restate the feature goal in product terms.
2. Map the current flow as a tree:

```text
User action
└─ System behavior
   └─ Existing architecture layer
      └─ Function or file anchor
```

3. Map the desired flow as a tree:

```text
User action
└─ System behavior
   └─ New or changed architecture layer
      └─ Function or file anchor
```

4. Identify boundary decisions:

- which layer detects the condition,
- which layer owns side effects,
- which layer updates user-visible status,
- which layer persists or mutates state,
- what is coupled to an existing product concept,
- what is intentionally independent.

5. Add implementation anchors only after the flow is clear:

- likely files,
- functions or components,
- existing abstractions to reuse,
- tests or artifact checks.

6. End with decisions:

- recommended architecture,
- alternatives rejected,
- assumptions or open questions,
- human-gated risks.

## Rules

- Keep current flow separate from desired flow.
- Do not start with line-level code edits.
- Use product language until the architectural boundary is clear.
- Human-gate auth, secrets, releases, data migrations, money, legal, payroll, customer-visible behavior, and irreversible operations.
