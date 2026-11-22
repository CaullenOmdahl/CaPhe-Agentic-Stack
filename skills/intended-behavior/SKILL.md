---
name: intended-behavior
description: Use before implementing non-trivial UI/UX flows, onboarding, dashboards, metrics, or user-facing API behavior to align on observable outcomes and avoid late rework.
---

# Intended Behavior — Compact Contract Before Code

Skip this for trivial internal refactors or bug fixes with obvious expected behavior. Use it whenever UI ambiguity, metric semantics, or user-flow expectations could cause costly rework.

## 1. Capture Observable Behavior First (5–10 Lines)
Before editing code, write down briefly (in chat or Plan Mode):
- **Actor & entry point:** Who triggers this and from where?
- **Happy path:** Exact visible state, feedback, and next step (e.g., loading indicator, confirmation, keyboard shortcuts).
- **Data semantics (when applicable):** Source of truth, label, unit, timezone/locale, included/excluded records.
- **Empty / error / permission states:** What the user sees when data is missing, slow, or unauthorized.

If two interpretations lead to materially different product behavior, ask one focused question before coding.

## 2. Verify One Real Artifact Before Scaling
- Render/test one representative viewport, locale, or API response before replicating across platforms or variants.
- Confirm the actual rendered UI or live payload matches the contract—passing unit tests alone does not prove layout, copy, or onboarding clarity.
- Report the exact scope verified (viewport, build, mock vs. live backend).
