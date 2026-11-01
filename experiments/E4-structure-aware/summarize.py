# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.1.3", "pandas==2.2.3"]
# ///
"""E4 summary: merges the raw per-job CSVs of `ChunkKvLab e4` and writes results.csv.gz, curves.csv, pairs.csv,
overhead.csv and summary.md into this folder.

Usage: uv run summarize.py <raw dir> [<raw dir> ...]

Instance = one task in one context (corpus, chunker, seed, mode, plan, task). Sets:
  kept-valid  : mode kept, and the task is valid in THIS context (full EM = 1, EM without the required chunk = 0, masked NLL
                gain >= ln 2: the Task 8 filter re-applied per seed/chunker; for symbol/seed 0 it reproduces Task 8)
  kept-all    : mode kept, no re-validation (sensitivity)
  unfiltered  : mode unfiltered, every generated task (sensitivity)
Normalisation (Boxoffice-style): share of the naive->full gap recovered, as a ratio of means
  gap_nll = (mean NLL_naive - mean NLL_arm) / (mean NLL_naive - mean NLL_full)   (masked-call NLL)
  gap_em  = (EM_arm - EM_naive) / (EM_full - EM_naive)
95 % CIs: cluster bootstrap (2000 resamples; cluster = corpus | file of the required definition, so the same definition's
tasks across seeds, chunkers and contexts move together); comparisons between arms are paired (same instances).
"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
REPS = 2000
RNG = np.random.default_rng(20261101)
BASELINES = ["first_k", "chunk_starts", "deviation", "random", "query"]
GRAPH_ARMS = ["graph", "hybrid_query", "hybrid_dev"]
ORDER = ["naive", "drop_required", "first_k", "chunk_starts", "deviation", "random", "query", "graph", "hybrid_query", "hybrid_dev",
         "oracle_def_fill", "oracle_def", "oracle_chunk", "full"]
LN2 = math.log(2)


def load(dirs):
    frames = [pd.read_csv(p) for d in dirs for p in sorted(Path(d).glob("*.csv"))]
    df = pd.concat(frames, ignore_index=True)
    df["inst"] = (df.corpus + "/" + df.chunker + "/s" + df.seed.astype(str) + "/" + df["mode"] + "/p" + df.plan.astype(str) + "/"
                  + df.task_id)
    dup = df.duplicated(["inst", "arm", "budget_pct"])
    if dup.any():
        raise SystemExit(f"duplicate rows: {dup.sum()}")
    return df


def instances(df):
    full = df[df.arm == "full"].set_index("inst")
    drop = df[df.arm == "drop_required"].set_index("inst")
    inst = full[["corpus", "chunker", "seed", "mode", "plan", "task_id", "cluster", "context_tokens", "chunks", "required_first",
                 "query_targets", "query_edges", "in_context_edges", "mask_tokens"]].copy()
    inst["full_nll"] = full.mask_nll
    inst["full_em"] = full.mask_em
    inst["drop_nll"] = drop.mask_nll.reindex(inst.index)
    inst["drop_em"] = drop.mask_em.reindex(inst.index)
    # Without a drop_required row (symbol/seed 0: Task 8's own contexts, validated there) only the full-prefill EM is re-checked.
    redo = (inst.drop_em == 0) & (inst.drop_nll - inst.full_nll >= LN2 - 1e-9)
    inst["valid"] = (inst.full_em == 1) & (redo | inst.drop_em.isna())
    return inst


def wide(df, inst, metric):
    """instance x (arm, budget) table of one metric; budget-free arms keyed with their own label."""
    d = df.copy()
    d["col"] = d.arm + "@" + d.budget_pct.round(2).astype(str)
    fixed = d.arm.isin(["full", "naive", "drop_required", "oracle_def", "oracle_chunk"])
    d.loc[fixed, "col"] = d.loc[fixed, "arm"]
    return d.pivot(index="inst", columns="col", values=metric).reindex(inst.index).astype(float)


def boot_idx(clusters):
    """REPS resamples of instance indices, resampling whole clusters."""
    codes, uniq = pd.factorize(clusters)
    members = [np.flatnonzero(codes == k) for k in range(len(uniq))]
    draws = RNG.integers(0, len(uniq), size=(REPS, len(uniq)))
    return [np.concatenate([members[k] for k in row]) for row in draws]


def ratio_ci(num, den, idx):
    """point and 95 % CI of sum(num)/sum(den) (num, den per instance)."""
    point = np.nansum(num) / np.nansum(den) if np.nansum(den) != 0 else np.nan
    vals = [np.nansum(num[i]) / np.nansum(den[i]) if np.nansum(den[i]) != 0 else np.nan for i in idx]
    lo, hi = np.nanpercentile(vals, [2.5, 97.5])
    return point, lo, hi


def mean_ci(x, idx):
    point = np.nanmean(x)
    vals = [np.nanmean(x[i]) if (~np.isnan(x[i])).any() else np.nan for i in idx]
    lo, hi = np.nanpercentile(vals, [2.5, 97.5])
    return point, lo, hi


def fmt(p, lo, hi, digits=2):
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "-"
    return f"{p:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def curves(df, inst, sel, label, idx):
    nll, em = wide(df, inst, "mask_nll")[sel], wide(df, inst, "mask_em")[sel]
    kl, top1 = wide(df, inst, "kl_cont")[sel], wide(df, inst, "top1_cont")[sel]
    rows = []
    n_naive, n_full = nll["naive"].to_numpy(), nll["full"].to_numpy()
    e_naive, e_full = em["naive"].to_numpy(), em["full"].to_numpy()
    for col in nll.columns:
        x = nll[col].to_numpy()
        have = ~np.isnan(x)
        if have.sum() < 2:
            continue
        e = em[col].to_numpy()
        arm, _, b = col.partition("@")
        miss = lambda v: np.where(have, v, np.nan)  # an arm run on only some cells is scored on the instances it ran on
        g = ratio_ci(n_naive - x, miss(n_naive - n_full), idx)
        ge = ratio_ci(e - e_naive, miss(e_full - e_naive), idx)
        emm = mean_ci(e, idx)
        dn = mean_ci(x - n_full, idx)
        rows.append(dict(set=label, arm=arm, budget=float(b) if b else np.nan, n=int(have.sum()), clusters=len(set(inst.loc[sel, "cluster"])),
                         gap_nll=g[0], gap_nll_lo=g[1], gap_nll_hi=g[2], gap_em=ge[0], gap_em_lo=ge[1], gap_em_hi=ge[2],
                         em=emm[0], em_lo=emm[1], em_hi=emm[2], dnll=dn[0], dnll_lo=dn[1], dnll_hi=dn[2],
                         kl_cont=kl[col].mean(), top1_cont=top1[col].mean(), naive_em=np.nanmean(miss(e_naive)), full_em=np.nanmean(miss(e_full))))
    return rows


def pairs(df, inst, sel, label, idx, budgets):
    nll, em = wide(df, inst, "mask_nll")[sel], wide(df, inst, "mask_em")[sel]
    full = nll["full"].to_numpy()
    rows = []
    def gap(col):
        h = nll[col].notna()
        return (nll["naive"] - nll[col])[h].sum() / (nll["naive"] - nll["full"])[h].sum()
    for b in budgets:
        key = f"{float(b)}"
        have = [a for a in BASELINES if f"{a}@{key}" in nll and nll[f"{a}@{key}"].notna().all()]
        if not have:
            continue
        best = max(have, key=lambda a: gap(f"{a}@{key}"))
        cmp = [("graph", "query"), ("graph", "chunk_starts"), ("hybrid_query", "query"), ("hybrid_dev", "deviation"),
               ("graph", best), ("hybrid_query", best), ("hybrid_dev", best), ("oracle_def_fill", "chunk_starts"), ("oracle_def_fill", "graph"),
               ("query", "chunk_starts")]
        for a, base in dict.fromkeys(cmp):
            ca, cb = f"{a}@{key}", f"{base}@{key}"
            if ca not in nll or cb not in nll:
                continue
            both = (nll[ca].notna() & nll[cb].notna()).to_numpy()
            if both.sum() < 2:
                continue
            d = np.where(both, (nll[ca] - nll[cb]).to_numpy(), np.nan)
            de = np.where(both, (em[ca] - em[cb]).to_numpy(), np.nan)
            dg = ratio_ci(d * -1, np.where(both, (nll["naive"] - nll["full"]).to_numpy(), np.nan), idx)
            dn, dem = mean_ci(d, idx), mean_ci(de, idx)
            rows.append(dict(set=label, budget=b, arm=a, baseline=base, best_baseline=best, n=int(both.sum()), d_gap=dg[0], d_gap_lo=dg[1],
                             d_gap_hi=dg[2], d_nll=dn[0], d_nll_lo=dn[1], d_nll_hi=dn[2], d_em=dem[0], d_em_lo=dem[1], d_em_hi=dem[2],
                             em_wins=int(np.nansum(de > 0)), em_losses=int(np.nansum(de < 0)),
                             nll_better=int(np.nansum(d < -1e-6)), nll_worse=int(np.nansum(d > 1e-6))))
    return rows


def lower_budget(df, inst, sel, label, idx, budgets):
    """Does an arm at budget b match the best baseline at a larger budget b2 (CI of the gap difference includes or exceeds 0)?"""
    nll = wide(df, inst, "mask_nll")[sel]
    den = (nll["naive"] - nll["full"]).to_numpy()
    rows = []
    for a in GRAPH_ARMS:
        for b in budgets:
            ca = f"{a}@{float(b)}"
            if ca not in nll or nll[ca].notna().sum() < 2:
                continue
            for b2 in budgets:
                if b2 <= b:
                    continue
                for base in BASELINES:
                    cb = f"{base}@{float(b2)}"
                    if cb not in nll:
                        continue
                    both = (nll[ca].notna() & nll[cb].notna()).to_numpy()
                    if both.sum() < 2:
                        continue
                    dg = ratio_ci(np.where(both, nll[cb].to_numpy() - nll[ca].to_numpy(), np.nan), np.where(both, den, np.nan), idx)
                    rows.append(dict(set=label, arm=a, budget=b, baseline=base, baseline_budget=b2, d_gap=dg[0], d_gap_lo=dg[1], d_gap_hi=dg[2]))
    return rows


def main(dirs):
    df = load(dirs)
    inst = instances(df)
    df.to_csv(HERE / "results.csv.gz", index=False)
    budgets = sorted(b for b in df.budget_pct.unique() if b in (5.0, 10.0, 15.0, 20.0))

    sets = {
        "kept-valid": (inst["mode"] == "kept") & inst.valid,
        "kept-all": inst["mode"] == "kept",
        "unfiltered": inst["mode"] == "unfiltered",
        # what the graph signal can add: instances whose query prefix references a symbol declared in a stale context chunk
        "kept-valid-targets": (inst["mode"] == "kept") & inst.valid & (inst.query_targets > 0),
        "kept-valid-notargets": (inst["mode"] == "kept") & inst.valid & (inst.query_targets == 0),
    }
    cur, prs, low = [], [], []
    for sname, smask in sets.items():
        for chunker in ["symbol", "fixed", "both"]:
            for corpus in ["afclaude", "docagent", "codesharp", "pooled"]:
                sel = smask & ((inst.chunker == chunker) if chunker != "both" else True) & ((inst.corpus == corpus) if corpus != "pooled" else True)
                sel = sel.to_numpy() if hasattr(sel, "to_numpy") else sel
                if sel.sum() < 2:
                    continue
                label = f"{sname}|{chunker}|{corpus}"
                idx = boot_idx(inst.loc[sel, "cluster"].to_numpy())
                cur += curves(df, inst, sel, label, idx)
                if corpus == "pooled" or sname == "kept-valid":
                    prs += pairs(df, inst, sel, label, idx, budgets)
                if corpus == "pooled" and sname == "kept-valid":
                    low += lower_budget(df, inst, sel, label, idx, budgets)
    cur, prs, low = pd.DataFrame(cur), pd.DataFrame(prs), pd.DataFrame(low)
    cur.to_csv(HERE / "curves.csv", index=False, float_format="%.5g")
    prs.to_csv(HERE / "pairs.csv", index=False, float_format="%.5g")
    low.to_csv(HERE / "lower-budget.csv", index=False, float_format="%.5g")

    # Overhead and cost per arm (contexts, not instances, for score/selection; recompute per distinct selection).
    d = df[~df.arm.isin(["full", "naive", "drop_required"])].copy()
    own = d.arm.isin(["oracle_def", "oracle_chunk"])
    d.loc[own, "budget_pct"] = -1.0  # own budget: one row per arm (mean budget in budget_tokens_mean)
    ov = d.groupby(["arm", "budget_pct"]).agg(rows=("inst", "size"), score_ms_median=("score_ms", "median"),
                                              select_ms_median=("select_ms", "median"), select_ms_max=("select_ms", "max"),
                                              forward_calls_mean=("forward_calls", "mean"), recompute_ms_mean=("recompute_ms", "mean"),
                                              memo_share=("memo", "mean"), graph_picks_mean=("graph_picks", "mean"),
                                              budget_tokens_mean=("budget_tokens", "mean")).reset_index()
    ov.to_csv(HERE / "overhead.csv", index=False, float_format="%.5g")

    write_summary(df, inst, sets, cur, prs, low, ov, budgets)


def table(cur, label, metric, budgets, arms=ORDER):
    c = cur[cur.set == label]
    out = [f"| arm | " + " | ".join(f"{b:g} %" for b in budgets) + " | own budget |", "|---|" + "---:|" * (len(budgets) + 1)]
    for a in arms:
        r = c[c.arm == a]
        if r.empty:
            continue
        cells = []
        for b in budgets:
            x = r[r.budget == b]
            cells.append(fmt(x[metric].iloc[0], x[metric + "_lo"].iloc[0], x[metric + "_hi"].iloc[0]) if not x.empty else "")
        x = r[r.budget.isna()]
        cells.append(fmt(x[metric].iloc[0], x[metric + "_lo"].iloc[0], x[metric + "_hi"].iloc[0]) if not x.empty else "")
        out.append(f"| {a} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def write_summary(df, inst, sets, cur, prs, low, ov, budgets):
    L = []
    w = L.append
    w("# E4 summary (generated by summarize.py; do not edit)\n")
    w("## Instances\n")
    w("| corpus | chunker | seed | mode | contexts | instances | valid (re-validated) | full EM | EM without required | query targets > 0 |")
    w("|---|---|---:|---|---:|---:|---:|---:|---:|---:|")
    for (c, ch, s, m), g in inst.groupby(["corpus", "chunker", "seed", "mode"]):
        w(f"| {c} | {ch} | {s} | {m} | {g.plan.nunique()} | {len(g)} | {int(g.valid.sum())} | {g.full_em.mean():.2f} | "
          f"{g.drop_em.mean():.2f} | {(g.query_targets > 0).mean():.2f} |")
    for sname, smask in sets.items():
        g = inst[smask]
        if len(g):
            w(f"\n{sname}: {len(g)} instances, {g.task_id.nunique()} distinct tasks, {g.cluster.nunique()} clusters (definition files).")
    w("")
    for label in [l for l in cur.set.unique()]:
        if not (label.endswith("|pooled") or label.startswith("kept-valid|")):
            continue
        n = cur[cur.set == label].n.iloc[0]
        k = cur[cur.set == label].clusters.iloc[0]
        w(f"## {label} (n = {n} instances, {k} clusters)\n")
        w("Share of the naive->full masked-call NLL gap recovered (ratio of means) [95 % cluster-bootstrap CI]:\n")
        w(table(cur, label, "gap_nll", budgets))
        w("\nMasked-call exact match (mean) [95 % CI]:\n")
        w(table(cur, label, "em", budgets))
        c = cur[cur.set == label]
        w("\nPost-query KL (32 continuation rows, mean nats) / top-1 agreement:\n")
        w("| arm | " + " | ".join(f"{b:g} %" for b in budgets) + " | own |")
        w("|---|" + "---:|" * (len(budgets) + 1))
        for a in ORDER:
            r = c[c.arm == a]
            if r.empty:
                continue
            cells = [f"{r[r.budget == b].kl_cont.iloc[0]:.3f} / {r[r.budget == b].top1_cont.iloc[0]:.3f}" if not r[r.budget == b].empty else ""
                     for b in budgets]
            x = r[r.budget.isna()]
            cells.append(f"{x.kl_cont.iloc[0]:.3f} / {x.top1_cont.iloc[0]:.3f}" if not x.empty else "")
            w(f"| {a} | " + " | ".join(cells) + " |")
        p = prs[prs.set == label]
        if not p.empty:
            w("\nPaired comparisons (arm - baseline; d_gap > 0 and d_nll < 0 favour the arm) [95 % CI]:\n")
            w("| budget | arm | baseline | d gap (NLL) | d masked NLL (nats) | d EM | EM wins/losses |")
            w("|---:|---|---|---|---|---|---|")
            for _, r in p.iterrows():
                base = r.baseline + (" (best)" if r.baseline == r.best_baseline else "")
                w(f"| {r.budget:g} | {r.arm} | {base} | {fmt(r.d_gap, r.d_gap_lo, r.d_gap_hi)} | {fmt(r.d_nll, r.d_nll_lo, r.d_nll_hi)} | "
                  f"{fmt(r.d_em, r.d_em_lo, r.d_em_hi)} | {r.em_wins}/{r.em_losses} |")
        w("")
    if not low.empty:
        w("## Lower-budget matches (kept-valid, pooled corpora): arm at b vs baseline at b2 > b, d gap [95 % CI]\n")
        w("| set | arm | b | baseline | b2 | d gap |")
        w("|---|---|---:|---|---:|---|")
        for _, r in low.iterrows():
            if r.d_gap_hi >= 0:
                w(f"| {r.set} | {r.arm} | {r.budget:g} | {r.baseline} | {r.baseline_budget:g} | {fmt(r.d_gap, r.d_gap_lo, r.d_gap_hi)} |")
        w("")
    w("## Overhead and recompute cost per arm\n")
    w("| arm | budget % | rows | score/probe ms (median) | selection ms (median / max) | forward calls (mean) | recompute ms (mean) | memo share | graph picks (mean) |")
    w("|---|---:|---:|---:|---|---:|---:|---:|---:|")
    for _, r in ov.iterrows():
        w(f"| {r.arm} | {'own' if r.budget_pct < 0 else f'{r.budget_pct:.1f}'} | {r.rows} | {r.score_ms_median:.0f} | {r.select_ms_median:.3f} / {r.select_ms_max:.2f} | "
          f"{r.forward_calls_mean:.0f} | {r.recompute_ms_mean:.0f} | {r.memo_share:.2f} | {r.graph_picks_mean:.1f} / {r.budget_tokens_mean:.0f} |")
    (HERE / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote summary.md, curves.csv ({len(cur)}), pairs.csv ({len(prs)}), lower-budget.csv ({len(low)}), overhead.csv")


if __name__ == "__main__":
    main(sys.argv[1:] or [str(HERE / "raw")])
