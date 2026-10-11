---
name: gh-review-certify-loop
description: Use one practical PR diff review route and address real findings without redundant review ceremony.
---

# PR review

Follow `docs/canon.md` in the source checkout or installed runtime. Use `docs/review-workflow.md` as
practical guidance, not an additional policy. Inspect the actual diff, existing reviews, and required
checks; choose one working route when review is useful, requested, or required. Prefer remote review,
with a separate local fallback when unavailable or explicitly requested. A separately performed
same-family review is allowed; author self-attestation is not review. Family diversity is optional for
a concrete risk, conflicting evidence, or explicit owner requirement.

Read relevant summaries and inline findings, validate them, and repair real defects with relevant checks.
Review changed behavior/context as useful; keep valid review of unchanged material. Do not restart review
for evidence-only churn or make optional QA block closure. Additional review needs a distinct reason.
Never duplicate a pending request or request a retired reviewer. Availability helpers are optional;
actual authentication/quota failures do not become instructions to bootstrap new clients or integrations.

Report the PR, meaningful fixes, checks, and genuine limitations. Preserve actual GitHub requirements,
source/permission isolation, secrets, and owner merge/install/release approval. Do not treat a check result,
acknowledgement, empty output, or missing reviewer as review approval.
