# Current Stack Inventory

This is a public-safe inventory of the current setup shape. It intentionally avoids local usernames, hostnames, client names, credentials, cache paths, and private release procedures.

## Agent Entrypoints

The current local setup uses one shared global canon with thin agent-specific adapters:

- Root tool files: detected by each agent and point to the adapter plus canon.
- Codex adapter: points to the shared canon and adds sandbox, memory, and offload cautions.
- Claude adapter: points to the shared canon and adds skill/review reminders.
- Gemini / Antigravity adapter: points to the shared canon and adds model-effort and offload reminders.

The important pattern is single-source canon plus small adapters. Parallel full copies should be avoided because they drift. Tool-native filenames can coexist with consistent human-facing adapter filenames when a tool expects a specific entrypoint.

## Skill Categories

Current skills fall into these public-safe categories:

- process discipline: intended behavior, strict-mode variants, verification, second opinion;
- review and PR support: code review, GitHub publishing, review follow-up, CI debugging;
- UI and product planning: frontend design, UX flow, product context;
- document and data utilities: spreadsheets, documents, PDF handling;
- browser and computer control: browser testing, local UI inspection, device automation;
- cloud and deployment helpers: provider-specific release or infrastructure workflows;
- domain-specific private workflows: excluded from this public repo.

Only generic, reusable, public-safe skills should be promoted into this repository.

## Current Review Policy

Implementation review should happen through pull requests. Local peer review can supplement design work or act as an emergency fallback, but it should not block opening a PR or be represented as completed implementation review.

## Current Worktree Policy

Use isolated branches or worktrees for meaningful changes. Before answering repo-state questions, inspect the actual checkout and distinguish:

- tracked modifications,
- staged changes,
- untracked files,
- unpushed commits,
- sibling worktrees.

## Public-Repo Boundary

Do not copy raw home-directory configuration, caches, auth files, project histories, machine inventories, or private skill bodies into this repo.
