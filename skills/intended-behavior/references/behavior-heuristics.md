# Behavior Heuristics

## Evidence Strength

Prefer stronger evidence first:

1. Explicit user instruction, acceptance criteria, tests, reference design, or product spec.
2. Existing behavior in the same app, especially nearby screens or the same role/workflow.
3. Domain convention from comparable software used for the same job.
4. General UX theory and label semantics.
5. Pure intuition. Treat this as weak; ask if the decision matters.

## Common Action Semantics

| Label | Default intended behavior | Ask when |
| --- | --- | --- |
| Dismiss / Acknowledge | Remove the current alert or notification instance from the active queue after the operator has seen it. Preserve the source record. | It might hide a recurring safety, payroll, or compliance issue. |
| Snooze / Remind later | Hide temporarily, then reappear after time or condition. | No duration or recurrence trigger is implied. |
| Resolve / Complete | Mark the underlying issue or task complete. | Completion criteria are unclear or affect another team. |
| Delete / Remove | Destructively remove data or detach an item. | Data may need audit history, soft delete, or undo. |
| Archive | Remove from active/default view while preserving retrieval. | Archive is being used as a substitute for delete or resolve. |
| Close | Close the panel/modal/screen only. Do not persist workflow state unless stated. | Close appears on an entity whose lifecycle may also change. |
| Cancel | Abort an in-progress operation or scheduled item. | The item may already have downstream effects such as payment, payroll, or orders. |
| Approve / Reject | Persist an explicit business decision with actor and timestamp. | The approval authority or review criteria are unclear. |
| Save | Persist current edits or draft state. | It is unclear whether save publishes, submits, or only drafts. |

## Operator Outcome Rubric

Before choosing behavior, answer:

- What job is the operator trying to finish right now?
- What object do they believe they are acting on: a notification, source record, task, payment, shift, order, or configuration?
- Is the condition historical, still active, or likely to recur independently?
- Would the operator be surprised if the item returned later?
- Would the operator be harmed if it never returned?
- Does the action need auditability, undo, confirmation, or attribution?
- Is the action personal to one user, shared across a team, or global?

## UI Placement Defaults

- Put row-specific actions on the row or detail page for that entity.
- Put queue actions inside the queue item or queue toolbar.
- Put manager-only controls in manager surfaces, not hidden behind developer/admin-only paths.
- Put register/order actions in the active register, ticket, or payment workflow.
- Put notification preferences in settings; put notification resolution on the notification itself.
- If a reference design or comparable product clearly defines the surface, use that as the target unless current app constraints make it impossible.
- If backend support exists but no user can discover or operate it, add the smallest coherent UI entry point that completes the workflow.

## Ask-Versus-Infer Thresholds

Infer when:

- Label semantics, workflow context, and existing app patterns all point to the same outcome.
- The wrong choice is reversible and easy to change.
- The feature is routine and comparable apps behave consistently.

Ask when:

- Two or more outcomes are equally plausible for different business goals.
- The action affects money, payroll, legal/compliance state, customer communication, security, access control, or irreversible data loss.
- Existing code and UI disagree about the state model.
- The product has no precedent and comparable software does not give a strong pattern.

When asking, present:

```text
I can infer X because Y. The other plausible choices are A and B. Should I proceed with X?
```

## Examples

- **Late check-in alert with Dismiss**: Permanently dismiss the current employee-day alert after manager acknowledgement. Do not delete or alter the attendance record. Do not show the same alert again after an arbitrary timer. A future late check-in can create a new alert.
- **Export engine built without UI**: Treat the feature as incomplete for operators. Add an export control to the natural manager/reporting surface, with loading, error, and success states.
- **Close button on modal**: Close only the modal unless the surrounding copy says the action is completing or saving work.
- **Dangerous cleanup action**: Ask or add confirmation when the action could delete operational records, affect payroll, or remove audit history.
