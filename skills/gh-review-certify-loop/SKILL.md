---
name: gh-review-certify-loop
description: Obtain one remote PR implementation review, fall back locally when unavailable, and address findings with continued remediation and persistent failure cooldowns.
---

# PR Review

Read `~/.local/share/caphe/runtime/docs/review-workflow.md` before requesting a
review. It is the shared policy for route selection, persistent
UTC cooldowns, request reservations, continued remediation and concise reporting.

1. Inspect repository instructions, actual branch/base, existing PR reviews/checks,
   and dirty state. Preserve unrelated edits and existing user authorization.
2. Select one responsive remote reviewer. Check account/repository cooldown state
   using the policy's helper; reserve before posting a trigger. Never request the
   retired consumer Gemini GitHub reviewer or duplicate an existing pending request.
3. Prefer remote review. After an explicit provider failure, unavailability or quota failure, record the evidence/time and use one independent local reviewer
   through `second-opinion`. Do not perform both routes routinely. Local fallback
   satisfies implementation review; GitHub-required checks remain enforceable.
4. Inspect all relevant inline threads AND review summaries, including unresolved
   findings from prior heads. Fetch missing pages; incomplete history is not clean.
   Validate claims against current code and intended behavior. Track each finding's
   disposition, source, fix and verification; distinguish stale anchors from defects.
5. Batch related fixes and test behavior. Review the changed delta and affected
   context after fixes; keep previous evidence for unchanged code. Continue until
   actionable findings are resolved. There is no fixed review duration or round cap;
   never ask permission merely to continue. Escalate genuine ambiguity, missing access
   or demonstrated non-progress, not a counter. Let pending/running reviews finish.
6. Complete required checks. Report the PR link, selected route, meaningful fixes,
   verification and remaining blockers. Keep hashes internal unless identifying a
   mismatch/artifact or explicitly requested. Avoid repeated certification comments.

A successful local fallback does not need another remote review when quota resets.
A same-family local audit, empty output, timeout or missing reviewer is not independent
approval. Do not switch reviewers to escape actionable findings.

Merge only with existing explicit authorization for this exact PR and repository
policy permission; verify branch protection and checks. Delete only authorized,
merged task branches. Review approval is not release/deployment authorization.
