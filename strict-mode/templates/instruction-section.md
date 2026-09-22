<!-- STRICT-MODE:BEGIN (managed by strict-mode; edit the canon, not this marker) -->
## Strict Mode

Read `~/strict-mode/methodology.md` for evidence lanes and the workflow runtime.
Keep `.agent/OWNERS.md` human gates, defect-detection evidence, one independent implementation review, and real-artifact
verification. Uncertain changes are behavioral. Pre-commit `FAST GREEN` is feedback; completion requires
`~/strict-mode/bin/strict-green-gate.sh --mode completion` and review evidence.
Prefer remote PR review; use independent local fallback on unavailability, with persistent cooldowns
and continued remediation until clean per the runtime `docs/review-workflow.md`. Do not routinely run both routes.
Keep immutable public evidence under `.agent/evidence/`, private continuation outside Git, and resolve
model plus effort explicitly. Prototype mode never relaxes completion; persistent disable remains user-only.
<!-- STRICT-MODE:END -->
