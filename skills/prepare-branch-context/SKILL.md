---
name: prepare-branch-context
description: Build read-only context for the current branch or pull request before follow-up work. Use when the user asks what a branch does, asks for PR context, inherits an unclear branch, or wants to continue work from an existing branch.
---

# Prepare Branch Context

Use this before changing an inherited branch. The skill is read-only.

## Precedence

User instructions and `docs/canon.md` are authoritative. If worktree discovery applies, inspect worktrees before assuming the current checkout is the whole state.

## Workflow

1. Identify the branch and repository:

```bash
git status -sb
git branch --show-current
git remote -v
```

2. Detect the base branch in this order:

- PR base from `gh pr view --json baseRefName,headRefName,url,state`;
- remote default from `git symbolic-ref -q refs/remotes/origin/HEAD`;
- `main`;
- `master`.

3. Inspect branch changes:

```bash
BASE_BRANCH="$(gh pr view --json baseRefName --jq .baseRefName 2>/dev/null || true)"
if [ -z "$BASE_BRANCH" ]; then
  BASE_BRANCH="$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|origin/||')"
fi
BASE_BRANCH="${BASE_BRANCH:-main}"
if git rev-parse --verify "origin/$BASE_BRANCH" >/dev/null 2>&1; then
  BASE="origin/$BASE_BRANCH"
else
  BASE="$BASE_BRANCH"
fi

git diff "$BASE"...HEAD --stat
git diff "$BASE"...HEAD
git log --oneline "$BASE"..HEAD
```

4. Inspect PR context when available:

```bash
if PR_DATA="$(gh pr view --json number,title,body,url,state,comments,reviews,reviewDecision,statusCheckRollup 2>/dev/null)"; then
  printf '%s\n' "$PR_DATA"
  NUMBER="$(printf '%s\n' "$PR_DATA" | jq -r .number)"
  REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
  gh api "repos/$REPO/pulls/$NUMBER/comments"
fi
```

5. Report:

- purpose of the branch,
- base branch used and how it was detected,
- key files and areas affected,
- notable decisions or patterns,
- open comments or review findings,
- tracked changes, staged changes, untracked files, and unpushed commits.

## Rules

- Do not edit files.
- Do not assume `main` when PR metadata or remote default says otherwise.
- Do not collapse dirty worktree state and unpushed commits into one status.
- If the diff is large, read the full structure first, then inspect the highest-impact files in detail.
