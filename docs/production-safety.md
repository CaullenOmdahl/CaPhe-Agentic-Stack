# Production Safety Guide

CaPhe v2 replaces ceremonial evidence files and post-turn `Stop` hooks with **deterministic automated checks** and **targeted diff audits** at ship time.

## Why No `Stop` Hooks?
Post-turn `Stop` hooks run after every assistant turn—even during exploratory reads or partial edits—causing multi-second/multi-minute hangs and noisy interruptions. Run checks instead:
1. **Explicitly during implementation** on the affected package/test file.
2. **Automatically at `pre-push` or CI** using the repository's real toolchain (see `hooks/pre-push-check.sh`).

## Automated Verification Ladder
Every production repository should declare its exact check commands in its root `AGENTS.md` (see `templates/repo/AGENTS.md`):
1. **Typecheck** (note: many build tools skip typechecking—run `tsc --noEmit` / `pyright` / `dart analyze` explicitly).
2. **Lint** (`eslint` / `biome` / `ruff` / `cargo clippy`).
3. **Tests** (targeted tests during iteration; full suite before production deploy or shared-core changes).
4. **Build / smoke check** (confirm production bundle compiles and starts cleanly).

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
