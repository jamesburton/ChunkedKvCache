# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.1.3", "pandas==2.2.3"]
# ///
"""E4b summary: the E4 arms on RELATED-chunk contexts, with the E4 random-context results as the control.

Usage: uv run summarize.py <E4b raw dir> [<E4b raw dir> ...]
Reads ../E4-structure-aware/results.csv.gz (random contexts, Task 11) as the control and writes results.csv.gz,
curves.csv, pairs.csv, contexts.csv and summary.md into this folder. Statistics (validity, ratio-of-means gap, cluster
bootstrap with cluster = corpus | definition file, paired comparisons) are E4's own functions (imported from
../E4-structure-aware/summarize.py), so the two experiments are scored identically.

Instance = one task in one context (corpus, chunker, seed, mode, context kind, plan, task). Sets:
  related-valid           : related contexts, task valid in THIS context (full EM 1, EM 0 without the required chunk, NLL gain >= ln 2)
  related-valid-targets   : ... and the query prefix references a symbol declared in a stale context chunk
  related-valid-notargets : ... and it does not
  related-all             : related contexts, no re-validation
  random-valid            : the E4 kept-valid set (control), recomputed here
  random-valid-targets    : ... with a query target
  matched-related / matched-random : (chunker, seed, task) valid in both kinds, scored in each kind
The `random` reproduction job (one E4 context rerun at the E4b commit) is only compared with E4, never pooled.
"""
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
E4 = HERE.parent / "E4-structure-aware"
_spec = importlib.util.spec_from_file_location("e4sum", E4 / "summarize.py")
e4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e4)
LN2 = math.log(2)
BUDGETS = [5.0, 10.0, 15.0, 20.0]


def load(dirs):
    new = pd.concat([pd.read_csv(p) for d in dirs for p in sorted(Path(d).glob("*.csv"))], ignore_index=True)
    old = pd.read_csv(E4 / "results.csv.gz").drop(columns=["inst"], errors="ignore")
    old = old[old["mode"] == "kept"].copy()
    old["context_kind"] = "random"
    repro = new[new.context_kind == "random"]
    new = new[new.context_kind == "related"]
    df = pd.concat([new, old], ignore_index=True)
    df["inst"] = (df.corpus + "/" + df.chunker + "/s" + df.seed.astype(str) + "/" + df["mode"] + "-" + df.context_kind + "/p"
                  + df.plan.astype(str) + "/" + df.task_id)
    if df.duplicated(["inst", "arm", "budget_pct"]).any():
        raise SystemExit("duplicate rows")
    return df, repro, old


def reproduction(repro, old):
    """The random-kind rerun against the E4 rows of the same context: identical metrics expected (deterministic CPU path)."""
    if repro.empty:
        return None
    cols = ["corpus", "chunker", "seed", "plan", "task_id", "arm", "budget_pct"]
    m = repro.merge(old, on=cols, suffixes=("_new", "_e4"))
    out = {"rows_rerun": len(repro), "rows_matched": len(m)}
    for c in ["mask_nll", "mask_em", "kl_cont", "budget_tokens", "graph_picks", "forward_calls"]:
        out[f"max_abs_diff_{c}"] = float((m[f"{c}_new"] - m[f"{c}_e4"]).abs().max())
    return out


def instances(df):
    full = df[df.arm == "full"].set_index("inst")
    drop = df[df.arm == "drop_required"].set_index("inst")
    inst = full[["corpus", "chunker", "seed", "mode", "context_kind", "plan", "context_id", "task_id", "cluster", "context_tokens", "chunks",
                 "required_first", "query_targets", "query_edges", "in_context_edges", "mask_tokens", "related_chunks", "hop1_chunks"]].copy()
    inst["full_nll"], inst["full_em"] = full.mask_nll, full.mask_em
    inst["drop_nll"], inst["drop_em"] = drop.mask_nll.reindex(inst.index), drop.mask_em.reindex(inst.index)
    redo = (inst.drop_em == 0) & (inst.drop_nll - inst.full_nll >= LN2 - 1e-9)
    # Related contexts are always re-validated (drop_required in every job); E4 symbol/seed 0 used Task 8's validation.
    inst["valid"] = (inst.full_em == 1) & (redo | (inst.drop_em.isna() & (inst.context_kind == "random")))
    return inst


def main(dirs):
    df, repro, old = load(dirs)
    rep = reproduction(repro, old)
    inst = instances(df)
    df.to_csv(HERE / "results.csv.gz", index=False)
    kept = inst["mode"] == "kept"
    rel, rnd = kept & (inst.context_kind == "related"), kept & (inst.context_kind == "random")
    tkey = inst.chunker + "/" + inst.seed.astype(str) + "/" + inst.task_id
    both = set(tkey[rel & inst.valid]) & set(tkey[rnd & inst.valid])
    matched = tkey.isin(both)
    sets = {
        "related-valid": rel & inst.valid,
        "related-valid-targets": rel & inst.valid & (inst.query_targets > 0),
        "related-valid-notargets": rel & inst.valid & (inst.query_targets == 0),
        "related-all": rel,
        "random-valid": rnd & inst.valid,
        "random-valid-targets": rnd & inst.valid & (inst.query_targets > 0),
        "matched-related": rel & inst.valid & matched,
        "matched-random": rnd & inst.valid & matched,
    }
    cur, prs = [], []
    for sname, smask in sets.items():
        for chunker in ["symbol", "fixed", "both"]:
            for corpus in ["afclaude", "docagent", "codesharp", "pooled"]:
                sel = smask & ((inst.chunker == chunker) if chunker != "both" else True) & ((inst.corpus == corpus) if corpus != "pooled" else True)
                sel = sel.to_numpy()
                if sel.sum() < 2:
                    continue
                label = f"{sname}|{chunker}|{corpus}"
                idx = e4.boot_idx(inst.loc[sel, "cluster"].to_numpy())
                cur += e4.curves(df, inst, sel, label, idx)
                if corpus == "pooled" or sname in ("related-valid", "random-valid"):
                    prs += e4.pairs(df, inst, sel, label, idx, BUDGETS)
    cur, prs = pd.DataFrame(cur), pd.DataFrame(prs)
    cur.to_csv(HERE / "curves.csv", index=False, float_format="%.5g")
    prs.to_csv(HERE / "pairs.csv", index=False, float_format="%.5g")

    # One row per context: the structure present in it (kept contexts, both kinds).
    ctx = inst[kept].groupby(["context_kind", "corpus", "chunker", "seed", "plan"]).agg(
        tasks=("task_id", "size"), valid=("valid", "sum"), chunks=("chunks", "first"), related_chunks=("related_chunks", "first"),
        hop1_chunks=("hop1_chunks", "first"), in_context_edges=("in_context_edges", "first"),
        query_targets_mean=("query_targets", "mean"), any_target=("query_targets", lambda s: (s > 0).mean())).reset_index()
    ctx.to_csv(HERE / "contexts.csv", index=False, float_format="%.4g")
    write_summary(df, inst, sets, cur, prs, ctx, rep)


def write_summary(df, inst, sets, cur, prs, ctx, rep):
    L = []
    w = L.append
    w("# E4b summary (generated by summarize.py; do not edit)\n")
    if rep:
        w("## Reproduction of an E4 random context at the E4b commit\n")
        w("; ".join(f"{k} = {v:g}" if isinstance(v, float) else f"{k} = {v}" for k, v in rep.items()) + "\n")
    w("## Instances\n")
    w("| kind | corpus | chunker | seed | contexts | instances | valid | full EM | EM without required | query targets > 0 |")
    w("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for (k, c, ch, s), g in inst[inst["mode"] == "kept"].groupby(["context_kind", "corpus", "chunker", "seed"]):
        w(f"| {k} | {c} | {ch} | {s} | {g.plan.nunique()} | {len(g)} | {int(g.valid.sum())} | {g.full_em.mean():.2f} | "
          f"{g.drop_em.mean():.2f} | {(g.query_targets > 0).mean():.2f} |")
    for sname, smask in sets.items():
        g = inst[smask]
        if len(g):
            w(f"\n{sname}: {len(g)} instances, {g.task_id.nunique()} distinct tasks, {g.cluster.nunique()} clusters (definition files).")
    w("\n## Structure per context (kept contexts; means over contexts)\n")
    w("Related distractors = distractor chunks from files within two hops of the calling files (also counted for the random"
      " contexts, where they occur by chance; E4 rows predate the column, so it is blank there).\n")
    w("| kind | chunker | corpus | contexts | chunks | related distractors / distractors | of which hop 1 | in-context cross-chunk edges (mean, median) | contexts with 0 edges | instances with a query target |")
    w("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for (k, ch), g0 in ctx.groupby(["context_kind", "chunker"]):
        for corpus, g in list(g0.groupby("corpus")) + [("pooled", g0)]:
            ii = inst[(inst["mode"] == "kept") & (inst.context_kind == k) & (inst.chunker == ch) & ((inst.corpus == corpus) if corpus != "pooled" else True)]
            w(f"| {k} | {ch} | {corpus} | {len(g)} | {g.chunks.mean():.1f} | {g.related_chunks.mean():.1f} / {(g.chunks - 1).mean():.1f} | "
              f"{g.hop1_chunks.mean():.1f} | {g.in_context_edges.mean():.1f}, {g.in_context_edges.median():.0f} | "
              f"{(g.in_context_edges == 0).mean():.2f} | {(ii.query_targets > 0).mean():.2f} |")
    for label in cur.set.unique():
        if not (label.endswith("|pooled") or label.startswith("related-valid|")):
            continue
        c = cur[cur.set == label]
        w(f"\n## {label} (n = {c.n.iloc[0]} instances, {c.clusters.iloc[0]} clusters)\n")
        w("Share of the naive->full masked-call NLL gap recovered (ratio of means) [95 % cluster-bootstrap CI]:\n")
        w(e4.table(cur, label, "gap_nll", BUDGETS))
        w("\nMasked-call exact match (mean) [95 % CI]:\n")
        w(e4.table(cur, label, "em", BUDGETS))
        w("\nPost-query KL (32 continuation rows, mean nats) / top-1 agreement:\n")
        w("| arm | " + " | ".join(f"{b:g} %" for b in BUDGETS) + " |")
        w("|---|" + "---:|" * len(BUDGETS))
        for a in e4.ORDER:
            r = c[c.arm == a]
            if r.empty or r.budget.isna().all():
                continue
            w(f"| {a} | " + " | ".join(f"{r[r.budget == b].kl_cont.iloc[0]:.3f} / {r[r.budget == b].top1_cont.iloc[0]:.3f}"
                                       if not r[r.budget == b].empty else "" for b in BUDGETS) + " |")
        p = prs[prs.set == label]
        if not p.empty:
            w("\nPaired comparisons (arm - baseline; d_gap > 0 and d_nll < 0 favour the arm) [95 % CI]:\n")
            w("| budget | arm | baseline | n | d gap (NLL) | d masked NLL (nats) | d EM | EM wins/losses |")
            w("|---:|---|---|---:|---|---|---|---|")
            for _, r in p.iterrows():
                base = r.baseline + (" (best)" if r.baseline == r.best_baseline else "")
                w(f"| {r.budget:g} | {r.arm} | {base} | {r.n} | {e4.fmt(r.d_gap, r.d_gap_lo, r.d_gap_hi)} | {e4.fmt(r.d_nll, r.d_nll_lo, r.d_nll_hi)} | "
                  f"{e4.fmt(r.d_em, r.d_em_lo, r.d_em_hi)} | {r.em_wins}/{r.em_losses} |")
    w("\n## Per chunker and seed (valid): share of the naive->full NLL gap recovered (point estimates)\n")
    nll = e4.wide(df, inst, "mask_nll")
    arms = [("chunk_starts", "ChunkStarts"), ("query", "QR"), ("graph", "Graph"), ("hybrid_query", "Hybrid(QR)")]
    w("| kind | chunker | seed | n | " + " | ".join(f"{l} {b} %" for _, l in arms for b in (5, 10, 20)) + " |")
    w("|---|---|---:|---:|" + "---:|" * (3 * len(arms)))
    for (k, ch, sd), g in inst[(inst["mode"] == "kept") & inst.valid].groupby(["context_kind", "chunker", "seed"]):
        n = nll.loc[g.index]
        den = (n.naive - n.full).sum()
        w(f"| {k} | {ch} | {sd} | {len(g)} | " + " | ".join(f"{(n.naive - n[f'{a}@{float(b)}']).sum() / den:.2f}" for a, _ in arms for b in (5, 10, 20)) + " |")
    w("\n## Graph picks vs fill (share of the budget chosen by the graph; the rest is chunk-start fill)\n")
    w("| kind | subset | budget % | graph picks / budget tokens (mean) | share |")
    w("|---|---|---:|---:|---:|")
    for k in ["related", "random"]:
        kv = df[df.inst.isin(inst.index[(inst["mode"] == "kept") & inst.valid & (inst.context_kind == k)])]
        for label, sub in [("all valid", kv), ("query targets > 0", kv[kv.query_targets > 0]), ("no query targets", kv[kv.query_targets == 0])]:
            for b in BUDGETS:
                r = sub[(sub.arm == "graph") & (sub.budget_pct == b)]
                if len(r):
                    w(f"| {k} | {label} | {b:g} | {r.graph_picks.mean():.1f} / {r.budget_tokens.mean():.0f} | {r.graph_picks.sum() / r.budget_tokens.sum():.2f} |")
    w("\n## Cost per arm (related contexts)\n")
    d = df[(df.context_kind == "related") & ~df.arm.isin(["full", "naive", "drop_required"])]
    ov = d.groupby(["arm", "budget_pct"]).agg(rows=("inst", "size"), select_ms=("select_ms", "median"), score_ms=("score_ms", "median"),
                                              calls=("forward_calls", "mean"), rec=("recompute_ms", "mean")).reset_index()
    w("| arm | budget % | rows | score ms (median) | selection ms (median) | forward calls (mean) | recompute ms (mean) |")
    w("|---|---:|---:|---:|---:|---:|---:|")
    for _, r in ov.iterrows():
        w(f"| {r.arm} | {r.budget_pct:g} | {r.rows} | {r.score_ms:.0f} | {r.select_ms:.3f} | {r.calls:.0f} | {r.rec:.0f} |")
    (HERE / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote summary.md, curves.csv ({len(cur)}), pairs.csv ({len(prs)}), contexts.csv ({len(ctx)})")


if __name__ == "__main__":
    main(sys.argv[1:] or [str(HERE / "raw")])
