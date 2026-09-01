---
name: gh-review-certify-loop
description: Run a GitHub pull request review loop with the repository's currently active review integrations. Use when the user asks to request GitHub reviews, wait for bot feedback, address review comments, loop until the PR is clear, then optionally merge or clean up when explicitly requested.
---

# GitHub Review Certify Loop

## Goal State

Drive one GitHub PR to a stable finish:

- The current branch is pushed.
- Every configured, currently responsive review integration has reviewed the current head.
- After the review wait, thread-aware data shows no current actionable findings from those reviewers.
- Required verification for changed surfaces passes.
- If and only if the current user request explicitly includes merge/cleanup, the PR is merged and related branches are deleted safely.

Do not treat flat PR review summaries as sufficient. Use thread-aware review data and compare stale anchors against the live code.

## Preconditions

1. Read repo instructions first.
2. Confirm `gh auth status`.
3. Resolve the PR from the current branch unless the user supplied a PR number or URL.
4. Check `git status -sb`.
5. If there are unrelated local changes, do not stage or modify them.
6. If the request includes merging, confirm the base branch and required checks before merging.
7. Discover the active reviewer set from current evidence before posting triggers:
   - inspect review workflows and repository instructions;
   - inspect recent successful review checks, reviews, and bot comments;
   - count a reviewer as active only when its integration is configured and has responded
     recently, or when a current check proves it ran.

## Review Loop

Use this loop until certified or blocked:

1. Ensure the latest local fixes are committed and pushed.
2. Trigger or observe every active reviewer on the current head using only currently verified repository
   triggers or check workflows. A mention or slash command is not evidence that an integration exists.
3. Give asynchronous reviewers one bounded window of up to seven minutes:
   - For check-backed reviewers, prefer `gh pr checks --watch --interval 15` so completion can return early.
   - Otherwise use one bounded wait; do not busy-poll comment state.
4. Fetch PR state with thread awareness:
   - Prefer the `gh-address-comments` skill/script when available.
   - Otherwise use `gh api graphql` to read `reviewThreads { isResolved isOutdated path line comments }`, reviews, and PR comments.
5. Classify findings:
   - **Current actionable**: non-outdated unresolved bot thread that still describes a real issue in current code.
   - **Stale anchor**: unresolved/non-outdated thread whose requested change is already present or whose referenced code no longer behaves that way.
   - **Waiting**: one bot has not posted a review for the current head after the 7-minute wait.
   - **Blocked**: conflicting feedback, failing required checks unrelated to the fix, missing auth, or unclear product behavior.
6. If one reviewer returns actionable feedback and another active reviewer has not returned after the bounded wait:
   - Address the returned feedback first.
   - Run focused verification.
   - Commit and push.
   - Trigger or observe all active reviewers again and restart the bounded wait.
7. If multiple reviewers return actionable feedback:
   - Address highest severity first.
   - Prefer one focused commit per review cluster.
   - Run focused verification for each cluster, then broader verification before final certification.
8. If neither has current actionable feedback on the current head:
   - Treat the active GitHub reviewer set as certified.
   - Record stale unresolved anchors explicitly in the final status if GitHub still shows them.

## Fix Discipline

- Verify review claims against current code before implementing.
- Do not blindly implement a suggestion that would break the intended behavior.
- Add or update tests for every behavioral review fix.
- Keep commits scoped to the feedback cluster.
- Run `git diff --check` before committing.
- Let repo hooks run unless the user explicitly permits bypassing them.

## Merge And Cleanup

Only perform this section when the current user request explicitly asks for merge/close/delete behavior.

1. Confirm certification on the current head.
2. Confirm required checks are green or not required by branch protection.
3. Merge with the repo’s normal method, preferring:
   - `gh pr merge <pr> --squash --delete-branch` if squash is the repo norm.
   - Use the merge method requested by the user or visible repo convention.
4. The PR closes automatically when merged. Do not separately close a merged PR.
5. Delete only branches related to this PR:
   - Remote branch deletion can be handled by `--delete-branch`.
   - For local branch deletion, switch to the base branch first, fast-forward it, then delete the feature branch.
6. Never force-delete a branch unless the user explicitly asks and you have verified it is merged or disposable.

## Stop Conditions

Stop and report instead of looping when:

- Active reviewer feedback conflicts and both interpretations are plausible.
- A required check fails for a reason unrelated to the review fixes.
- A bot has not responded after two consecutive bounded waits on the same head.
- GitHub auth or rate limits block thread-aware reads.
- Merge would require force, bypassing protections, or deleting a branch that is not clearly related to the PR.

## Final Report

Include:

- PR URL and final head SHA.
- Active reviewer names and their latest review/check timestamps.
- Current actionable threads: none, or list remaining blockers.
- Stale unresolved anchors, if any, with why they are stale.
- Verification commands and results.
- Commits pushed.
- Merge and branch deletion result, if requested and performed.
