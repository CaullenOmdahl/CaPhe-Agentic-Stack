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
| `effort`       | Native Agent tool: `effort:` in the definition frontmatter. Remote CLI: `--effort` flag. | Native: **no**, bound to definition. CLI: yes. |
| `service_tier` | none; fast mode is a session-level toggle, not a dispatch parameter | no — always `standard` |
| domain         | Agent tool `subagent_type`: which definition runs        | yes |
| isolation      | Agent tool `isolation: worktree`                         | yes |

The per-dispatch `model` parameter overrides the definition's `model:` frontmatter. A definition that
pins `model:` is therefore not a route by itself; the dispatcher must always pass `model` so the tier
is chosen per task, not inherited from the file.

Registry key to alias: `claude-fable` → `fable`, `claude-opus` → `opus`, `claude-sonnet` → `sonnet`,
`claude-haiku` → `haiku`. Alias resolution to a concrete model ID differs by provider (first-party
API, Bedrock, Vertex, Foundry). Before marking a Claude route available for dispatch, observe the
concrete model ID from an authenticated invocation using that alias, then pass that observation to
`tools/stack_probe_models.py` with `--resolved-model claude-opus=<observed-id>` (once per Claude
registry key). The private overlay records the supplied observation alongside its probe timestamp.
The probe does not itself send a model request or infer an ID from the alias. A missing observation,
or one that differs from the registry `vendor_model`, makes that Claude route unsupported on the
host; refresh it after changing the client or provider configuration.

## Effort is the definition

For native Agent tool dispatch, effort cannot be set per call, so the definition is the effort knob.
The consequences are mechanical:

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
it spawns. It is not a per-route lever and a route must not depend on it. Before native Agent tool
dispatch, verify that fast mode is off in the coordinating session. If it is on or its state cannot
be verified, Claude routes declaring `service_tier: standard` are unavailable for that session.
Every Claude Code route declares `service_tier: standard`, and the capability overlay lists
`service_tiers: ["standard"]` for every Claude model. Priority tier is not exposed to Claude Code
dispatch at all.

## What a valid dispatch looks like

For a route `{model: claude-opus, effort: high, service_tier: standard}` serving
`difficult-implementation`:

1. Select a definition whose frontmatter declares `effort: high` and whose role fits the task.
2. Verify fast mode is off, then call the Agent tool with `subagent_type` = that definition and
   `model: opus`.
3. Record in the task evidence: the registry key, the alias passed, the definition name, the effort
   the definition declares, `service_tier: standard`, and the concrete model ID the overlay says the
   alias resolved to on this host.

If no definition at the required effort exists for the domain, the route is unrealisable on this
host until one is added. The dispatcher does not substitute a nearby effort silently; an
over-provisioned effort may be used only when recorded as such, and an under-provisioned one never.
The remote `claude` CLI dispatcher sets both `--model` and `--effort`; if the installed client does
not support those values, execution fails and the route is unavailable.

## What this file does not do

It does not name any project's agent definitions, task tables or hosts; those belong in the
consuming project. It does not promote any Claude model's registry status; that still requires
paired accepted-task evidence and an owner-policy change. It does not change the delegation
contract, lane ceilings, file leases, repair budget or the single independent review route, all of
which apply unchanged to Claude Code dispatch.
