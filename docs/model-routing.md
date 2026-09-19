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
