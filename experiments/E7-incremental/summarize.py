"""Summarise E7 rows (ChunkKvLab e7 CSV): re-encoded tokens per edit, symbol vs fixed, with distribution and a
file-clustered paired bootstrap. Stdlib only.

Usage: uv run summarize.py raw/codesharp.csv [--corpus-tokens symbol=N,fixed=M] > summary.md
"""
import csv
import random
import statistics
import sys
from collections import defaultdict

ARMS = ("symbol", "fixed")


def q(xs, p):
    """Linear-interpolated quantile (p in [0,1])."""
    s = sorted(xs)
    if not s:
        return float("nan")
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def dist_row(label, xs, fmt="{:.0f}"):
    cells = [statistics.fmean(xs), q(xs, 0.0), q(xs, 0.10), q(xs, 0.25), q(xs, 0.5), q(xs, 0.75), q(xs, 0.90), q(xs, 1.0)]
    return f"| {label} | " + " | ".join(fmt.format(c) for c in cells) + " |"


def cluster_bootstrap(rows, stat, reps=10000, seed=0):
    """Percentile CI of stat(rows) resampling files (clusters) with replacement."""
    by_file = defaultdict(list)
    for r in rows:
        by_file[r["file"]].append(r)
    clusters = list(by_file.values())
    rng = random.Random(seed)
    vals = []
    for _ in range(reps):
        sample = [r for _ in clusters for r in rng.choice(clusters)]
        vals.append(stat(sample))
    return q(vals, 0.025), q(vals, 0.975)


def main():
    path = sys.argv[1]
    corpus_tokens = {}
    if "--corpus-tokens" in sys.argv:
        spec = sys.argv[sys.argv.index("--corpus-tokens") + 1]
        corpus_tokens = {k: int(v) for k, v in (p.split("=") for p in spec.split(","))}
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in list(r.items()):
            if k not in ("file", "method", "kind"):
                r[k] = float(v)
    seeds = sorted({int(r["seed"]) for r in rows})
    print(f"Rows: {len(rows)} edits ({len(seeds)} seeds x {len(rows) // len(seeds)}), "
          f"{len({r['file'] for r in rows})} distinct files, {len({(r['file'], r['line']) for r in rows})} distinct methods.\n")

    print("### Re-encoded tokens per edit (all seeds pooled)\n")
    print("| chunker | mean | min | p10 | p25 | median | p75 | p90 | max |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for a in ARMS:
        print(dist_row(a, [r[f"{a}_reencoded_tokens"] for r in rows]))
    print(dist_row("edited method (incl. leading trivia)", [r["method_tokens"] for r in rows]))
    print(dist_row("edited file (after edit)", [r["file_tokens_after"] for r in rows]))
    print()

    print("### Per seed (mean / median re-encoded tokens)\n")
    print("| seed | symbol mean | symbol median | fixed mean | fixed median | fixed / symbol (ratio of means) |")
    print("|---:|---:|---:|---:|---:|---:|")
    for s in seeds:
        rs = [r for r in rows if r["seed"] == s]
        sm = statistics.fmean(r["symbol_reencoded_tokens"] for r in rs)
        fm = statistics.fmean(r["fixed_reencoded_tokens"] for r in rs)
        print(f"| {s} | {sm:.0f} | {q([r['symbol_reencoded_tokens'] for r in rs], .5):.0f} | {fm:.0f} | "
              f"{q([r['fixed_reencoded_tokens'] for r in rs], .5):.0f} | {fm / sm:.2f} |")
    print()

    def mean_of(a):
        return lambda rs: statistics.fmean(r[f"{a}_reencoded_tokens"] for r in rs)

    def diff(rs):
        return statistics.fmean(r["fixed_reencoded_tokens"] - r["symbol_reencoded_tokens"] for r in rs)

    def ratio(rs):
        return mean_of("fixed")(rs) / mean_of("symbol")(rs)

    print("### Paired comparison (bootstrap over files, 10,000 resamples, 95 % percentile CI)\n")
    print("| quantity | value | 95 % CI |")
    print("|---|---:|---|")
    for label, fn, fmt in (("symbol mean re-encoded tokens", mean_of("symbol"), "{:.0f}"),
                           ("fixed mean re-encoded tokens", mean_of("fixed"), "{:.0f}"),
                           ("fixed - symbol (mean of paired differences)", diff, "{:.0f}"),
                           ("fixed / symbol (ratio of means)", ratio, "{:.2f}")):
        lo, hi = cluster_bootstrap(rows, fn)
        print(f"| {label} | {fmt.format(fn(rows))} | {fmt.format(lo)} .. {fmt.format(hi)} |")
    def med_ratio(rs):
        return q([r["fixed_reencoded_tokens"] for r in rs], .5) / q([r["symbol_reencoded_tokens"] for r in rs], .5)

    def per_edit_ratio(rs):
        return q([r["fixed_reencoded_tokens"] / r["symbol_reencoded_tokens"] for r in rs], .5)

    for label, fn in (("fixed / symbol (ratio of medians)", med_ratio),
                      ("fixed / symbol (median of per-edit ratios)", per_edit_ratio)):
        lo, hi = cluster_bootstrap(rows, fn)
        print(f"| {label} | {fn(rows):.2f} | {lo:.2f} .. {hi:.2f} |")
    fixed_by_file = defaultdict(float)
    for r in rows:
        fixed_by_file[r["file"]] += r["fixed_reencoded_tokens"]
    top = max(fixed_by_file, key=fixed_by_file.get)
    rest = [r for r in rows if r["file"] != top]
    top_n = len(rows) - len(rest)
    top_tokens = max(r["file_tokens_after"] for r in rows if r["file"] == top)
    print(f"\nLargest contributor: `{top}` ({top_tokens:.0f} tokens), {top_n}/{len(rows)} edits, "
          f"{fixed_by_file[top] / sum(fixed_by_file.values()):.3f} of all fixed re-encoded tokens. Without it "
          f"({len(rest)} edits): symbol mean {mean_of('symbol')(rest):.0f}, fixed mean {mean_of('fixed')(rest):.0f}, "
          f"ratio of means {ratio(rest):.2f}, ratio of medians {med_ratio(rest):.2f}, median per-edit ratio {per_edit_ratio(rest):.2f}.")
    wins = sum(r["fixed_reencoded_tokens"] > r["symbol_reencoded_tokens"] for r in rows)
    ties = sum(r["fixed_reencoded_tokens"] == r["symbol_reencoded_tokens"] for r in rows)
    print(f"\nPer edit: fixed re-encodes more than symbol in {wins}/{len(rows)}, the same in {ties}, "
          f"less in {len(rows) - wins - ties}.\n")

    print("### By edit kind (mean / median re-encoded tokens)\n")
    print("| kind | edits | token delta of file (median) | symbol mean | symbol median | fixed mean | fixed median |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for k in ("insert", "delete", "modify"):
        rs = [r for r in rows if r["kind"] == k]
        if not rs:
            continue
        print(f"| {k} | {len(rs)} | {q([r['file_tokens_after'] - r['file_tokens_before'] for r in rs], .5):+.0f} | "
              f"{statistics.fmean(r['symbol_reencoded_tokens'] for r in rs):.0f} | {q([r['symbol_reencoded_tokens'] for r in rs], .5):.0f} | "
              f"{statistics.fmean(r['fixed_reencoded_tokens'] for r in rs):.0f} | {q([r['fixed_reencoded_tokens'] for r in rs], .5):.0f} |")
    print()

    print("### Cache hit rate after one edit\n")
    print("Chunk hit rate = share of the edited file's chunks still in the store; token hit rate = share of the edited file's "
          "tokens not re-encoded.\n")
    print("| chunker | chunks per edited file (median) | re-encoded chunks: mean / median / max | chunk hit rate, edited file (mean / median) | "
          "token hit rate, edited file (mean / median) |" + (" token hit rate, whole corpus (mean) |" if corpus_tokens else ""))
    print("|---|---:|---|---|---|" + ("---:|" if corpus_tokens else ""))
    for a in ARMS:
        ch = [1 - r[f"{a}_miss_chunks"] / r[f"{a}_file_chunks"] for r in rows]
        th = [1 - r[f"{a}_reencoded_tokens"] / r["file_tokens_after"] for r in rows]
        miss = [r[f"{a}_miss_chunks"] for r in rows]
        line = (f"| {a} | {q([r[f'{a}_file_chunks'] for r in rows], .5):.0f} | {statistics.fmean(miss):.2f} / {q(miss, .5):.0f} / {max(miss):.0f} | "
                f"{statistics.fmean(ch):.3f} / {q(ch, .5):.3f} | {statistics.fmean(th):.3f} / {q(th, .5):.3f} |")
        if corpus_tokens:
            ct = [1 - r[f"{a}_reencoded_tokens"] / corpus_tokens[a] for r in rows]
            line += f" {statistics.fmean(ct):.6f} |"
        print(line)
    print()

    multi = sum(r["symbol_miss_chunks"] > 1 for r in rows)
    over = [r for r in rows if r["method_tokens"] > 512]
    print(f"Symbol edits re-encoding more than one chunk: {multi}/{len(rows)}. Edited methods over 512 tokens (split "
          f"into several chunks): {len(over)}/{len(rows)}; for those, symbol re-encodes mean "
          f"{statistics.fmean(r['symbol_reencoded_tokens'] for r in over) if over else 0:.0f} of mean "
          f"{statistics.fmean(r['method_tokens'] for r in over) if over else 0:.0f} method tokens.\n")
    fx = [r["fixed_reencoded_tokens"] / r["file_tokens_after"] for r in rows]
    print(f"Fixed: share of the edited file re-encoded, median {q(fx, .5):.2f} (p10 {q(fx, .1):.2f}, p90 {q(fx, .9):.2f}).\n")
    print("Index update time per edit (re-chunk + key one file), ms, median / p90: "
          + ", ".join(f"{a} {q([r[f'{a}_update_ms'] for r in rows], .5):.1f} / {q([r[f'{a}_update_ms'] for r in rows], .9):.1f}" for a in ARMS)
          + ".")


if __name__ == "__main__":
    main()
