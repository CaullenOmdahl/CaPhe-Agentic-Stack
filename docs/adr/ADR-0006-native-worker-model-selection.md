# ADR 0006 — task-level native worker selection

- **Status:** accepted for implementation; verification and independent PR review required before installation
- **Date:** 2026-09-26
- **Approver:** Caullen Omdahl
- **Authorization:** The owner supplied the report that all subagents used Astra High because the
  installed runtime retained the incumbent until a cheaper route was evaluated and approved, then
  instructed: "We need to fix this behavior."
- **Scope:** Correct native worker selection and its installed instructions. No merge, remote-machine
  rollout, new provider activation, pinned owner-policy replacement, or reviewer-route change is authorized.

## Behavior contract

The coordinator chooses each native worker's supported model and effort before spawning, based on
that worker's bounded acceptance contract and risk. Routine copy/extraction starts lightweight;
settled implementation and error mapping starts on a workhorse; ambiguous or high-risk reasoning can
use a frontier model. User and explicit owner route constraints remain binding. When a preferred route
is unavailable, select an adequate supported alternative and record the reason for that task.

Use explicit model/effort arguments and fresh or bounded context. The coordinator retains integration,
acceptance, and escalation; one failed repair escalates or tightens the contract. Existing completed
work is not restarted to change models. Changes affect future spawns and are reversible by restoring
the instruction payload. Already running tasks may retain earlier instructions until refreshed.

## Decision and alternatives

The incumbent-retention rule governs evaluated policy promotion, not every native worker choice.
Amend ADR-0004's routing interpretation for native delegation only. Keep both existing resolver APIs,
remote pilot admission, capability/isolation requirements, benchmarks, and independent PR review intact.
An actual pinned owner route cannot be bypassed by relabeling a worker as native.

Uniform frontier inheritance wastes resources on bounded tasks. Conversely, routing every task to the
smallest model ignores ambiguity and risk. Use task-level tier defaults and supported effort instead of
hardcoding a vendor model inventory into public policy. No measured savings or quality equivalence is
claimed; those still require paired accepted-task evidence including parent, retry, and child cost.

## Defect detection and verification

The old canon, Strict Mode skill, and methodology all require incumbent retention without distinguishing
native selection from policy promotion. The runtime guide additionally prescribes Astra as coordinator
and couples every selection to the evaluated resolver. This reproduces the owner's reported reasoning.

Inspect the actual instruction artifacts together and check these scenarios: routine copy/extraction,
settled error mapping, ambiguous/high-risk work, an unavailable preferred route, a pinned owner route,
and canonical review. Validate that the first two need no benchmark promotion, while the last two keep
their explicit constraints. Run the complete unchanged verification matrix, including existing resolver
approval, fallback, and reviewer tests. Obtain PR review before installing the changed instruction
payload, preserve local custom instructions, and verify installed bytes with a private rollback journal.
