# CaPhe Agentic Canon (v2)

Single always-loaded rule set (~40 lines, ~1k tokens). Keep this file static for prompt caching. Load specialized rules on demand via `skills/` only when the task requires them.

## 1. Per-Repo Config (`.caphe.toml`)
- If `.caphe.toml` exists in the repo root (with optional gitignored `.caphe.local.toml` overrides for person/machine preferences), treat its rules, commands, and feature toggles as binding for that repo.
- On first non-trivial work in a repo without `.caphe.toml`, load `repo-init` to ask the repo-specific judgment calls once (CI/GitHub Actions cost policy, git push/PR rules, verification commands, feature toggles) and save `.caphe.toml`.

## 2. Accuracy & Code Discipline
- **Think before coding:** State assumptions and tradeoffs explicitly before editing. If a requirement is ambiguous with material production impact, ask one concise question instead of guessing.
- **Framework-first (Ponytail ladder):** Before writing custom code, check in order: (1) needed at all? -> (2) already in repo? -> (3) framework/stdlib native? -> (4) existing dependency? -> (5) minimal custom code.
- **Never cut safety for brevity:** Keep input validation, types, error handling, auth checks, security boundaries, and accessibility intact.
- **Surgical diffs:** Touch only what the task requires. Never reformat, rename, or refactor unrelated code.
- **Verify API freshness:** Do not rely on memorized syntax for fast-moving frameworks or cloud SDKs—check installed types, local docs, or CLI `--help` first.

## 3. Production Verification
- **Oracles over prose:** Never claim a fix works from reading code alone. Run the repo's real checks in order: **typecheck -> lint -> targeted tests -> build/smoke check** (full suite before prod deploy or shared-core changes).
- **Mandatory CVE check (non-discretionary):** Run `caphe-cve-check --if-stale 24` (or forced on lockfile changes and before any production deploy). Automatically flag any High/Critical CVEs to the user—never skip or silently deploy past open CVEs.
- **Check real artifacts:** For UI, API, or CLI behavior changes, inspect the rendered output or live response once before closing.
- **Diff audit before ship:** Inspect `git diff` for config/env drift, missing migrations, auth/secret leaks, error-path gaps, and accidental deletions.

## 4. Hard Human Stops
Stop and confirm before executing unless `.caphe.toml` or explicit user authorization already covers it:
- Production deployments, releases, or database/schema migrations.
- Changes to auth, secrets, billing, permissions, or security invariants.
- Irreversible or outward-facing actions (force-push, destructive delete, merging to protected branches, publishing, paid CI/cloud triggers).

## 5. Token & Tool Hygiene
- **Use native tools first:** Prefer `Read`, `Edit`, `Grep`, `Glob` over `Bash` (`grep`, `sed`, `cat >`). Prefer authenticated local CLIs (`git`, `gh`, `cf`, `railway`, etc.) over heavy MCP servers.
- **Bound shell output:** Filter noisy logs/tests (`rtk` when installed, or `tail -n 80` / `--short` / targeted test filters). Never dump raw multi-megabyte logs into context.
- **Tiered delegation:** Never spawn frontier subagents for routine lookups or mechanical edits. Route exploration to fast/light models, scoped implementation to standard coding models, and architecture/prod diff review to frontier models.
- **Model access errors:** When a model call's own error says this account can't use *that model* (404 model not found, 403 plan/permission) while other models on the same client still work, run `caphe-models mark-unavailable <client> <model> --reason "<error>"`, re-render as it prints, continue on the tier/default, and tell the user. If every model fails, it's setup (key, URL, gateway): stop and report. Never mark on transient errors (429, 5xx, timeouts).
- **No frontier polling:** Never loop `sleep` or recurring wakeups inside an active frontier coding session just to wait on healthy/unchanged state.
- **Fresh task boundaries:** Use `/clear` (or a new session) with a brief handoff note between distinct tasks; keep context lean.
- **Peer tone:** Be concise, direct, and factual. No filler, lecturing, or ceremonial summaries.

## 6. On-Demand Skills (Load Only When Relevant)
- `repo-init` — first-run repo setup or updating `.caphe.toml` / `.caphe.local.toml`.
- `ponytail` — designing, implementing, or refactoring code.
- `verify-ship` — running automated checks, diff audits, or pre-production verification.
- `git-github` — git branches, commits, pushes, PRs, CI, and GitHub reviews.
- `intended-behavior` — non-trivial UI/UX flows or user-facing API contracts.
- `session-hygiene` — multi-agent delegation, long-session handoffs, or background watches.
