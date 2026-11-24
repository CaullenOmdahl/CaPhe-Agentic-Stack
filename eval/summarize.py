#!/usr/bin/env python3
"""Summarize eval results.jsonl (from run_experiment.sh / score_trial.sh) as Markdown tables.

Usage: python3 eval/summarize.py results.jsonl
Reports every trial: no filtering, no cherry-picking. Medians with min-max ranges show variance.
"""
import json
import statistics
import sys
from collections import defaultdict


def notes(d):
    return dict(kv.split("=", 1) for kv in (d.get("notes") or "").split(";") if "=" in kv)


def rate(rows, pred):
    hits = sum(1 for r in rows if pred(r))
    return f"{hits}/{len(rows)}"


def spread(values, fmt):
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return "n/a"
    med = statistics.median(values)
    return f"{fmt(med)} ({fmt(min(values))}–{fmt(max(values))})"


def table(groups, label):
    out = [f"| {label} | Condition | n | Hidden tests pass | Regressions | Ran verification | Out-of-scope edits | Subagent calls | Wall time, s | Tokens | Cost, USD |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for (key, cond), rows in sorted(groups.items()):
        out.append("| " + " | ".join([
            key, cond, str(len(rows)),
            rate(rows, lambda r: r["hidden_pass"]),
            rate(rows, lambda r: r["regression"]),
            rate(rows, lambda r: r["verification_ran"] == "yes"),
            rate(rows, lambda r: bool(r["out_of_scope_files"])),
            spread([int(notes(r).get("subagents", 0)) for r in rows], lambda v: f"{v:g}"),
            spread([r["seconds"] for r in rows], lambda v: f"{v:.0f}"),
            spread([r["tokens"] for r in rows], lambda v: f"{v / 1000:.0f}k"),
            spread([r["cost_usd"] for r in rows], lambda v: f"{v:.3f}"),
        ]) + " |")
    return "\n".join(out)


def main() -> int:
    rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
    by_task, overall = defaultdict(list), defaultdict(list)
    for r in rows:
        by_task[(r["task"], r["condition"])].append(r)
        overall[("all", r["condition"])].append(r)
    clients = sorted({r.get("client") or "?" for r in rows})
    models = sorted({r.get("model") or "?" for r in rows})
    errors = [r for r in rows if notes(r).get("client_exit", "0") != "0" or notes(r).get("is_error") == "True"]
    print(f"**Trials:** {len(rows)} · **Client:** {', '.join(clients)} · **Model (as reported):** {', '.join(models)}\n")
    print("Medians with (min–max). Cost is the client-reported `total_cost_usd`.\n")
    print(table(by_task, "Task") + "\n")
    print(table(overall, "All tasks") + "\n")
    if errors:
        print(f"**Client errors / timeouts:** {len(errors)} trial(s): "
              + ", ".join(f"{r['task']}/{r['condition']}/rep {notes(r).get('rep')}" for r in errors))
    else:
        print("**Client errors / timeouts:** none.")
    oos = [(r["task"], r["condition"], f) for r in rows for f in r["out_of_scope_files"]]
    if oos:
        print("\n**Out-of-scope files seen:** " + ", ".join(sorted({f"`{f}` ({t}/{c})" for t, c, f in oos})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
