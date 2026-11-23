---
name: git-github
description: Use when creating branches, committing, pushing, opening or updating GitHub pull requests, checking CI runs, or handling GitHub code review comments.
---

# Git & GitHub Workflow

Prefer local `git` and authenticated `gh` CLI over GitHub MCP servers.

## 1. Branch & Commit Hygiene
- Work on a scoped branch (`feat/...`, `fix/...`, `chore/...`), never commit unapproved work directly to `main`/`master`.
- Inspect `git status --short` and `git diff --stat` before staging; never silently stage unrelated user changes.
- Keep commits atomic and descriptive. Never commit `.env*`, credentials, private keys, local caches, or absolute user paths into public repos.

## 2. Push & Pull Request Flow
1. Run relevant checks (`verify-ship` skill) before pushing.
2. Push with `git push -u origin HEAD`. Never force-push shared/protected branches without explicit user approval.
3. Open/update PRs with `gh pr create` / `gh pr edit` including: concise summary, exact verification commands run, and any remaining limitations or prod-rollout notes.

## 3. CI & Review Follow-Up
- Inspect CI compactly (`gh pr checks` or `gh run view <id> --log-failed | tail -n 80`). Do not dump full successful CI logs into context.
- Read active PR review threads with `gh`, validate each finding against intended behavior, fix real defects, verify the changed delta, and reply concisely.
- Never self-merge or bypass required GitHub checks/approvals. Merge only with explicit human authorization.
- After an authorized merge, delete completed task branches only when all work is preserved.
