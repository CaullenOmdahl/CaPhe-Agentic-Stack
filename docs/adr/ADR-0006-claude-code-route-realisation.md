# ADR 0006 — Claude client registry entries and Claude Code route realisation

- **Status:** accepted
- **Date:** 2026-09-23
- **Approver:** Caullen Omdahl, explicit instruction to remap routing onto the agents Claude Code can dispatch and add the result to the stack
- **Deciders / reviewers:** Claude Code implementation; independent PR review pending

## Context

ADR-0005 established a registry-bound router with Codex-client routes as the incumbent and planner
hypotheses, and a single Claude entry (`claude-sonnet`) recorded as `strong` tier with a stale alias
`vendor_model` and a 200k context window.

A Claude Code session executing a plan written for Codex routes cannot dispatch those routes. The
first attempt to remap them substituted domain specialisations for tiers, which is not equivalence:
a specialisation carries no capability tier and no reasoning effort. The second attempt mapped tiers
correctly but against a model lineup three months stale.

## Decision

Register the current Claude lineup as four client routes with a one-to-one tier mapping, verified
against the vendor's live model and pricing pages on 2026-09-23:

| Registry key    | Tier     | Concrete model              | Effort parameter |
| --------------- | -------- | --------------------------- | ---------------- |
| `claude-fable`  | frontier | `claude-fable-5-1`          | low–max          |
| `claude-opus`   | strong   | `claude-opus-5-5`           | low–max, default medium |
| `claude-sonnet` | standard | `claude-sonnet-5`           | low–max          |
| `claude-haiku`  | light    | `claude-haiku-4-5-20251001` | none             |

`claude-sonnet` is re-tiered from `strong` to `standard`, its `vendor_model` pinned, and its
context window corrected. All four remain `candidate`; this ADR registers them, it does not promote
them.

Add `adapters/claude/ROUTING.md`, which states how a Claude Code session realises a route: tier via
the Agent tool's per-dispatch `model` parameter, effort via the dispatched definition's `effort:`
frontmatter, service tier always `standard`. The definition is the effort lever because Claude Code
exposes no per-dispatch effort; one definition therefore serves one effort, and a domain needed at two
efforts has two definitions.

Extend `docs/model-routing.md` with a client-availability substitution rule: substitution is never
silent, is drawn on tier, effort and class rather than persona, requires both axes to be actually
settable, and leaves lane ceilings, leases, repair budget and the review route unchanged.

## Second opinion

The owner's review of the first two attempts required equivalence on tier and effort rather than on
role, current rather than cached model data, and a specification the executing client can act on
from its own levers without lookup. These revisions are included here.

## Consequences

A Claude Code host can now express a valid route for every task class the registry carries, and the
router can reject a dispatch whose definition lacks a declared effort or whose alias resolves to a
model other than the registered one. Built-in agents without frontmatter remain usable only where the
class tolerates inherited effort. The light tier carries the lineup's earliest retirement date and
needs a recorded successor before it.

Rollback is removing the four entries and the adapter file; no policy route is activated by this ADR.

## Alternatives considered

Mapping routes to named domain agents was rejected because it is not equivalence. Leaving effort
inherited was rejected because canon requires model and effort resolved explicitly. Creating one
definition per (domain × effort) pair everywhere was rejected in favour of adding variants only
where a route actually needs a second effort.
