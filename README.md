# CaPhe Agentic Stack

Public-safe, agent-agnostic development workflow canon.

This repository anchors a shared development methodology that can be used by multiple coding agents without tying the workflow to one vendor or local machine.

The stack is intentionally split into:

- `docs/canon.md`: shared operating rules every agent should follow.
- `adapters/`: thin agent-specific entrypoints that point back to the canon.
- `docs/review-workflow.md`: the peer-review and pull-request route.
- `docs/current-stack-inventory.md`: public-safe inventory of the current setup shape.
- `docs/public-safety.md`: rules for what must not be committed here.

Private project skills, credentials, local caches, machine hostnames, and client-specific release procedures are intentionally excluded.
