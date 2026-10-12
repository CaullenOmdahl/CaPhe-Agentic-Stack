# Contributing to CaPhe

Help make the stack easier to understand, adopt, and maintain across coding agents. Useful contributions
include accurate examples, clearer installation instructions, regression fixes, and small reusable skills.

Read the [canon](docs/canon.md) and [public-safety rules](docs/public-safety.md) first. The canon defines
shared policy; adapters and guides should explain it without introducing competing requirements.

## Propose a change

Open an [issue](https://github.com/CaullenOmdahl/CaPhe-Agentic-Stack/issues) or a focused pull request.
Explain the problem, expected behavior, and concrete example. For policy or architecture changes, explain
the tradeoff before implementing a broad rewrite. Maintainers retain approval over consequential decisions.

Keep reports and examples public-safe. Do not include credentials, private hostnames, user paths, project
histories, local agent state, or private skill bodies. If you find a sensitive exposure, do not reproduce
its contents in a public issue or PR; use GitHub private vulnerability reporting if available, or an
existing private maintainer contact channel. No dedicated disclosure channel is configured by this guide.

## Work locally

Use Git, Python 3.11 or newer, and Bash on macOS or Linux. Linux/WSL is the route for Windows users.
The core checks use Python's standard library; optional provider and memory integrations have their own
prerequisites. Use existing clients and subscriptions only with the operator's consent.

```bash
git clone https://github.com/CaullenOmdahl/CaPhe-Agentic-Stack.git
cd CaPhe-Agentic-Stack
git switch -c your-change
```

Preserve existing instructions and hooks. You do not need to install the stack globally, configure a
memory hub, or launch a worker to contribute. Installer tests use disposable destinations; do not use
your real agent configuration as a test fixture.

## Verify the change

For documentation edits, check statements against current source, follow relative links, and inspect
the rendered Markdown, including tables and commands. For behavior changes, add useful regression
coverage and run the relevant tests. Keep historical evidence immutable.

On macOS, select a canonical temporary path before running the checks; security regressions reject
symlinked output roots (the standard `/tmp` path is a symlink):

```bash
export TMPDIR="$(python3 -c 'import os,tempfile; print(os.path.realpath(tempfile.gettempdir()))')"
```

The repository's broad local check set is:

```bash
python3 -m unittest discover -s tests -v
bash strict-mode/test/shell-syntax-test.sh
bash strict-mode/test/strict-confer-isolation-test.sh
bash strict-mode/test/strict-init-refresh-test.sh
bash test/public-safety-test.sh
```

The optional declared-matrix runner is `bash strict-mode/bin/strict-green-gate.sh --mode completion`.
Its current manifest covers Python tests, shell syntax, confer isolation, and public safety; run the
initializer refresh check separately when relevant. A green check result does not authorize merge or release.

GitHub Actions is currently disabled for cost control. The checked-in `quality` workflow is manual-only;
do not enable or dispatch it without maintainer authorization. Report local check results and limitations
in the PR instead of assuming automatic CI ran.

## Submit a pull request

- Keep the branch and commits scoped; stage only intended files.
- Describe the resulting behavior, why the change helps, and what you verified.
- Update related docs and skills when behavior changes. Put common rules in the canon and tool-specific
  notes in adapters. Include supporting files with a skill.
- Run the public-safety check and inspect the actual diff before pushing.
- Address relevant summary and inline review findings. Use one separate diff-review route when useful
  or required, preserving actual GitHub requirements and valid review of unchanged material.
- Leave merge, installation, and release decisions to the appropriately authorized maintainer.

Do not claim general efficiency or cost improvements from a single example. Evaluations should record
accepted task outcomes and total work, including coordinator effort, retries, and workers.
