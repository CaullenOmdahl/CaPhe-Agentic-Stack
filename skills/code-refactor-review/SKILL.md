---
name: code-refactor-review
description: Review diffs and pull requests for reuse, composition, codebase consistency, unnecessary indirection, React or frontend state slop, and avoidable diff churn. Use when the user asks for PR review, refactor review, cleanup review, reuse review, code-quality review, or slop detection.
---

# Code Refactor Review

Use this as a local quality lens for an existing diff. It supplements pull-request review; it does not replace independent PR review.

## Precedence

User instructions and `docs/canon.md` are authoritative.

If another process skill also applies, run the process skill first, then use this skill only for review-specific judgment.

## Workflow

1. Inspect the full diff, including staged and unstaged changes.
2. Identify the feature or behavior flow before reviewing isolated lines.
3. Search nearby code and sibling features before claiming something should be reused.
4. Review against the lenses below.
5. Report findings by severity with file and line references.

## Review Lenses

### Reuse

- Prefer established local utilities, components, hooks, route patterns, error handling, copy style, and data-loading patterns.
- Flag duplicate logic or custom helpers that overlap with existing code.
- Accept new shared helpers only when they have clear reuse or simplify a real boundary.

### Consistency

- File placement should match neighboring domain structure.
- Names should describe product behavior, not incidental implementation.
- Result, loading, error, and empty states should follow existing local conventions.
- User-facing copy should match the surrounding product voice.

### Composition

- Functions should have one clear level of responsibility.
- Avoid grab-bag modules that mix flags, API calls, formatting, UI state, logging, and scheduling.
- Avoid parameter sprawl; it usually means the boundary is wrong.
- Keep domain-specific logic close to the domain until cross-domain reuse is proven.

### Slop

Flag unnecessary:

- comments that restate obvious code,
- tiny wrappers with no domain meaning,
- exported one-off types,
- custom result shapes where a standard exists,
- memoization without a structural or measured reason,
- effects that mirror props or derived state,
- compatibility cruft that preserves accidental architecture,
- unrelated formatting, renames, or churn.

### React and Frontend State

- Derive render values during render when possible.
- Move event-caused work into event handlers.
- Reset state with keys when that is the simpler ownership boundary.
- Do not use `useMemo` or `useCallback` as default noise reduction.
- Avoid prop/callback plumbing that disappears when ownership is simplified.

## Output

Start with one verdict:

- `clean`: no meaningful concerns.
- `mostly clean`: minor cleanup only.
- `needs cleanup`: important consistency, reuse, or composition issues.

For each finding include:

- file and line or symbol,
- issue,
- existing pattern or searched area,
- minimal fix.

If the user asked for review only, do not edit files.
