# Production Safety Guide

CaPhe relies on **deterministic automated checks** and **targeted diff audits** at ship time, not on post-turn `Stop` hooks or hand-written evidence files.

## Why No `Stop` Hooks?
Post-turn `Stop` hooks run after every assistant turn—even during exploratory reads or partial edits—causing multi-second/multi-minute hangs and noisy interruptions. Run checks instead:
1. **Explicitly during implementation** on the affected package/test file.
2. **Automatically at `pre-push`** using the repository's real toolchain (see `hooks/pre-push-check.sh`).

## Automated Verification Ladder
Every production repository should declare its exact check commands in its root `AGENTS.md` (see `templates/repo/AGENTS.md`):
1. **Typecheck** (note: many build tools skip typechecking—run `tsc --noEmit` / `pyright` / `dart analyze` explicitly).
2. **Lint** (`eslint` / `biome` / `ruff` / `cargo clippy`).
3. **Tests** (targeted tests during iteration; full suite before production deploy or shared-core changes).
4. **Build / smoke check** (confirm production bundle compiles and starts cleanly).
5. **Non-discretionary CVE check (`caphe-cve-check`)**: Runs automatically on lockfile changes, pre-push, and before deploys—never left to user discretion.

## Behind-the-Scenes CVE Scanning (Zero LLM Tokens)
`install.sh` installs `caphe-cve-check` to `~/.local/bin/caphe-cve-check`. It uses `osv-scanner` (universal: JS/TS, Python, PHP, Java/Maven/Gradle, Go, Rust, Dart, Ruby) or `trivy` when installed, falling back to native ecosystem audits (`pnpm`/`npm`/`composer`/`pip-audit`/`cargo-audit`/`govulncheck`).

- **Fast caching:** `--if-stale 24` skips repeat scans within 24 hours unless a lockfile changed. Only clean scans are cached.
- **Exit codes:** `0` clean, `1` high/critical CVEs flagged, `2` scan incomplete (scanner error or no scanner installed). An incomplete scan is never reported or cached as clean, so the next run retries.
- **Background schedule (optional):** Run a lightweight daily cron or `systemd --user` timer across active project directories so open CVEs are flagged even between coding sessions:
  ```bash
  # Example daily background sweep (zero AI tokens; alerts only on findings)
  for d in ~/Projects/*/.git; do caphe-cve-check --repo "$(dirname "$d")" --if-stale 24 --quiet-ok; done
  ```

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
