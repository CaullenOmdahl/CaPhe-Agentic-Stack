# Practical diff review

The [canon](canon.md) defines the workflow. Review should help resolve risk and defects, not add a
ceremony. Use one route when review is useful, explicitly requested, or actually required. This guide
adds no acceptance gates.

1. Inspect the actual branch/base and existing reviews/checks. Reuse a completed review for unchanged
   material and do not duplicate a pending request.
2. Prefer a working remote PR reviewer. Use one separate local review if remote is unavailable or local
   review is requested. Do not routinely perform both. Model-family diversity is not required: a separately
   performed same-family review is allowed; author self-attestation is not review. Different-family review
   is optional for a concrete risk, conflicting evidence, or an explicit owner requirement.
3. Send the actual diff and necessary context with a neutral description of intended behavior. Local
   review must preserve read-only source/permission isolation, omit unrelated tool servers, and keep
   credentials, histories, and private memory out of review material. Confirm the invocation succeeded
   and produced a real assessment; discovery/version output, acknowledgements, and empty output do not
   establish completed review. Choose suitable capability using judgment, not family labels.
4. Read relevant summaries and inline threads, including unresolved findings from earlier revisions.
   Verify findings against the code. Batch related repairs, run relevant checks, and review changed
   behavior/context where useful. Retain valid review of unchanged code; evidence-only commits do not
   trigger fresh review loops. Avoid switching reviewers merely to escape real findings.
5. Report the PR, meaningful findings/fixes, checks, and genuine access limitations. Optional QA does not
   block closure of a verified defect. Additional review/tests need a concrete distinct reason. Preserve
   actual GitHub requirements and owner merge/install/release approval.

## Availability and optional helpers

Use existing reviews and provider status before requesting again. A pending review is not unavailable
merely because it is slow. An actual authentication, access, or quota failure can justify a fallback;
report missing capability without claiming a review occurred. Do not install clients, sign in, add billed
services, or widen access merely to satisfy a review ritual. The retired consumer Gemini GitHub review
service is not a usable route; verify current capabilities rather than assuming a catalog stays current.

`tools/stack_setup.py review-routes --current <agent>` is an optional inventory. Its family metadata is
informational and its eligibility fields do not certify authentication, isolation, or completed review.
See `docs/reviewer-catalog.md` and the selected reviewer skill only when they help use that capability.

`tools/stack_review_cooldown.py` is an optional coordination helper for environments with concurrent
requests or known shared quotas. It does not intercept GitHub or certify review. Ordinary repository
work does not require reservations, a private state store, or cooldown records. When selected, use its
atomic claim token for the corresponding request, preserve existing state, and distinguish provider reset
times from estimated recheck times. Do not copy availability or credentials between machines. A helper
failure is not a new acceptance gate; inspect actual provider status and avoid duplicate requests.
