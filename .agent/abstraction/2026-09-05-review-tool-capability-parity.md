# Review Tool Capability Parity

## Goal

Keep local review preparation usable without letting stale model pins or assumed clients change the
canonical pull-request review rule.

## Observable contract

- Pull-request review remains the implementation-review gate.
- A local reviewer is available only after its executable and authenticated headless invocation succeed
  on the current machine.
- `strict-confer`, `second-opinion`, and `codex-review` resolve and record a review-grade model from a
  private per-machine configuration. Public source contains capability rules, not a floating or stale
  version pin. A caller override is accepted only after verification with that same client.
- Direct Gemini CLI is not a default route. The supported Gemini-family route is `agy` when its live
  probe succeeds.
- One machine's reviewer inventory does not imply another machine has the same authenticated clients.
- The source repository distributes every generic skill needed to apply this rule; selected machine
  installs are copied from that source and verified for parity.

## Current evidence

- Mac Codex CLI 0.142.5 rejected both the former `gpt-5.4` pin and its configured `gpt-5.6-terra`;
  upgrading to 0.153.4 restored the configured-default route.
- Mac headless probes currently pass for Claude Code, agy, and Codex. Direct Gemini rejects the installed
  individual client as unsupported.
- Fedora headless probes currently pass for agy and Codex. Claude authentication is expired and direct
  Gemini is absent.

## Edge cases

- An installed executable with expired authentication is unavailable.
- Connectivity and non-empty output are insufficient when the resolved model is missing, unknown, or a
  lightweight tier.
- Inventory/version probes and inference run inside the same default-deny filesystem boundary. Network is
  allowed, but host auth files and token caches are not; inability to authenticate there means unavailable.
- A model visible in documentation or another client is not proven compatible with the active client.
- Empty reviewer output is failure, not approval.
- A local fallback may be recorded as preparation evidence but never relabeled independent PR approval.
