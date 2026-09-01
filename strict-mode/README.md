# Strict Mode v2

Version-controlled source for the evidence-preserving strict workflow. Install from this repository into
`~/strict-mode`; edit and review this source, not the deployed copy.

Key commands:

```bash
strict-mode/bin/strict-init.sh
strict-mode/bin/strict-green-gate.sh --mode affected
strict-mode/bin/strict-green-gate.sh --mode completion
strict-mode/bin/strict_evidence.py evidence.json --root .
strict-mode/bin/strict-confer.sh codex --adversarial --save design-v1 "Review the ADR"
```

The affected gate optimizes feedback. The completion gate and independent PR review remain authoritative.
Default manifests include independent nested Python test roots as well as discovered Dart, Node, Cargo,
and Go roots.

`strict-confer` is for design/ADR review or an explicitly recorded fallback when PR review is genuinely
unavailable; it is not normal implementation-review evidence. Its local peer set is Claude Code, agy
(Gemini-family), and Codex. A direct Gemini CLI install is not automatically equivalent to agy. The
wrapper pins reviewer models that may be overridden only after the installed clients verify them.

Confer snapshots materialize stage-0 regular blobs directly from the Git index. They omit unstaged
worktree bytes, symlinks, gitlinks, and every arbitrary untracked file, even when it is not ignored;
peer environments receive no live source-root path. Stage every deliberate review input before invoking
confer. Snapshot mode refuses non-Git worktrees and unmerged index entries. Peer execution additionally uses
a default-deny host filesystem, a scrubbed environment, and an ephemeral home seeded with only the minimum
CLI authentication state. macOS masks host data roots and reopens selected system/runtime paths through
`sandbox-exec`; Linux constructs a selective Bubblewrap namespace with a private PID namespace. The command
fails closed if a peer or boundary cannot operate without broader host access.
