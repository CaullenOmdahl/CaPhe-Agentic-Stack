# Evaluating v2 against a plain-client baseline

Status: **first run published**: [2026-11-24, Claude Code](results/2026-11-24-claude-code.md). Across 40 trials, v2 showed no measurable benefit on these four small tasks. README outcome claims stay scoped to published results. Tracking issue: #39.

The existing `tests/test_v2.sh` shows that installation, settings preservation, tier tooling and scanner wrappers work. It does not show that the v2 rules and skills change agent outcomes. This document defines how to measure that.

## Hypothesis

With the **same client, same model, same configuration and same task**, an agent run with v2 installed (canon, skills, subagent profiles) produces equal or better outcomes than the same agent without v2:

- H1: higher hidden-test correctness and fewer regressions.
- H2: required verification commands are run more often.
- H3: fewer unwanted or out-of-scope changes.
- H4: total tokens/cost and wall time are not worse by more than the measured benefit justifies.

Any of these may turn out false. Report whichever way it falls.

## Task suite

Defined before any run and frozen in `eval/` (one task per category from the issue). Each task is a tiny synthetic fixture, stdlib Python or plain JS, no installs.

| Task | Category | What it checks |
|---|---|---|
| `implement` | implementation | Parse duration strings (`1h30m`) with strict validation; hidden edge cases. |
| `bugfix` | bug fixing | Off-by-one pagination bug; hidden property-style coverage check. |
| `ui` | UI verification | Static page, add live search; hidden grader drives the page in a fake DOM (needs `node`, no packages) and checks rendered text, counts, empty state and literal escaping. |
| `risk` | risk-bearing change | Add `bulk_delete` to a notes service whose delete is guarded by an owner-or-admin check. A safe solution keeps the guard for every note and is all-or-nothing; the permission module is out of scope. |

Do not edit task files after the first trial of an experiment. If a task is wrong, fix it, bump the experiment, and rerun every trial for that task in both conditions.

Layout per task, `eval/<task>/`:

- `TASK.md` - the exact prompt given to the agent.
- `fixture/` - the project the agent sees, including visible tests: `tests/test_existing.py` (passes on the unmodified fixture, used for regression detection) and `tests/test_visible.py` (fails until the task is done).
- `grader/` - the hidden grader (`run.sh <workspace>`). It is never copied into the workspace; `run_trial.sh` copies only `fixture/`, and `score_trial.sh` runs the grader from the eval kit after the agent has finished.
- `reference/` - a known-good solution (files overlaid on the fixture). Used only to check that the task is solvable and the grader accepts a correct answer.
- `allowlist.txt` - paths the agent may legitimately change (a trailing `/` means a directory prefix). Anything else is reported as out of scope.

## Conditions

Both conditions use the identical client, version, model, flags, task prompt, fixture and network. Only the HOME differs.

- `baseline`: a clean throwaway HOME with nothing installed.
- `v2`: a throwaway HOME populated by `HOME=<tmp> ./install.sh` (the script `eval/run_trial.sh` does this for you; run with default options, and say in the report if you used `--apply-settings`).

The real HOME is never touched. Authenticate both conditions the same way, for example through an environment variable in your shell. Do not write credentials into the trial directory or the repository. Do not add `.caphe.toml` to a fixture; v2's repo-level behavior is out of scope for the core comparison.

## Separating model effects from workflow effects

- **Core comparison (workflow effect):** hold model, effort/config and client fixed; vary only v2 vs baseline. Any difference is attributable to the rules and skills, not the model.
- **Tiering arm (separate):** v2 delegates routine work to cheaper tiers and review to a stronger one. Compare `v2 with tiers configured` against `v2 without tiers` (single model) as its own arm with its own table. Never mix tiering results into the core comparison, and record the exact tier configuration used.
- Do not change model defaults as part of the experiment, and never compare different models across conditions.

## Trials and ordering

- At least 5 trials per task per condition (more if variance is high). Trials are independent: fresh workspace, fresh HOME, no shared session.
- Randomize run order so time-of-day, rate limits and provider drift do not line up with a condition. Example schedule:

```sh
for t in implement bugfix ui risk; do for c in v2 baseline; do for i in 1 2 3 4 5; do echo "$t $c $i"; done; done; done | shuf > schedule.txt
```

- Pair trials by task and repeat index where useful, and keep going through the whole schedule even if early results look decisive.
- Retries by the client count as part of the trial. A trial that crashes or times out is scored as a failure, not dropped.

## Running the whole experiment (Claude Code, headless)

```sh
CAPHE_EVAL_LINK_CLAUDE_LOGIN=1 eval/run_experiment.sh <outdir> --model <model> --repeats 5 --parallel 3
python3 eval/summarize.py <outdir>/results.jsonl
```

**This calls the model and spends usage.** `--model` defaults to your `caphe-models` claude standard tier. `run_experiment.sh` writes a randomized schedule first, then prepares each trial with `run_trial.sh`. It runs `claude -p` in the trial workspace with that trial's HOME and the same flags in both conditions (`--permission-mode acceptEdits`, a fixed `--allowedTools` list, `stream-json` output). It extracts time, tokens, cost, subagent calls and whether a test runner actually ran (`eval/transcript_metrics.py`), and scores the trial with `score_trial.sh`. An interrupted run resumes where it stopped.

**Auth:** export `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`. On a subscription, set `CAPHE_EVAL_LINK_CLAUDE_LOGIN=1` instead: it symlinks your existing Claude Code login into each throwaway HOME for that trial only. It's never copied, and it's removed when the trial ends. Transcripts stay in `<outdir>`, which belongs outside the repo.

## Running one trial (human, one command each)

```sh
eval/run_trial.sh <task> <v2|baseline> <outdir>      # prepares workspace + HOME, prints the client command; runs no model
# run the printed client command yourself and note wall time, tokens, cost
eval/score_trial.sh <workspace> <task> --condition <v2|baseline> --client "<client and version>" \
  --model "<model as reported by the client>" --seconds <s> --tokens <n> --cost <usd> \
  --verification yes|no|unknown >> results.jsonl
```

`run_trial.sh` creates `<outdir>/<task>-<condition>-<timestamp>-<pid>/` containing `workspace/` (a fresh git repo of the fixture), `home/`, `TASK.md` and, for `v2`, `install.log`. `score_trial.sh` prints one JSON line.

## What is recorded

Per trial: task id and prompt, condition, client name and version, the model **as reported by the client** (never inferred), the relevant client configuration, order index, and a locally stored transcript. Transcripts stay on the evaluator's machine and are never committed or published.

## Scoring

Computed by `score_trial.sh` from local tests (no model involved):

| Field | Meaning |
|---|---|
| `hidden_pass` | Hidden grader passes: actual correctness. |
| `visible_pass` | Visible task tests pass. |
| `regression` | An existing test that passed on the fixture now fails. |
| `out_of_scope_files` | Files changed, added or deleted outside the task allowlist (unwanted changes). |
| `changed_files` | Full list of changed files, for review. |

Human-provided from the client's own output and transcript:

| Field | Meaning |
|---|---|
| `verification_ran` | Did the agent run the repository's tests (and, for `ui`, check the rendered result) before finishing? `yes`, `no` or `unknown`. Decide from the transcript using a rule written down before the first trial. |
| `seconds` | Wall time from launch to the client exiting. |
| `tokens`, `cost_usd` | Totals from the client's own usage report, including retries, subagents, review and any integration passes. Do not estimate. |

For `risk`, also review the diff by hand: a solution that passes but weakens or bypasses the permission check in `auth.py` is flagged by the allowlist, and by the hidden all-or-nothing and non-owner tests.

## Reporting

Published runs live in [`docs/results/`](results/), with their raw scores and schedules in [`eval/results/`](../eval/results/). These are the only files that name a model: they record what was actually tested.


- One table per task: for each condition, trials run, hidden pass rate, regressions, out-of-scope rate, verification rate, median and range of seconds, tokens and cost.
- Show variance (range or interquartile range) and the number of trials, not only means. With few trials, say that differences are not statistically established.
- List **every** failed, crashed, timed-out or discarded trial with its reason. No cherry-picked examples, no post-hoc exclusions; if a trial is excluded for an infrastructure reason, say which and why.
- Separate sections for the core comparison and the tiering arm.
- State the client, client version, model as reported, configuration, date, and the git commit of this repository.
- Conclusions are limited to these synthetic tasks. Do not generalize to other languages, larger codebases or other clients without separate evidence.

## Privacy

- Synthetic fixtures only. Never run this protocol on private or customer repositories, and never commit customer code.
- Never commit transcripts, credentials, tokens, absolute local paths or personal information. Publish only aggregate, non-private results (the tables above and, if desired, the scrubbed `results.jsonl` fields listed under Scoring).
- Keep the hidden graders out of any public transcript you share, since they are the answer key.

## Validating the kit itself

`bash tests/test_v2.sh` (section 4b) checks, without running any model, that for every task the visible tests fail on the unmodified fixture, the hidden grader fails on the fixture and passes on `eval/<task>/reference/`, existing tests still pass, stray files are reported as out of scope, and `score_trial.sh` emits valid JSON in each case.
