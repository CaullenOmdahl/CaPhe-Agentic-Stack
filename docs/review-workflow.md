# One implementation review route

Prefer remote PR review; fall back to one independent local reviewer when remote
review is unavailable or quota-limited. Do not routinely run both. This is the
shared implementation-review policy for the canon, skills and project templates.

## Selection and completion

- Select one responsive remote reviewer unless actual repository branch protection
  requires more. Do not request every installed integration merely because it exists.
- Do not request the retired consumer Gemini Code Assist GitHub reviewer. Google
  shut it down on 2026-07-17. Enterprise is a different integration and requires
  explicit current installation and successful-response evidence. Local agy is separate.
  Source: https://developers.google.com/gemini-code-assist/docs/deprecations/consumer-code-review
- Inspect existing reviews/checks and private cooldown state before posting a trigger.
  A pending request is not a reason to post another. Atomically reserve an attempt
  with the helper below before triggering; only `request_reserved` permits sending.
- If remote review is unavailable, quota-limited, or has no result after one bounded
  window of at most seven minutes, record why and use one independent local reviewer.
  Do not wait through repeated windows. Observe asynchronously or in tool waits of
  at most 60 seconds; unchanged polls do not warrant model work or status narration.
- The local reviewer inspects the complete current implementation diff against its
  actual PR base plus necessary context, with a frozen source identity. Require a
  successful, non-empty result; use the second-opinion skill's isolated invocation.
  Same-family self-review is not independent fallback. If no independent route works,
  report the review blocker; never call missing review approval.
- Before launching a local fallback, check/reserve its machine-scoped availability
  key (for example `local:agy:ACCOUNT:machine`) with the same helper. Record
  local timeouts or unavailable clients too; a new task must not repeatedly relaunch
  a known unavailable fallback. This key is separate from the remote account quota.
- Local fallback satisfies the workflow's implementation-review requirement. Do not
  subsequently obtain remote review merely to duplicate it, including after quota
  resets. This does not bypass GitHub-required checks/approvals or merge/release gates.
  Preserve the PR as the change/discussion container when available.
- Keep the selected fallback for the current change. Carry all outstanding findings
  across route switches; switching reviewers or changing a commit never resets them.
- Record source identity internally. A changed behavioral diff needs review of its
  delta and affected context; retain prior review for unchanged material. Do not
  repeatedly ask for the entire diff to be rereviewed after each small repair.
  Deterministically proven docs/generated-only changes may use the mechanical lane.
- At most two fix-and-rereview rounds after the initial review, across both routes.
  Then stop for a concise human decision with unresolved findings. Do not use an
  unavailable provider attempt as a completed review round. Do not reset the counter
  on a new head or a switch to local.
- Batch related verified fixes, inspect siblings for the same defect class, and keep
  unrelated features/release work in separate PRs. Avoid changes to evidence files
  solely to stamp each new SHA and thereby create another review cycle.
- Read both summary findings and all relevant inline threads, including earlier-head
  unresolved findings. Paginate; truncated history cannot establish a clean review.
  Record a disposition and verification for each actionable finding.
- Normal updates report defects, fixes and remaining blockers. Keep hashes, raw
  review metadata, repeated no-change updates and certification ceremony out of chat.
  Final report: PR link, selected route, meaningful findings/fixes, checks and blockers.
  Show exact hashes only for a mismatch, artifact identity, or an explicit request.

## Persistent availability and request reservations

Set `CAPHE_RUNTIME` to the installed runtime (normally `~/.local/share/caphe/runtime`).
In a source checkout, use its root instead. This helper requires POSIX file locking.

Use `stack_review_cooldown.py` under the runtime tools directory. It uses the system UTC clock,
owner-only state under `~/.local/state/caphe/review-availability`, file locking and
atomic writes. It performs no network calls and never certifies code or posts comments.
All installed skill copies use this same helper/state, including across repositories.

The key is `provider:reviewer:account:scope`, for example
`github:codex:ACCOUNT:account`. Use the provider's actual quota scope when known;
if unknown, conservatively share the account key across repos. Do not include a PR,
commit, worktree or task in an account-quota key. Do not infer GitHub review quota
from a local Codex chat/CLI usage bucket. For a repository-only access failure use a
separate repo scope and check both account and repo state before requesting review.

```
python3 "$CAPHE_RUNTIME/tools/stack_review_cooldown.py" status --key KEY --subject OWNER/REPO/PR@HEAD
python3 "$CAPHE_RUNTIME/tools/stack_review_cooldown.py" claim --key KEY --subject OWNER/REPO/PR@HEAD
python3 "$CAPHE_RUNTIME/tools/stack_review_cooldown.py" blocked --key KEY --reason quota --token TOKEN --evidence RESPONSE_URL --observed-at RFC3339 --reset-at RFC3339
python3 "$CAPHE_RUNTIME/tools/stack_review_cooldown.py" success --key KEY --subject OWNER/REPO/PR@HEAD --token TOKEN --evidence REVIEW_URL
```

Before `claim`, reuse a review already present for the subject; do not request it
again. On `wait_existing_request`, observe that request or continue other work.
On `local_fallback`, switch locally without sending a remote trigger. A reservation
lasts ten minutes to prevent simultaneous agents or abandoned tasks causing duplicate
requests. Save the returned token and supply it when recording that attempt's result.
While a reservation lease is active, `blocked` requires its matching token too. Tokenless
external failure observations are accepted when no live reservation exists (including an abandoned, expired lease); they
must not cancel another task's request. Use `success` for a real completed review, even one with findings: it restores
availability, not approval. Acknowledgements, reactions and empty outputs do not count.

For a blocked response record its actual timestamp and source link, not the time an
old message was rediscovered. Omit `--reset-at` unless the provider supplies a reset
time or retry duration (convert the latter relative to the response timestamp).
Unknown quota reset defaults to a 24-hour *recheck estimate*, doubling on subsequent
failures up to seven days. Other unavailability/timeouts start at one hour and double
up to 24 hours. These estimates suppress retries; they are not promises of recovery.
Repeated observations of the same timestamp do not extend the cooldown.

After expiry, inspect existing provider status first and allow only one reserved
attempt when another remote review is actually needed. Do not wake up just to probe,
switch a completed local review back to remote, or repeatedly narrate the countdown.
Report once: blocked at TIME, provider reset TIME or estimated recheck TIME, local
fallback selected. If state cannot be read, stop remote requests and report the
state error; do not delete it or assume the provider is available.

For private continuation use the existing stack_state task record: PR/base/head,
selected route and reason, review round count, finding dispositions and next action.
Availability state is shared by quota scope; per-PR review progress is separate.
