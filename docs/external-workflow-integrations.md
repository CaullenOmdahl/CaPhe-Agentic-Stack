# External Workflow Integrations

This document records public workflow ideas considered for the stack and how they are integrated.

## Integrated

### Code refactor review

Source idea: `https://gist.github.com/jnsahaj/22806282b18a5c5136e0805d892dee39`

Integrated as `skills/code-refactor-review/SKILL.md`.

Adaptation:

- framed as a local review lens, not a completion gate;
- explicitly subordinate to `docs/canon.md`;
- requires searching local patterns before claiming reuse or inconsistency;
- preserves PR review as the canonical implementation-review route.

### Prepare branch context

Source idea: `https://gist.github.com/jnsahaj/fc47181ecf7c5c248a88f18a369c0a63`

Integrated as `skills/prepare-branch-context/SKILL.md`.

Adaptation:

- read-only by default;
- detects the real PR base before falling back to `main` or `master`;
- separates tracked dirt, staged changes, untracked files, and unpushed commits;
- includes PR comments and review data when available.

### UX flow plan

Source idea: `https://gist.github.com/jnsahaj/7d468eb2171705a7bb685c24e9003dee`

Integrated as `skills/ux-flow-plan/SKILL.md`.

Adaptation:

- positioned before implementation planning;
- includes boundary ownership and human-gated risk checks;
- avoids replacing the stack's implementation-plan or review workflow.

## Not Integrated As-Is

### Multiple checkout aliases

Source idea: `https://gist.github.com/jnsahaj/4a59082307d848d502a06086371a79cf`

Not integrated as shell aliases.

Reason:

- clone-per-branch aliases would compete with the stack's worktree preference;
- delete helpers around repository directories are destructive and should remain human-gated;
- the original alias assumptions are local-shell-specific.

Replacement:

- use scoped branches or `git worktree` for parallel work;
- inspect dirty state and unpushed commits before removal;
- keep destructive cleanup explicit and reviewed.
