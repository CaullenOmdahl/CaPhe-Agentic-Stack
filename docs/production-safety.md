# Production Safety Guide

CaPhe asks agents to rely on **deterministic automated checks** and **targeted diff audits** at ship time, not on post-turn `Stop` hooks or hand-written evidence files. These are instructions plus tools; see [What this does and doesn't enforce](#what-this-does-and-doesnt-enforce).

## Why No `Stop` Hooks?
Post-turn `Stop` hooks run after every assistant turn—even during exploratory reads or partial edits—causing multi-second/multi-minute hangs and noisy interruptions. Run checks instead:
1. **Explicitly during implementation** on the affected package/test file.
2. **At `pre-push`**, if you opt in by installing the hook, using the repository's real toolchain (see `hooks/pre-push-check.sh`).

## Automated Verification Ladder
Every production repository should declare its exact check commands in its root `AGENTS.md` (see `templates/repo/AGENTS.md`):
1. **Typecheck** (note: many build tools skip typechecking—run `tsc --noEmit` / `pyright` / `dart analyze` explicitly).
2. **Lint** (`eslint` / `biome` / `ruff` / `cargo clippy`).
3. **Tests** (targeted tests during iteration; full suite before production deploy or shared-core changes).
4. **Build / smoke check** (confirm production bundle compiles and starts cleanly).
5. **CVE check (`caphe-cve-check`)**: The canon instructs agents to run it on lockfile changes and before deploys, and the optional pre-push hook runs it with `--if-stale 24`. Nothing runs it automatically, and agents or operators can skip it.

## Behind-the-Scenes CVE Scanning (Zero LLM Tokens)
`install.sh` installs `caphe-cve-check` to `~/.local/bin/caphe-cve-check`. It uses `osv-scanner` (universal: JS/TS, Python, PHP, Java/Maven/Gradle, Go, Rust, Dart, Ruby) or `trivy` when installed, falling back to native ecosystem audits (`pnpm`/`npm`/`composer`/`pip-audit`/`cargo-audit`/`govulncheck`).

- **Nested discovery:** Manifests/lockfiles are found recursively up to 6 directory levels deep (monorepo `apps/*`, `services/*`, `packages/*`, not just the root). Dependency and build output is never searched: `.git`, `node_modules`, `vendor`, `target`, `dist`, `build`, `out`, virtualenvs, framework caches and similar. Add more with a repeatable `--exclude DIRNAME`.
- **Fast caching:** `--if-stale 24` skips repeat scans within 24 hours. The cache key covers the path and content of every discovered manifest, so adding, removing, moving or editing any of them (nested included) forces a re-scan. Only clean scans are cached.
- **Native fallbacks are per directory:** Without `osv-scanner`/`trivy`, each manifest is audited by its ecosystem tool in its own directory. A manifest no installed tool can audit (for example `pom.xml`, `yarn.lock`) is listed as not scanned and makes the run incomplete, never clean.
- **Outcomes:** (1) `no supported dependency manifests found` (exit `0`; nothing to scan, scanner not run); (2) `clean (cached result ...; not re-scanned)` (exit `0`; a previous clean scan of identical manifests); (3) `OK — scanned N manifest(s) with <scanners>` (exit `0`; a real scan ran); (4) `SCAN INCOMPLETE` (exit `2`) or `OPEN CVEs FLAGGED` (exit `1`).
- **Exit codes:** `0` clean, `1` high/critical CVEs flagged, `2` scan incomplete (scanner error, no scanner installed, or manifests that no installed tool covers). An incomplete scan is never reported or cached as clean, so the next run retries.
- **Background schedule (optional):** Run a lightweight daily cron or `systemd --user` timer across active project directories so open CVEs are flagged even between coding sessions:
  ```bash
  # Example daily background sweep (zero AI tokens; alerts only on findings)
  for d in ~/Projects/*/.git; do caphe-cve-check --repo "$(dirname "$d")" --if-stale 24 --quiet-ok; done
  ```

## What this does and doesn't enforce
- **Instructions** (canon, skills): agents are asked to follow them; nothing enforces it.
- **Installed tools** (`caphe-cve-check`, `caphe-models`): deterministic when run, never run on their own.
- **Optional pre-push hook:** opt-in, copied in manually, bypassed by `CAPHE_SKIP_PRE_PUSH=1` or `git push --no-verify`. It reuses a clean CVE result for up to 24h while dependency files are unchanged, so a new advisory against unchanged dependencies is not seen until the next real scan. Run `caphe-cve-check` without `--if-stale` before a release.
- **Repo-configured commands** (`.caphe.toml` `[verify]`): only as strong as the commands you declare.
- **External release controls** (branch protection, required reviews, CI gates): not provided by this stack; the operator owns them.
- **Scan incomplete (exit `2`):** never cached as clean and never a pass. The operator must resolve it.

A clean result is not proof of zero CVEs, and `tests/test_v2.sh` checks installer and tool behavior, not agent compliance.

## Compounding Engineering Rule
When a production defect or framework misuse slips through:
1. First add a **regression test** or **linter/type rule** so tooling catches it deterministically forever.
2. Only if tooling cannot catch it, add a **single binary line** (`MUST` / `NEVER`) to the repo's `AGENTS.md`. Keep `AGENTS.md` under ~100 lines.

## High-Risk Human Gates
Never bypass human confirmation for:
- Production deployments, releases, or rollback order.
- Database/schema migrations or wire-format changes.
- Auth, permissions, secrets, billing, or legal/compliance invariants.
- Force-push, destructive deletes, or merging into protected branches.
