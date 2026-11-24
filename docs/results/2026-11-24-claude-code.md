# Results: 2026-11-24, Claude Code + `sonnet`

Protocol: [docs/evaluation.md](../evaluation.md). Tracking issue: #39.

**Setup:**
- **Client and model:** `claude-code 2.1.331`, `--model sonnet`, reported by the client as `claude-sonnet-5-5`.
- **Trials:** 4 tasks × 2 conditions × 5 = 40, in a randomized order fixed before the first run ([`eval/results/2026-11-24-schedule.txt`](../../eval/results/2026-11-24-schedule.txt)), 3 at a time.
- **Code:** repository at `c318626`, plus the experiment driver from the PR that published these results.
- **What differs between conditions:** v2 = default `./install.sh` into the trial HOME (canon, 6 skills, `explorer`/`worker`/`reviewer` agents, no `--apply-settings`). Baseline = empty HOME. Client, model, flags and auth were identical.
- **Raw scores:** [`eval/results/2026-11-24-claude-code.jsonl`](../../eval/results/2026-11-24-claude-code.jsonl). That file holds scores only. Transcripts stay local.

**Trials:** 40 · **Client:** claude-code 2.1.331 · **Model (as reported):** claude-sonnet-5-5

Medians with (min–max). Cost is the client-reported `total_cost_usd`.

| Task | Condition | n | Hidden tests pass | Regressions | Ran verification | Out-of-scope edits | Subagent calls | Wall time, s | Tokens | Cost, USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bugfix | baseline | 5 | 5/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 13 (10–15) | 105k (94k–106k) | 0.085 (0.065–0.087) |
| bugfix | v2 | 5 | 5/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 14 (11–14) | 108k (96k–111k) | 0.090 (0.069–0.090) |
| implement | baseline | 5 | 5/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 11 (10–13) | 103k (94k–104k) | 0.076 (0.065–0.081) |
| implement | v2 | 5 | 5/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 11 (10–14) | 107k (96k–109k) | 0.080 (0.068–0.087) |
| risk | baseline | 5 | 5/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 13 (10–17) | 106k (103k–118k) | 0.084 (0.071–0.091) |
| risk | v2 | 5 | 4/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 14 (10–16) | 120k (107k–137k) | 0.088 (0.069–0.092) |
| ui | baseline | 5 | 5/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 20 (17–24) | 165k (137k–199k) | 0.098 (0.089–0.109) |
| ui | v2 | 5 | 5/5 | 0/5 | 5/5 | 0/5 | 0 (0–0) | 17 (15–28) | 138k (127k–265k) | 0.099 (0.086–0.126) |

| All tasks | Condition | n | Hidden tests pass | Regressions | Ran verification | Out-of-scope edits | Subagent calls | Wall time, s | Tokens | Cost, USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | baseline | 20 | 20/20 | 0/20 | 20/20 | 0/20 | 0 (0–0) | 13 (10–24) | 105k (94k–199k) | 0.084 (0.065–0.109) |
| all | v2 | 20 | 19/20 | 0/20 | 20/20 | 0/20 | 0 (0–0) | 14 (10–28) | 109k (96k–265k) | 0.088 (0.068–0.126) |

**Client errors / timeouts:** none.

Median v2 vs. baseline: tokens **+3%**, cost **+4%**, wall time **+4%** overall. By task: bugfix +3% tokens / +6% cost, implement +4% / +4%, risk +13% / +5%, ui −16% / +2%. The total client-reported cost of all 40 trials was $3.41. On a subscription that figure is the client's notional cost, not a bill.

## What this shows

- **No measurable benefit on these tasks.** Both conditions solved essentially everything (baseline 20/20, v2 19/20 hidden-test passes). Neither caused a regression or an out-of-scope edit. With 5 trials per cell, the difference is not statistically meaningful in either direction.
- **v2 costs a little more on small tasks.** The always-loaded canon and skill headers add context to every turn, and on 10–20 second tasks that shows up as a few percent more tokens and cost. On `ui`, the longest task, v2's median tokens were lower, but with a wider range, so this run doesn't establish a saving.
- **The one failure (risk / v2 / rep 5)** kept the security property the task is about: it checks permission on every note and deletes nothing if any check fails. It failed the hidden test `test_missing_id_raises_keyerror_and_deletes_nothing` because it skipped unknown IDs instead of raising `KeyError` the way the existing `delete_note` does. `TASK.md` never specifies missing-ID behavior. The failure is counted as-is, since changing the grader after seeing the results would be cherry-picking.
- **Delegation never happened.** Neither condition made a single subagent call, so tiering (fast/standard/frontier) was not exercised at all. Its cost effect is untested.

## Limitations, and what the next run should change

- **Verification hit a ceiling.** Every `TASK.md` ends with "Run the repository's tests", so both conditions ran tests 40/40 times. That measures the prompt, not the canon. A follow-up run should drop that sentence, so the canon's "oracles over prose" rule is what's being tested.
- **The tasks are small.** Single-file changes of 10–30 seconds don't exercise long sessions, delegation or the risk-review rules. A tiering arm needs multi-step tasks, where an orchestrator plausibly delegates.
- **The risk task is ambiguous.** It should say whether missing IDs are skipped or raise, so the grader tests safety, not a guess.
- **Measurement fix made before publishing.** The first version of the verification detector also counted *reading* test files (`cat tests/test_x.py`) as running them. It was tightened to require a real test-runner invocation, now in `eval/transcript_metrics.py`, and all 40 saved transcripts were re-scored. All 40 still ran a test runner, and the correctness and regression results were identical on re-scoring.
- **Scope:** one client, one model, one machine, one date, synthetic Python/JS fixtures. Don't generalize beyond that.
