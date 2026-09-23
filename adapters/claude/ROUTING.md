# Claude Code route realisation

This file states how a Claude Code session realises a route from the routing policy. It is the
client-side half of `docs/model-routing.md`; the registry says what a model is, this says how a
Claude Code session actually dispatches it. The session is the authority on its own levers and does
not need to look them up: they are the parameters of its Agent tool and the frontmatter of the agent
definitions it can dispatch.

## The route and the levers

A policy route is `{config, model, effort, service_tier}`. Claude Code realises each field as
follows.

| Route field    | Lever                                                    | Set per dispatch? |
| -------------- | -------------------------------------------------------- | ----------------- |
| `model`        | Agent tool `model` parameter: `fable`, `opus`, `sonnet`, `haiku`, or a full model ID | yes |
| `effort`       | `effort:` in the dispatched definition's frontmatter: `low`, `medium`, `high`, `xhigh`, `max` | **no** — bound to the definition |
| `service_tier` | none; fast mode is a session-level toggle, not a dispatch parameter | no — always `standard` |
| domain         | Agent tool `subagent_type`: which definition runs        | yes |
| isolation      | Agent tool `isolation: worktree`                         | yes |

The per-dispatch `model` parameter overrides the definition's `model:` frontmatter. A definition that
pins `model:` is therefore not a route by itself; the dispatcher must always pass `model` so the tier
is chosen per task, not inherited from the file.

Registry key to alias: `claude-fable` → `fable`, `claude-opus` → `opus`, `claude-sonnet` → `sonnet`,
`claude-haiku` → `haiku`. Alias resolution to a concrete model ID differs by provider (first-party
API, Bedrock, Vertex, Foundry). The private capability overlay for a host records which concrete ID
each alias resolved to on that host and when it was probed; a registry `vendor_model` that differs
from the observed resolution makes the route `unsupported` on that host.

## Effort is the definition

Because effort cannot be set per dispatch, the definition is the effort knob. The consequences are
mechanical:

- Every definition the dispatcher may route to declares `effort:`. A definition without it runs at an
  inherited default, which the evidence must record as `inherited-default`, never as the route's
  declared effort.
- One definition serves one effort. When the same domain is needed at two efforts — for instance a
  strong-tier route at `high` and a standard-tier route at `medium` — there are two definitions,
  named for the role they play, not for the effort number. The role distinction is usually real:
  a bounded implementer working against a frozen contract is a different job from an owner of
  difficult integration.
- Built-in agents (`Plan`, `Explore`, `general-purpose`) cannot carry `effort:`. They are dispatchable
  at any tier but their effort is inherited. Route them only where the class tolerates inherited
  effort — lookup and mechanical work on the light tier, which has no effort parameter at all — or
  where the inherited default equals the route's declared effort and that equality is recorded.
- The light tier (`claude-haiku`) accepts no effort parameter. Its registry `efforts` is `["none"]`,
  and a route to it declares effort `none`. This is not a gap; it is the model's contract.

## Service tier is always standard

Fast mode exists in Claude Code but is toggled for the whole session and inherited by every subagent
it spawns. It is not a per-route lever and a route must not depend on it. Every Claude Code route
declares `service_tier: standard`, and the capability overlay lists `service_tiers: ["standard"]`
for every Claude model. Priority tier is not exposed to Claude Code dispatch at all.

## What a valid dispatch looks like

For a route `{model: claude-opus, effort: high, service_tier: standard}` serving
`difficult-implementation`:

1. Select a definition whose frontmatter declares `effort: high` and whose role fits the task.
2. Call the Agent tool with `subagent_type` = that definition and `model: opus`.
3. Record in the task evidence: the registry key, the alias passed, the definition name, the effort
   the definition declares, `service_tier: standard`, and the concrete model ID the overlay says the
   alias resolved to on this host.

If no definition at the required effort exists for the domain, the route is unrealisable on this
host until one is added. The dispatcher does not substitute a nearby effort silently; an
over-provisioned effort may be used only when recorded as such, and an under-provisioned one never.

## What this file does not do

It does not name any project's agent definitions, task tables or hosts; those belong in the
consuming project. It does not promote any Claude model's registry status; that still requires
paired accepted-task evidence and an owner-policy change. It does not change the delegation
contract, lane ceilings, file leases, repair budget or the single independent review route, all of
which apply unchanged to Claude Code dispatch.
