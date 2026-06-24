---
name: intended-behavior
description: Determine intended product behavior before implementation, review, or debugging. Use when an agent must infer what a function, button, state transition, alert, backend feature, UI affordance, or operator workflow should do; when deciding between permanent dismissal, snooze, no-op, deletion, resolution, or recurrence; when a feature was built without an obvious UI path; or when the agent should infer from user role, existing app patterns, comparable software, and UX theory before asking the user.
---

# Intended Behavior

## Purpose

Use this skill to turn ambiguous product behavior into a defensible behavior contract before changing code. Prefer grounded inference when the intended outcome follows from the actor, workflow, labels, existing patterns, and operator goals; ask the user when the inference is not defensible or the cost of being wrong is high.

## Precedence

User instructions and `docs/canon.md` are authoritative.

## Required Output

For non-trivial behavior decisions, state:

- **Intended behavior**: The recommended outcome in one or two sentences.
- **Why**: The actor, object, trigger, persistence model, reversibility, and evidence that make this behavior likely.
- **Contract**: The observable state change, UI affordance, persistence rule, and tests or verification needed.
- **Question**: Only include when a user decision is actually needed; present the best default and the competing choices.

## Workflow

1. **Anchor in evidence**
   - Inspect the request, existing code, tests, docs, issue text, labels, route names, database fields, state machines, and nearby UI.
   - Identify the actor, object, trigger, current state, terminal state, recurrence model, and who benefits from the action.
   - Treat explicit user requirements, reference designs, tests, and current product patterns as stronger evidence than generic UX theory.

2. **Enumerate possible outcomes**
   - Include at least the plausible extremes: do nothing, close the surface only, temporarily hide, permanently dismiss the current item, resolve the underlying issue, delete data, snooze, retry, or escalate.
   - Compare each outcome by operator objective, surprise, reversibility, data integrity, recurrence, implementation risk, and precedent in the app.

3. **Infer the default behavior**
   - Let action labels carry normal product meaning: `dismiss` acknowledges/removes the current alert instance, `snooze` hides temporarily, `resolve` completes the underlying issue, `delete` removes data, and `close` affects only the visible surface unless the app says otherwise.
   - For alert-like operational items, distinguish the alert instance from the source fact. A manager dismissing a late check-in should permanently dismiss that employee-day alert for the manager, while preserving the underlying attendance record and allowing future late events to create new alerts.
   - Treat a backend feature without an operator-accessible UI path as incomplete unless it is explicitly an integration, automation, migration, or admin-only internal tool.
   - Place controls where the operator is already doing the related work: entity actions on entity rows/details, queue actions inside the queue, manager actions in manager surfaces, register actions in the register/payment flow, and configuration in settings.
   - For correctness-sensitive flows, write or update the behavior contract and focused tests before broad implementation.

4. **Ask only when needed**
   - Ask the user when evidence conflicts, the choice affects money/payroll/legal/customer-visible behavior, the action is irreversible, or multiple outcomes are equally defensible for different operators.
   - Ask a compact question with concrete choices and a recommended default, not an open-ended "what should this do?" unless the domain is genuinely unknown.

5. **Implement the full loop**
   - Implement the semantic behavior, persistence, UI affordance, empty/loading/error states, and tests needed for the operator to actually use the feature.
   - Verify the user-visible outcome, not just that backend code exists.
   - Call out any inferred behavior in the final response, especially if no explicit product spec existed.

## Reference

Read `references/behavior-heuristics.md` when action-label semantics, UI placement, recurrence, or ask-vs-infer thresholds are unclear.
