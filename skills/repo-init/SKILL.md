---
name: repo-init
description: Use on first run in a repository that lacks `.caphe.toml`, or when the user wants to configure or toggle repo-specific or person-specific agentic stack settings.
---

# Repo Init — First-Run Per-Repo Config

Keep the global CaPhe stack identical across repos while capturing repo-to-repo and person-to-person judgment calls in a tiny `.caphe.toml` (shared) and optional gitignored `.caphe.local.toml` (personal override).

## 1. Detect Existing Defaults First
Before asking anything, inspect the repo root quickly (`package.json`, `pyproject.toml`, `Cargo.toml`, `pubspec.yaml`, `go.mod`, `.github/workflows/`, git remote visibility if available) so you can propose smart defaults instead of making the user type commands manually.

## 2. Ask Only What Varies Per Repo (One Concise Batch)
Ask the user in a single compact turn to confirm or adjust:
1. **GitHub Actions / remote CI policy:** `disabled` (never create/trigger paid Actions builds, e.g., private repos), `manual_only` (`workflow_dispatch` only), or `auto` (PR/push CI allowed).
2. **Git & PR autonomy:** `ask_before_push` (default), `branch_auto_push` (push feature branches freely, ask before PR/merge), or `manual_only` (never push).
3. **Production / deploy sensitivity:** `strict` (always ask before prod deploy/migrations/auth + require frontier diff review) or `standard` (ask on prod deploy/migrations; diff review only for risky changes).
4. **Verification commands:** Confirm the auto-detected `typecheck`, `lint`, `test`, and `build` commands (plus package manager if applicable).
5. **Feature toggles:** Which optional rules/skills to enable (`ponytail`, `verify_ship`, `git_github`, `intended_behavior`, `session_hygiene`, `caveman_terse_output`, `pre_push_hook`).
6. **Scope:** Write shared repo rules to `.caphe.toml` (committed) and/or personal preferences to `.caphe.local.toml` (ensure `.caphe.local.toml` is in `.gitignore`).

## 3. Write & Respect the File
- Write `.caphe.toml` cleanly using `templates/repo/.caphe.toml` structure (keep it <= 40 lines, zero secrets or private paths if the repo is public).
- Never re-ask settled questions on future turns once `.caphe.toml` exists; honor its toggles automatically (e.g., if `github_actions = "disabled"`, never create or trigger GitHub Actions workflows).
- If the user asks to change a setting later, edit `.caphe.toml` (or `.caphe.local.toml`) directly.
