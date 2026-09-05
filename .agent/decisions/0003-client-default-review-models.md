# ADR-0003: Resolve live review-grade models for local reviewers

- **Status:** Accepted
- **Date:** 2026-09-05
- **Decision owner:** Caullen Omdahl
- **Evidence lane:** Full risk (reviewer/model selection)

## Context

The local review wrappers and two separately installed skills pinned Codex `gpt-5.4`. Codex CLI later
rejected that model for ChatGPT accounts, while an older Mac CLI also rejected its newer configured
default. The separate second-opinion skill still routed Gemini-family work through a direct Gemini CLI
that Google now rejects, and neither review skill was present in the stack distribution or on Fedora.

## Decision

Local reviewer wrappers resolve an auditable review-grade model from a private per-machine configuration.
The public stack enforces capability tiers but neither floats to the newest inventory entry nor embeds a
machine-specific version pin. Codex rejects missing, unknown, or lightweight configured tiers; agy requires
a Gemini Pro High model; Claude requires Sonnet or Opus. A caller override remains available only after it
was live-verified with that client. Gemini-family fallback uses agy, not direct Gemini CLI.

Reviewer availability is machine-local and requires a successful exit, non-empty review output, and
recorded executable version and resolved model. Version/model discovery and inference stay inside the same
default-deny filesystem boundary. The boundary permits network access but withholds host auth files and
token caches; a client unable to authenticate without them is unavailable rather than silently widened.
Strict gate child checks also discard the calling hook's Git repository-location variables so nested
repository tests resolve their own index, while the gate itself still plans against the real staged index.

The generic `second-opinion` and `codex-review` skills become CaPhe distribution sources and are installed
from there on both machines. None of these local routes replaces pull-request implementation review.

## Alternatives

- **Pin the newest observed model:** rejected because compatibility changes independently across clients
  and machines.
- **Maintain per-machine model pins in the public repository:** rejected because it leaks runtime detail
  into distribution policy and still drifts.
- **Remove local review tooling:** rejected because it remains useful for design and explicit fallback
  preparation.

## Consequences

- Client upgrades and authentication failures remain visible instead of being misdiagnosed as reviewer
  findings.
- Reproducibility comes from a deliberately updated private model pin plus recorded executable, version,
  resolved model, and probe evidence rather than a floating or stale public pin.
- Optional overrides remain possible but require a current compatibility probe.
- `strict-confer` can remain unavailable for clients that require disk OAuth state. This is the deliberate
  ADR-0001 credential-isolation tradeoff, not permission to copy auth state or weaken the boundary. Direct
  local second-opinion tools may use their normal host authentication under their own plan/read-only
  controls, but they still do not replace canonical GitHub pull-request review.

## Adversarial design review

- Round 1 rejected unconstrained client defaults because liveness did not prove review quality.
- Round 2 rejected floating to the newest provider model and probes outside the isolation boundary.
- The design was revised to deliberate private exact pins, capability tiers, recorded model/version, and
  sandboxed discovery.
- The final dissent argued that withholding disk OAuth can make strict-confer unavailable. That is an
  intentional existing ADR-0001 security boundary; the objection is retained as a known limitation rather
  than resolved by exposing credentials. PR review remains the normal path.

## Approval

Caullen Omdahl requested cross-machine and Codex-skill parity for the two CaPhe review changes on
2026-09-05.
