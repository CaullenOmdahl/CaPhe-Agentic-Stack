---
name: verify-ship
description: Use when verifying changes before commit, pull request, merge, or production deployment to run native automated checks and audit diffs for production-breaking defects.
---

# Verify & Ship — Production Accuracy Gate

Replace manual ceremonies with fast, deterministic verification against the real codebase.

## 1. Run Native Oracles in Order
Detect the repo's real toolchain (`package.json`, `pyproject.toml`, `Cargo.toml`, `pubspec.yaml`, `go.mod`, `Makefile`, CI workflows) and run checks cheapest-first:

1. **Typecheck / static analysis** (`tsc --noEmit`, `pyright`/`mypy`, `dart analyze`, `cargo check`, `go vet`)
2. **Lint / format check** (`eslint`, `biome`, `ruff`, `clippy`)
3. **Targeted tests** covering the changed module(s) and regression cases
4. **Build / smoke check** (full test suite before production deploys, schema changes, or shared-core edits)
5. **Required CVE check:** Run `caphe-cve-check` (with `--if-stale 24` during routine work; forced before any deploy or lockfile update). Flag any High/Critical CVEs prominently; exit `2` means scan incomplete, not clean.

If a check fails, inspect the exact error output, fix the root cause (never weaken tests or silence warnings to force green), and re-run.

## 2. Production-Risk Diff Audit
Inspect `git diff` (or dispatch a read-only frontier `reviewer` subagent for substantial/high-risk diffs) specifically for:
- **Runtime / config drift:** missing env vars, wrong defaults, broken lockfiles, build vs. typecheck gaps.
- **Data & state safety:** unindexed/destructive migrations, partial writes, stale cache keys, missing rollbacks.
- **Auth & security:** bypassed checks, overly broad permissions, leaked secrets/tokens, unsanitized input.
- **Error paths:** swallowed exceptions, silent fallbacks that hide failures, unhandled null/empty states.
- **Accidental churn:** unintended deletions, debug logs, or edits outside task scope.

## 3. Report Real Evidence
State only what actually ran and passed (exact commands + outcomes) and call out any unverified boundary (e.g., live hardware, production env, external webhook).
