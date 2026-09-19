# ADR 0005 — remote model routing proof of concept

- **Status:** accepted
- **Date:** 2026-09-19
- **Approver:** Caullen Omdahl, explicit instruction to execute the entire approved plan
- **Deciders / reviewers:** Codex implementation; independent PR review pending

## Context

The stack has a closed delegation contract, route resolver, and benchmark, but no public registry,
capability overlay, safe dispatcher, or telemetry bridge.

## Decision

Use registry-bound remote routing. Terra medium is the hypervisor and incumbent hypothesis; Astra high is
the planner hypothesis. Both require a fresh private capability probe before use. Admit only named low-risk
routes to `pilot` by owner policy; a pilot is not a promotion. Remote dispatch accepts only frozen,
tracked-only public or sanitized source snapshots and fails closed otherwise. Local backends remain deferred.

## Second opinion

The design review required an explicit candidate-to-pilot evidence path, fresh capability gating instead of
assuming every client works, and a hard remote-input egress boundary. These revisions are included here.

## Consequences

Policies, overlays, telemetry, and corpora remain private. The public registry and tools are reviewable.
Unsupported clients remain candidates. Rollback is removing a policy route; no daemon or route is activated.

## Alternatives considered

Hardcoded model strings and automatic route promotion were rejected because they bypass live capability and
owner evidence requirements.
