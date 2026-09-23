# Model routing proof of concept

The proof of concept routes only remote models. `registry/models.json` is public catalog metadata; an
owner-only overlay records a machine's actual authenticated capabilities. A policy is also owner-only.
Neither a catalog entry nor an installed executable makes a model routable.

Remote dispatch is fail-closed. Create the input with `tools/stack_freeze_snapshot.py`; it uses `git archive`
to make a frozen, tracked-only snapshot explicitly marked
`public` or `sanitized`; ignored files, untracked files, secrets, and unknown classification are rejected.
The dispatcher defaults to dry-run. It records one private benchmark event per real request and does not
change policies. Direct Gemini CLI is a candidate only until a fresh authenticated isolation probe succeeds.

Use `tools/stack_probe_models.py` to create a private baseline overlay, then record successful authenticated
and isolated capability observations before changing any model to `pilot`. Use `tools/stack_route_review.py`
only to report recommendations. Owner decisions belong in an ADR and an owner-policy PR.

## Client-availability route substitution

A routing policy names routes, and every route belongs to a client. A session can only dispatch
routes whose client it is itself running under. When a plan names routes belonging to a client the
executing session cannot dispatch, that is an availability problem, not a licence to pick
substitute models.

Substitution is never silent. The session must hold, state which named routes are undispatchable
and why, and obtain an owner decision before dispatching. The owner may instead move execution to a
host running the required client, which keeps the original routes intact.

### Equivalence is drawn on tier, effort and class

A route is not a persona. It is a `tier` and a set of `efforts` and `classes`, which is what the
registry already records. Substitution must therefore be justified on those axes: the substitute
carries the same tier band, is registered for the class it takes over, and is dispatched at the
effort the original route declared. Mapping a route onto a domain specialisation — a reviewer, a
front-end worker, a deployment helper — is not equivalence, because a specialisation says nothing
about capability tier or reasoning effort. Domain selection is an orthogonal axis and may be chosen
freely within an equivalent tier.

### Both axes must actually be settable

A substitution is only valid if the executing harness can set tier *and* effort for each dispatch.
Where a harness exposes tier per dispatch but takes effort from a static agent definition, effort is
resolved by that definition, not by the dispatcher, and the definition becomes the effort lever. The
session must then either:

- ensure the definitions it dispatches declare an explicit effort, with one definition per effort a
  domain is needed at, or
- record effort as an inherited default and treat it as unresolved.

Canon requires model and effort to be resolved explicitly, so an unresolved effort is a recorded gap
that bounds which lanes the substitution may serve. It must not be reported as a resolved value.
Definitions that pin a model also silently override a requested tier unless the dispatcher passes
the tier on every call; a dispatcher that cannot override them has not achieved the substitution it
claims.

Each client adapter states how its harness realises these levers. For Claude Code, see
`adapters/claude/ROUTING.md`; the registry keys `claude-fable`, `claude-opus`, `claude-sonnet` and
`claude-haiku` are the routable Claude tiers (ADR-0006).

### What survives a substitution unchanged

- lane ceilings from the routing policy;
- one leased file owner per wave, and no recursive delegation;
- the declared repair budget, then escalation to the parent;
- per-task runtime, output and token budgets;
- the single independent implementation-review route. A substitute reviewer sharing the
  coordinating session's client or model family is an author self-check, not independent review,
  and does not satisfy the review gate.

The approved substitution belongs in the consuming project's own records, alongside the work it
governs. Keep project-specific agent inventories, host details and task tables out of this
repository; only the substitution discipline is general.

A substitution is scoped to the work it was approved for. It does not become standing policy, and
it does not promote any substitute model's registry status. Promotion still requires paired
accepted-task evidence and an owner-policy change.
