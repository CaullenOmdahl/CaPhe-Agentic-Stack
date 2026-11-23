---
name: ponytail
description: Use when designing, implementing, or refactoring code to enforce framework-first minimalism, prevent over-engineering, and avoid fragile custom boilerplate while keeping full production safety.
---

# Ponytail — Framework-First Minimalism

Before writing custom code or adding a dependency, walk this ladder in order and stop at the first rung that cleanly solves the problem:

1. **Needed at all?** Confirm the requirement is real and in scope. Skip speculative abstractions, unused extension points, and "just in case" config flags.
2. **Already in this repo?** Search existing utilities, hooks, components, queries, and helpers before writing a second copy.
3. **Standard library / runtime native?** Prefer built-in language and platform APIs (`URL`, `Intl`, `crypto`, `pathlib`, `sql`, native HTML elements/forms) over custom parsers or wrappers.
4. **Framework native?** Use the active framework's canonical primitives (routing, validation, caching, state, ORM migrations, middleware) instead of free-writing glue around it.
5. **Existing installed dependency?** Reuse what is already in the lockfile rather than adding a new package.
6. **Direct & small?** Prefer a clear 10-line function over a 100-line class hierarchy, factory, or manager layer.
7. **Minimal custom code (last resort):** Write only the smallest coherent implementation needed.

## Non-Negotiable Production Guardrails
Minimal code comes from omitting bloat—**never** from cutting correctness:
- Keep strict types, schema/input validation, and explicit error handling.
- Keep auth, permission, tenant, and secret boundaries intact.
- Keep accessibility, timezone/locale correctness, and edge-case guards.
- Leave unrelated code, comments, and formatting untouched (surgical diffs).
