# Abstraction — <component/system> (non-code; review before implementing)

> Language-agnostic. Edit and get this reviewed BEFORE writing code (strict-mode phase 0).
> Tag every behaviour `intended` / `legacy` / `unknown`. Unknowns block implementation.

## Surfaces
What the thing presents / exposes (UIs, APIs, outputs) — no implementation detail.

## Actions
What can be done to it / what it does (commands, operations, triggers).

## State & data
The data it holds and the shape of its state; what is authoritative vs derived.

## Rules
The domain rules / invariants that must always hold. Cite sources where they're external
(specs, regulations). These become property tests + golden replays.

## Edge cases
Boundary conditions, failure modes, concurrency, ordering, time.

## Non-functional
Performance, determinism, security, observability, portability targets.

## Triage
| Behaviour | intended / legacy / unknown | note |
|---|---|---|

## Open questions (blocking)
List unknowns that must be resolved (with a human) before code.
