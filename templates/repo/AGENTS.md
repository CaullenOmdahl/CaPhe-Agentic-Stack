# AGENTS.md — Project Agent Contract

Keep this file under ~80 lines. Add a binary rule only to prevent a real recurring mistake.

## Verification Commands (Run Before Commit / Push)
- Typecheck: `<e.g. pnpm typecheck / pyright / dart analyze>`
- Lint: `<e.g. pnpm lint / ruff check .>`
- Targeted test: `<e.g. pnpm vitest run path/to/file.test.ts / pytest tests/test_x.py>`
- Build / full check: `<e.g. pnpm build && pnpm test>`

## Hard Constraints
- Package manager: `<e.g. pnpm only — never npm or yarn>`
- Framework idioms: `<e.g. Next.js App Router only; Server Components by default; Prisma migrations only>`
- NEVER commit `.env*`, credentials, or private keys.
- NEVER mock or bypass auth, permission, or validation checks to make tests pass.
- NEVER modify unrelated files or reformat untouched code.

## High-Risk Areas (Confirm Before Changing)
- `<e.g. db/migrations/, auth/, billing/, infra/>`

## Key Paths
- `<e.g. src/ — application code>`
- `<e.g. tests/ — automated test suite>`
