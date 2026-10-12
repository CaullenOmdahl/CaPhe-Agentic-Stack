# Documentation

Start with the [project README](../README.md) for the value proposition, quick start, and compatibility.
The [canon](canon.md) is the sole shared workflow policy authority. Guides explain procedures; historical
plans, ADRs, and evidence record the revision they describe and do not add current acceptance gates.

## Start here

| Goal | Read |
| --- | --- |
| Understand how agents should work | [Shared canon](canon.md) |
| See how much process a task needs | [Workflow examples](workflow-examples.md) |
| Adopt the stack on a machine | [Install for agents](install-for-agents.md) |
| Choose components and skills | [Current stack inventory](current-stack-inventory.md) |
| Make a contribution | [Contributor guide](../CONTRIBUTING.md) |

## Operating guides

| Area | Guide |
| --- | --- |
| Runtime commands, prerequisites, installation, and limits | [Efficiency runtime](efficiency-runtime.md) |
| Verification runner and optional hook integration | [Verification runtime overview](../strict-mode/README.md), [procedures](../strict-mode/methodology.md) |
| One separate diff-review route and remediation | [Review workflow](review-workflow.md) |
| Reviewer discovery and provider consent | [Reviewer catalog](reviewer-catalog.md) |
| Private shared memory and optional derived retrieval | [Memory architecture](memory-architecture.md) |
| Capability-gated remote routing proof of concept | [Model routing](model-routing.md) |
| Keeping public source and reports free of private state | [Public safety](public-safety.md) |

The reviewer catalog contains dated vendor observations. Verify current flags, availability, and billing
with the linked primary sources before using a service. Installation and discovery are not completed review.

## Research and decision history

- [External workflow integrations](external-workflow-integrations.md): provenance and adaptation of adopted ideas.
- [External account research](external-account-research.md): a research watchlist, not a maintained compatibility catalog.
- [Efficiency improvement plan](efficiency-improvement-plan.md): dated proposal and measurements;
  implementation status is documented in the runtime guide.
- [Design ADRs](adr/) and [earlier decisions](../.agent/decisions/): historical rationale and scoped acceptance.
- [Orchestration design](superpowers/specs/2026-09-19-model-routing-orchestration-design.md): recorded design proposal.
- [Historical evidence](../.agent/evidence/): immutable records, not certification of the current revision.

Provider pricing, model names, and external projects change. Research dates bound those observations;
they are not promises of current availability or general productivity gains.
