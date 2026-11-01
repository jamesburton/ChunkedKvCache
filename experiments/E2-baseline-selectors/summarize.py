"""Summarise E2 results.csv: mean and [min, max] over seeds per (size, method), as Markdown tables.

Usage: python -I summarize.py results.csv > summary.md
"""
import csv
import sys
from collections import defaultdict

rows = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
groups = defaultdict(list)
for r in rows:
    sel = r["Selector"] or r["Method"]
    name = sel + ("+runs" if r["Contiguous"] == "1" else "")
    pct = float(r["BudgetPct"])
    groups[(int(r["ContextTokens"]), name, pct)].append(r)


def stat(rs, key, fmt):
    v = [float(r[key]) for r in rs if r[key] != ""]
    if not v:
        return ""
    return f"{fmt.format(sum(v) / len(v))} [{fmt.format(min(v))}, {fmt.format(max(v))}]"


order = ["full", "noise_prefill_block128", "noise_recompute_all", "naive_concat"]
sizes = sorted({k[0] for k in groups})
for size in sizes:
    print(f"\n### {size} tokens\n")
    print("| method | budget % | tokens | n | KL (nats) mean [min, max] | KL post-query | top-1 | top-1 post-query | greedy EM | J(oracle) | fwd calls | recompute s |")
    print("|---|---:|---:|---:|---|---|---|---|---|---|---:|---:|")
    keys = [k for k in groups if k[0] == size]
    keys.sort(key=lambda k: (order.index(k[1]) if k[1] in order else len(order), k[1], k[2]))
    for k in keys:
        rs = groups[k]
        calls = sum(int(r["ForwardCalls"]) for r in rs) / len(rs)
        rec = sum(float(r["RecomputeMs"]) for r in rs) / len(rs) / 1000
        toks = sum(int(r["BudgetTokens"]) for r in rs) / len(rs)
        print(f"| {k[1]} | {k[2]:.1f} | {toks:.0f} | {len(rs)} | {stat(rs, 'MeanKl', '{:.4f}')} | {stat(rs, 'KlPostQuery', '{:.4f}')} | "
              f"{stat(rs, 'Top1Agreement', '{:.3f}')} | {stat(rs, 'Top1PostQuery', '{:.3f}')} | {stat(rs, 'ExactMatch', '{:.2f}')} | "
              f"{stat(rs, 'OracleJaccard', '{:.2f}')} | {calls:.0f} | {rec:.1f} |")

# Compact matrices: selector x budget, per size (mean; share of the naive-concat value removed, mean of per-seed ratios).
# First KL over all 64 rows, then KL over the post-query rows 16-63 only (rows 0-15 are the query the query-relevance
# selector was built from, an in-sample advantage for it).
for col, title in (("MeanKl", "Mean KL, all 64 rows"), ("KlPostQuery", "Mean KL, post-query rows 16-63")):
    print(f"\n### {title}, by selector and budget (share of the naive-concat value removed, mean over seeds of per-seed ratios)\n")
    for size in sizes:
        naive = {r["Seed"]: float(r[col]) for r in rows if int(r["ContextTokens"]) == size and r["Method"] == "naive_concat"}
        budgets = sorted({k[2] for k in groups if k[0] == size and k[2] in (5.0, 10.0, 15.0, 20.0)})
        names = sorted({k[1] for k in groups if k[0] == size and k[1] not in order})
        print(f"\n{size} tokens (naive mean {sum(naive.values()) / len(naive):.4f})\n")
        print("| selector | " + " | ".join(f"{b:.0f}%" for b in budgets) + " |")
        print("|---|" + "---:|" * len(budgets))
        for n in names:
            cells = []
            for b in budgets:
                rs = groups.get((size, n, b), [])
                if not rs:
                    cells.append("")
                    continue
                kl = sum(float(r[col]) for r in rs) / len(rs)
                rec = sum(1 - float(r[col]) / naive[r["Seed"]] for r in rs) / len(rs)
                cells.append(f"{kl:.4f} ({rec:+.0%})")
            print(f"| {n} | " + " | ".join(cells) + " |")
