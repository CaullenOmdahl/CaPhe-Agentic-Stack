# External Account Research

This note tracks public GitHub accounts and repositories worth monitoring for agentic development workflow ideas.

The filter for this repository is strict:

- agent-agnostic or easily adaptable across Codex, Claude, Gemini, Cursor, OpenCode, and Copilot;
- public-safe, with no reliance on private local services;
- compatible with the pull-request review canon in `docs/canon.md`;
- useful as source material for small, reviewable stack improvements.

## Highest Priority

### vercel-labs

Sources:

- [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills)
- [vercel-labs/skills](https://github.com/vercel-labs/skills)
- [vercel-labs/coding-agent-template](https://github.com/vercel-labs/coding-agent-template)
- [vercel-labs/open-agents](https://github.com/vercel-labs/open-agents)

Why it matters:

- Official Vercel Labs material around agent skills, distribution, and coding-agent runtime templates.
- The skills tooling and repository shape are directly relevant to our `skills/` directory.
- The coding-agent and open-agent templates are useful references for background-agent architecture, but should not be copied into this repo unless we decide to build runtime infrastructure.

Candidate follow-up:

- Add a documented compatibility check between this repo's `skills/*/SKILL.md` files and the Vercel Agent Skills format.
- Consider a small `docs/skill-packaging.md` note if we decide to publish or install these skills through `npx skills`.

### waterrmalann

Source:

- [waterrmalann/How I use AI agents effectively](https://gist.github.com/waterrmalann/6e1b2b60006b54087a5c07b032bc4773)

Why it matters:

- Practical operating notes on using agents effectively.
- Points toward Vercel skills and structured skill use instead of overloading one giant instructions file.
- Useful as a sanity check for keeping this stack concise and skill-oriented.

Candidate follow-up:

- Extract only workflow principles that reduce context load or improve handoff clarity.
- Avoid copying model-specific or time-sensitive recommendations.

### davidgibsonp

Source:

- [davidgibsonp/Agent-Agnostic Repository Guide](https://gist.github.com/davidgibsonp/337be9b80b3f03eccd188235c287bb05)

Why it matters:

- Directly aligned with this repository's purpose: agent-agnostic repo conventions, shared skills, symlinks, and private local skills.
- Specifically useful for deciding whether `.agents/skills/` should become the canonical skill source instead of `skills/`.

Candidate follow-up:

- Compare `.agents/skills/` against the current `skills/` layout.
- Decide whether this repo should support generated symlinks or stay documentation-only.

### bradfeld

Source:

- [bradfeld/Advanced Claude Code Configuration Guide](https://gist.github.com/bradfeld/1deb0c385d12289947ff83f145b7e4d2)

Why it matters:

- Mature solo-development operating model covering worktrees, session persistence, quality gates, and workflow discipline.
- Useful for process review, especially around long-running work and multi-repo context.

Candidate follow-up:

- Mine for process checks, not local business operations.
- Keep any adoption small because the source is Claude-heavy and personal-workflow-specific.

## Medium Priority

### fcakyon

Source:

- [fcakyon/claude-codex-settings](https://github.com/fcakyon/claude-codex-settings)

Why it matters:

- Broad Claude Code and Codex setup with skills, plugins, hooks, agents, and cross-tool installation notes.
- Good catalog for plugin packaging and hook ideas.

Risk:

- Large and opinionated. High risk of importing tool-specific ceremony or hidden assumptions.

Candidate follow-up:

- Review plugin layout and packaging only.
- Do not adopt hooks without a separate safety review.

### joelhooks

Sources:

- [joelhooks/OpenCode global AGENTS prompt](https://gist.github.com/joelhooks/3c3db5ea5df87e2df9aad15207bd6512)
- [joelhooks/swarm-tools](https://github.com/joelhooks/swarm-tools)
- [joelhooks/opencode-config](https://github.com/joelhooks/opencode-config)

Why it matters:

- Strong material on multi-agent coordination, work queues, file reservations, and agent mail.
- Relevant if we later support multiple agents working the same repo at the same time.

Risk:

- Coordination services are infrastructure, not simple instructions. They can add operational weight quickly.

Candidate follow-up:

- Record coordination principles first.
- Defer service or MCP adoption until we have a concrete multi-agent collision problem.

### wshobson

Source:

- [wshobson/agents](https://github.com/wshobson/agents)

Why it matters:

- Large multi-harness plugin and skill marketplace spanning Claude Code, Codex CLI, Cursor, OpenCode, Copilot, and Gemini.
- Useful for discovery and naming conventions.

Risk:

- Very large surface area. Treat as a catalog, not a source of default rules.

Candidate follow-up:

- Sample only specific skills with clear relevance.
- Avoid bulk imports.

## Lower Priority / Watchlist

### Anbeeld

Source:

- [Anbeeld/AGENTS.md](https://github.com/Anbeeld/AGENTS.md)

Why it matters:

- Compact global instruction set focused on evidence, parallelization, and validation.
- Useful comparison point for keeping our canon concise.

Candidate follow-up:

- Compare structure against `docs/canon.md` during future cleanup.

### zoharbabin

Source:

- [zoharbabin/Agent Skills Ecosystem Guide](https://gist.github.com/zoharbabin/cf5ab80b2b0af50e34328b5eb2bfdc93)

Why it matters:

- Agent skills ecosystem and distribution notes.
- Useful for understanding conventions, not necessarily workflow behavior.

Candidate follow-up:

- Monitor for updates on standardized skill distribution formats.

### RedEagle-dh

Source:

- [RedEagle-dh/Sharing AI Agent Skills](https://gist.github.com/RedEagle-dh/adc52131e27b272d97aa18c9030d808d)

Why it matters:

- Cross-agent skill sharing and symlink setup across local tool directories.
- Relevant only if we decide to support local installation automation.

Candidate follow-up:

- Keep as reference if local symlink automation becomes a priority.

### littlebearapps

Source:

- [littlebearapps/contextdocs](https://github.com/littlebearapps/contextdocs)

Why it matters:

- AGENTS-first context file model spanning multiple agent tools.
- Low current adoption, but relevant to context-maintenance ideas.

Candidate follow-up:

- Evaluate contextdocs structure if we design multi-agent context templates.

## Immediate Recommendation

Next research PR should inspect `vercel-labs/agent-skills`, `vercel-labs/skills`, and the `davidgibsonp` agent-agnostic repo guide together.

Reason:

- They are the closest match to this repository's current shape.
- They could influence skill packaging and directory layout without changing our development canon.
- They are less likely to collide with PR review, public-safety, or human-merge gates than swarm coordination or hook-heavy setups.
