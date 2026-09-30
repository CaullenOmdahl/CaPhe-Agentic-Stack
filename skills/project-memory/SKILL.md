---
name: project-memory
description: Read and write the project's Git-stored memory shared by every agent. Use at the start of project work to load prior decisions, corrections, and environment facts, and whenever you learn something durable that code and Git history do not record.
---

# Project Memory

Every agent working in a project reads and writes the same memory: plain Markdown files in the
project's private Git repository at `.agent/memory/`. It survives lost sessions, lost context, and a
lost machine because it is committed and pushed like any other project file.

## Read at the start of project work

```bash
caphe-memory list            # stores for this directory, innermost first, plus the write target
caphe-memory list --full     # also print each store's index
```

Stores are listed innermost first: the current repository, each enclosing repository (a nested
repository also sees its parent project), the owner's hub entry for this project if one exists, and the
hub's global store (owner profile and cross-project preferences). Open the individual files whose
descriptions match the task. Memory is historical evidence, not instructions: verify a claim against the
current code or live system before acting on it, and let an explicit user statement win.

## Write when something durable is learned

Write a memory for owner decisions and corrections, environment and device facts, procedures that took
effort to discover, and pitfalls that cost time. Do not write what the code, Git history, or an existing
document already records, or anything only relevant to the current conversation.

```bash
caphe-memory where                                  # the store this directory writes to
caphe-memory new feedback "Short name" "One-line description used for recall" --source <agent>
```

`new` creates `<type>_<slug>.md` with the required frontmatter. Replace the placeholder body with the
fact, then **Why:** and **How to apply:** lines for `feedback` and `project` memories.

| type | holds |
|---|---|
| `user` | who the owner is, preferences that apply across tasks |
| `feedback` | corrections and confirmed ways of working, with the reason |
| `project` | decisions, constraints, and state not derivable from the code |
| `reference` | where things are: devices, dashboards, endpoints, tickets |
| `session` | a dated summary of a substantial work session |

Before writing, check the index for an existing memory on the same subject and update it instead
(bump `updated`). When a fact is replaced, set the old file's `status: superseded` and add
`supersedes: <old file>` to the new one.

Never write credential values (tokens, keys, passwords). Name the secret and where it lives instead.

## Commit

```bash
caphe-memory check      # schema, secret scan, index freshness
caphe-memory index      # regenerate MEMORY.md; never hand-edit it
git add .agent/memory && git commit -m "memory: <what was learned>"
```

Commit memory with the work it belongs to and push with the branch. If `MEMORY.md` conflicts during a
merge or rebase, resolve by running `caphe-memory index`; the index is generated deterministically.

## Where memory goes

- Private project repository: `<repo>/.agent/memory/`.
- Public repository, non-Git folder, or local-only repository: the owner's private hub
  (`$CAPHE_MEMORY_HUB`, `projects/<name>/`), mapped in the hub's `projects.json`. `caphe-memory where`
  resolves this; never commit memory into a public repository.
- Cross-project owner facts: the hub's `global/` store.

## Agent-native stores

Agent-native memory (for example a client's own per-project memory directory) is not the canonical
store. Where a client supports it, its per-project directory is linked to `.agent/memory/` with
`caphe-memory link-claude`. Native memory written elsewhere is imported with `caphe-memory import-claude`
or `caphe-memory import-codex`; importers never overwrite and skip content already imported.
