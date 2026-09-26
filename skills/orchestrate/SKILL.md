---
name: orchestrate
description: Safely resolve and dispatch bounded remote-model work using the CaPhe registry and owner policy.
---

# Orchestrate

This skill governs registry-based remote dispatch. Native harness workers follow the task-level model
and effort selection in Strict Mode; they do not need a remote pilot or benchmark promotion merely to
avoid inheriting the coordinator's model. Explicit owner route constraints still apply in either path.

Use only a validated v2 route, a private capability overlay from a fresh probe, and an owner policy.
Do not route `candidate`, deprecated, retired, unprobed, or isolation-unverified models. Classify first,
enforce the task class lane ceiling, and give each worker a fresh bounded contract. At most 64 workers or the active agent environment limit, whichever is lower;
one repair only. Canonical PR review remains on its dedicated route.

For remote work, create a frozen tracked-only source snapshot and a manifest declaring `public` or
`sanitized`. Reject unknown, secret-bearing, ignored, or untracked input before calling a remote client.
Never copy transcripts, local configuration, or credentials into a worker context. Run the dispatcher dry
run first; `--execute` is an explicit operator action after the capability probe has recorded compatible
model, effort, service tier, authentication, and isolation support.

Inspect bounded worker evidence; never accept unsupported success claims. Emit one private benchmark event
per request, count repair and parent work, then use the ordinary PR implementation-review workflow.

Determine available worker slots from the active environment before delegation. If its limit counts all
agents, subtract the coordinator and any other occupied slots. Set the contract's `max_workers` no higher
than `min(64, available slots)` and pass the observed capacity as `capabilities.available_worker_slots`
to `stack_route.py`. Refresh capacity before each spawn; this validator does not reserve slots or enforce
a global process count. When capacity is not exposed, the ceiling is 64 and the host's admission limits
still apply. Existing callers may omit the capacity field; that does not override known host limits.
