# Claude Entry Point

Read `docs/canon.md` and treat it as binding unless the user gives a more specific instruction.
Use native Plan Mode for non-trivial changes, delegate routine coding/exploration to tiered subagents (`worker` on the standard tier, `explorer` on the fast tier), and load skills under `skills/` only when relevant.
