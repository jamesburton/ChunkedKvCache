"""Per-corpus difficulty summary of the Task 8 reference run: python -I summarize.py afclaude docagent codesharp > summary.md"""
import csv
import json
import statistics
import sys
from pathlib import Path

here = Path(__file__).parent
print("| corpus | tasks validated | plans | ref EM with chunk | ref EM without | mean mask NLL with / without (nats) | median NLL gain | "
      "mean cont. NLL/token with / without | kept | reference-fails | solved-without | below-margin | mean s/plan |")
print("|---|---:|---:|---:|---:|---|---:|---|---:|---:|---:|---:|---:|")
for name in sys.argv[1:]:
    rows = list(csv.DictReader(open(here / f"{name}.validation.csv", encoding="utf-8")))
    # Actual continuation length per task (shorter than 32 near the end of a file), from the plans.
    clen = {t["id"]: t["continuationTokens"] for line in open(here / f"{name}.plans.jsonl", encoding="utf-8")
            for t in json.loads(line)["tasks"]}
    n = len(rows)
    f = lambda k: [float(r[k]) for r in rows]
    em_w = sum(r["EmWith"] == "1" for r in rows)
    em_o = sum(r["EmWithout"] == "1" for r in rows)
    reasons = {k: sum(r["Reason"] == k for r in rows) for k in ("kept", "reference-fails", "solved-without", "below-margin")}
    plans = {r["Plan"]: float(r["PlanSeconds"]) for r in rows}
    cont_w = statistics.mean(float(r["ContNllWith"]) / clen[r["TaskId"]] for r in rows)
    cont_o = statistics.mean(float(r["ContNllWithout"]) / clen[r["TaskId"]] for r in rows)
    print(f"| {name} | {n} | {len(plans)} | {em_w} ({100*em_w/n:.0f} %) | {em_o} ({100*em_o/n:.0f} %) | "
          f"{statistics.mean(f('MaskNllWith')):.2f} / {statistics.mean(f('MaskNllWithout')):.2f} | {statistics.median(f('NllGain')):.2f} | "
          f"{cont_w:.3f} / {cont_o:.3f} | **{reasons['kept']} ({100*reasons['kept']/n:.0f} %)** | {reasons['reference-fails']} | "
          f"{reasons['solved-without']} | {reasons['below-margin']} | {statistics.mean(plans.values()):.1f} |")
