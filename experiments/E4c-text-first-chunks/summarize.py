# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.1.3", "pandas==2.2.3"]
# ///
"""E4c summary: the E4 fixed-chunk arms with TEXT-FIRST fixed chunks (fixed-text-512), against E4's id-sliced fixed chunks.

Usage: uv run summarize.py [<E4c raw dir> ...]   (default raw/)
Reads ../E4-structure-aware/results.csv.gz (id-sliced `fixed` rows, mode kept) as the control and roundtrip.csv.gz (the
tokenizer-only round-trip census), and writes results.csv.gz, curves.csv, pairs.csv, cross.csv and summary.md here.
Statistics (validity, ratio-of-means gap, cluster bootstrap with cluster = corpus | definition file, paired comparisons)
are E4's own functions (imported from ../E4-structure-aware/summarize.py), so both chunkers are scored identically.

Instance = one task in one context (corpus, chunker, seed, plan, task). Validity is re-applied per context for both chunkers
(full EM 1, EM 0 without the required chunk, masked NLL gain >= ln 2; every fixed / fixed-text job ran drop_required).
Sets:
  text-valid      : fixed-text instances, valid in their own context
  slice-valid     : E4 fixed instances, valid (E4's kept-valid|fixed)
  slice-covered   : slice-valid restricted to the (corpus, seed, task) that E4c ran (the time cap truncated some cells)
  matched-text / matched-slice : (corpus, seed, task) valid under both chunkers, scored under each
cross.csv: paired text - slice differences on the matched set (same task and seed; different contexts, because the chunks
differ and so the distractor draw differs), gap recovered and EM, with one shared cluster resample.
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
ARMS = ["naive", "chunk_starts", "query", "graph", "hybrid_query", "random", "full"]
LABEL = {"naive": "naive", "chunk_starts": "ChunkStarts", "query": "QR", "graph": "Graph", "hybrid_query": "Hybrid(QR)", "random": "Random",
         "full": "full"}


def load(dirs):
    # *.csv.partial: a job stopped before its time cap (rows of finished contexts only; see run.ps1 / e4 resume)
    files = [p for d in dirs for pat in ("*.csv", "*.csv.partial") for p in sorted(Path(d).glob(pat))]
    new = pd.concat([pd.read_csv(p) for p in files], ignore_index=True)
    old = pd.read_csv(E4 / "results.csv.gz").drop(columns=["inst"], errors="ignore")
    old = old[(old["mode"] == "kept") & (old.chunker == "fixed")].copy()
    df = pd.concat([new, old], ignore_index=True)
    df["inst"] = (df.corpus + "/" + df.chunker + "/s" + df.seed.astype(str) + "/p" + df.plan.astype(str) + "/" + df.task_id)
    if df.duplicated(["inst", "arm", "budget_pct"]).any():
        raise SystemExit("duplicate rows")
    return df


def instances(df):
    full = df[df.arm == "full"].set_index("inst")
    drop = df[df.arm == "drop_required"].set_index("inst")
    inst = full[["corpus", "chunker", "seed", "mode", "plan", "context_id", "task_id", "cluster", "context_tokens", "chunks", "required_first",
                 "query_targets", "query_edges", "in_context_edges", "mask_tokens"]].copy()
    inst["full_nll"], inst["full_em"] = full.mask_nll, full.mask_em
    inst["drop_nll"], inst["drop_em"] = drop.mask_nll.reindex(inst.index), drop.mask_em.reindex(inst.index)
    if inst.drop_em.isna().any():
        raise SystemExit("an instance without drop_required: every fixed / fixed-text job runs it")
    inst["valid"] = (inst.full_em == 1) & (inst.drop_em == 0) & (inst.drop_nll - inst.full_nll >= LN2 - 1e-9)
    inst["key"] = inst.corpus + "/s" + inst.seed.astype(str) + "/" + inst.task_id
    return inst


def cross(df, inst, label, corpus_mask):
    """Paired text - slice differences on the matched instances: gap recovered (difference of two ratios of means) and EM."""
    mt = inst[(inst.chunker == "fixed-text") & inst.valid & inst.matched & corpus_mask].sort_values("key")
    ms = inst[(inst.chunker == "fixed") & inst.valid & inst.matched & corpus_mask].sort_values("key")
    if len(mt) < 2:
        return []
    assert list(mt.key) == list(ms.key)
    nt, ns = e4.wide(df, inst, "mask_nll").loc[mt.index], e4.wide(df, inst, "mask_nll").loc[ms.index]
    et, es = e4.wide(df, inst, "mask_em").loc[mt.index], e4.wide(df, inst, "mask_em").loc[ms.index]
    idx = e4.boot_idx(mt.cluster.to_numpy())
    rows = []
    cols = ["naive", "full"] + [f"{a}@{b}" for a in ARMS[1:-1] for b in BUDGETS]
    for col in cols:
        if col not in nt or col not in ns:
            continue
        have = nt[col].notna().to_numpy() & ns[col].notna().to_numpy()   # positional: the two frames have different labels
        if have.sum() < 2:
            continue
        def gaps(ii):
            ii = ii[have[ii]]
            dt = (nt.naive.to_numpy()[ii] - nt.full.to_numpy()[ii]).sum()
            ds = (ns.naive.to_numpy()[ii] - ns.full.to_numpy()[ii]).sum()
            gt = (nt.naive.to_numpy()[ii] - nt[col].to_numpy()[ii]).sum() / dt if dt else np.nan
            gs = (ns.naive.to_numpy()[ii] - ns[col].to_numpy()[ii]).sum() / ds if ds else np.nan
            em = np.mean(et[col].to_numpy()[ii] - es[col].to_numpy()[ii])
            return gt, gs, gt - gs, em
        allidx = np.arange(len(mt))
        gt, gs, d, dem = gaps(allidx)
        boots = np.array([gaps(i) for i in idx])
        lo, hi = np.nanpercentile(boots[:, 2], [2.5, 97.5])
        elo, ehi = np.nanpercentile(boots[:, 3], [2.5, 97.5])
        arm, _, b = col.partition("@")
        dd = et[col].to_numpy()[have] - es[col].to_numpy()[have]
        rows.append(dict(set=label, arm=arm, budget=float(b) if b else np.nan, n=int(have.sum()), clusters=mt.cluster[have].nunique(),
                         gap_text=gt, gap_slice=gs, d_gap=d, d_gap_lo=lo, d_gap_hi=hi,
                         em_text=np.mean(et[col].to_numpy()[have]), em_slice=np.mean(es[col].to_numpy()[have]), d_em=dem, d_em_lo=elo, d_em_hi=ehi,
                         em_text_wins=int((dd > 0).sum()), em_text_losses=int((dd < 0).sum())))
    return rows


def main(dirs):
    df = load(dirs)
    inst = instances(df)
    df.to_csv(HERE / "results.csv.gz", index=False)
    text, slc = inst.chunker == "fixed-text", inst.chunker == "fixed"
    ran = set(inst.key[text])
    both = set(inst.key[text & inst.valid]) & set(inst.key[slc & inst.valid])
    inst["matched"] = inst.key.isin(both)
    sets = {
        "text-valid": text & inst.valid,
        "slice-valid": slc & inst.valid,
        "slice-covered": slc & inst.valid & inst.key.isin(ran),
        "matched-text": text & inst.valid & inst.matched,
        "matched-slice": slc & inst.valid & inst.matched,
        "text-all": text,
    }
    cur, prs, crs = [], [], []
    for sname, smask in sets.items():
        for corpus in ["afclaude", "docagent", "codesharp", "pooled"]:
            sel = (smask & ((inst.corpus == corpus) if corpus != "pooled" else True)).to_numpy()
            if sel.sum() < 2:
                continue
            label = f"{sname}|{corpus}"
            idx = e4.boot_idx(inst.loc[sel, "cluster"].to_numpy())
            cur += e4.curves(df, inst, sel, label, idx)
            prs += e4.pairs(df, inst, sel, label, idx, BUDGETS)
    for corpus in ["afclaude", "docagent", "codesharp", "pooled"]:
        crs += cross(df, inst, f"matched|{corpus}", (inst.corpus == corpus) if corpus != "pooled" else pd.Series(True, index=inst.index))
    cur, prs, crs = pd.DataFrame(cur), pd.DataFrame(prs), pd.DataFrame(crs)
    cur.to_csv(HERE / "curves.csv", index=False, float_format="%.5g")
    prs.to_csv(HERE / "pairs.csv", index=False, float_format="%.5g")
    crs.to_csv(HERE / "cross.csv", index=False, float_format="%.5g")
    write_summary(df, inst, sets, cur, prs, crs)


def roundtrip_table():
    p = HERE / "roundtrip.csv.gz"
    if not p.exists():
        return []
    rt = pd.read_csv(p)
    out = ["| corpus | chunker | chunks | decoded-text round trip fails | of which U+FFFD (cut inside a UTF-8 character) | file-range text round trip fails | chunk tokens (median / max) |",
           "|---|---|---:|---:|---:|---:|---|"]
    for (c, ch), g in rt.groupby(["corpus", "chunker"], sort=False):
        out.append(f"| {c} | {ch} | {len(g)} | {int((g.decoded_rt_ok == 0).sum())} ({(g.decoded_rt_ok == 0).mean() * 100:.2f} %) | {int(g.decode_fffd.sum())} | "
                   f"{int((g.range_rt_ok == 0).sum())} ({(g.range_rt_ok == 0).mean() * 100:.2f} %) | {int(g.tokens.median())} / {int(g.tokens.max())} |")
    for ch, g in rt.groupby("chunker", sort=False):
        out.append(f"| all | {ch} | {len(g)} | {int((g.decoded_rt_ok == 0).sum())} ({(g.decoded_rt_ok == 0).mean() * 100:.2f} %) | {int(g.decode_fffd.sum())} | "
                   f"{int((g.range_rt_ok == 0).sum())} ({(g.range_rt_ok == 0).mean() * 100:.2f} %) | {int(g.tokens.median())} / {int(g.tokens.max())} |")
    return out


def write_summary(df, inst, sets, cur, prs, crs):
    L = []
    w = L.append
    w("# E4c summary (generated by summarize.py; do not edit)\n")
    rt = roundtrip_table()
    if rt:
        w("## Text round trip of every chunk (tokenizer only; roundtrip.csv.gz)\n")
        L.extend(rt)
        w("")
    w("## Instances\n")
    w("| chunker | corpus | seed | contexts | instances | valid | full EM | EM without required | chunks per context | query targets > 0 |")
    w("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for (ch, c, s), g in inst.groupby(["chunker", "corpus", "seed"]):
        w(f"| {ch} | {c} | {s} | {g.plan.nunique()} | {len(g)} | {int(g.valid.sum())} | {g.full_em.mean():.2f} | {g.drop_em.mean():.2f} | "
          f"{g.groupby('plan').chunks.first().mean():.1f} | {(g.query_targets > 0).mean():.2f} |")
    for sname, smask in sets.items():
        g = inst[smask]
        if len(g):
            w(f"\n{sname}: {len(g)} instances, {g.task_id.nunique()} distinct tasks, {g.cluster.nunique()} clusters (definition files).")
    if not crs.empty:
        w("\n## Text-first minus id-sliced, paired on the matched instances (same task and seed) [95 % cluster-bootstrap CI]\n")
        w("| set | arm | budget % | n | gap text | gap slice | d gap | EM text | EM slice | d EM | EM text wins/losses |")
        w("|---|---|---:|---:|---:|---:|---|---:|---:|---|---|")
        for _, r in crs.iterrows():
            b = "" if np.isnan(r.budget) else f"{r.budget:g}"
            w(f"| {r.set} | {LABEL.get(r.arm, r.arm)} | {b} | {r.n} | {r.gap_text:.2f} | {r.gap_slice:.2f} | {e4.fmt(r.d_gap, r.d_gap_lo, r.d_gap_hi)} | "
              f"{r.em_text:.2f} | {r.em_slice:.2f} | {e4.fmt(r.d_em, r.d_em_lo, r.d_em_hi)} | {r.em_text_wins}/{r.em_text_losses} |")
    w("\n## 95 % / 20 % bar (exact match >= 0.95 x full at <= 20 % recompute), point estimates\n")
    w("'Best' is the maximum over every runnable arm and budget <= 20 % (optimistic: a maximum of noisy cells); the pre-specified"
      " arms (E4's) are QR and Hybrid(QR) at 20 %.\n")
    w("| set | n | full EM | naive EM | QR 20 % | Hybrid(QR) 20 % | ChunkStarts 20 % | best runnable arm at <= 20 % (EM) | ratio | met (best) |")
    w("|---|---:|---:|---:|---:|---:|---:|---|---:|---|")
    for label in cur.set.unique():
        c = cur[cur.set == label]
        run = c[c.arm.isin(["chunk_starts", "query", "graph", "hybrid_query", "random"]) & (c.budget <= 20)]
        if run.empty:
            continue
        best = run.sort_values(["em", "budget"], ascending=[False, True]).iloc[0]
        fe = c.full_em.iloc[0]
        ne = c[c.arm == "naive"].em.iloc[0] if not c[c.arm == "naive"].empty else np.nan
        at = lambda a: (lambda x: f"{x.em.iloc[0]:.2f}" if not x.empty else "")(c[(c.arm == a) & (c.budget == 20)])
        w(f"| {label} | {c.n.max()} | {fe:.2f} | {ne:.2f} | {at('query')} | {at('hybrid_query')} | {at('chunk_starts')} | {LABEL[best.arm]} {best.budget:g} % ({best.em:.2f}) | {best.em / fe:.2f} | "
          f"{'yes' if best.em >= 0.95 * fe else 'no'} |")
    for label in cur.set.unique():
        if not (label.endswith("|pooled") or label.startswith("text-valid|")):
            continue
        c = cur[cur.set == label]
        w(f"\n## {label} (n = {c.n.max()} instances, {c.clusters.iloc[0]} clusters)\n")
        w("Share of the naive->full masked-call NLL gap recovered (ratio of means) [95 % cluster-bootstrap CI]:\n")
        w(e4.table(cur, label, "gap_nll", BUDGETS, arms=ARMS))
        w("\nMasked-call exact match (mean) [95 % CI]:\n")
        w(e4.table(cur, label, "em", BUDGETS, arms=ARMS))
        w("\nPost-query KL (32 continuation rows, mean nats) / top-1 agreement:\n")
        w("| arm | " + " | ".join(f"{b:g} %" for b in BUDGETS) + " |")
        w("|---|" + "---:|" * len(BUDGETS))
        for a in ARMS:
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
    w("\n## Per seed (valid): share of the naive->full NLL gap recovered (point estimates)\n")
    nll = e4.wide(df, inst, "mask_nll")
    arms = [("chunk_starts", 5), ("chunk_starts", 20), ("query", 5), ("query", 10), ("query", 20), ("hybrid_query", 20), ("graph", 20)]
    w("| chunker | seed | n | " + " | ".join(f"{LABEL[a]} {b} %" for a, b in arms) + " |")
    w("|---|---:|---:|" + "---:|" * len(arms))
    for (ch, sd), g in inst[inst.valid].groupby(["chunker", "seed"]):
        n = nll.loc[g.index]
        den = (n.naive - n.full).sum()
        w(f"| {ch} | {sd} | {len(g)} | " + " | ".join(f"{(n.naive - n[f'{a}@{float(b)}']).sum() / den:.2f}" if f"{a}@{float(b)}" in n else ""
                                                     for a, b in arms) + " |")
    w("\n## Cost per arm (fixed-text rows)\n")
    d = df[(df.chunker == "fixed-text") & ~df.arm.isin(["full", "naive", "drop_required"])]
    ov = d.groupby(["arm", "budget_pct"]).agg(rows=("inst", "size"), select_ms=("select_ms", "median"), score_ms=("score_ms", "median"),
                                              calls=("forward_calls", "mean"), rec=("recompute_ms", "mean"), memo=("memo", "mean")).reset_index()
    w("| arm | budget % | rows | score ms (median) | selection ms (median) | forward calls (mean) | recompute ms (mean) | memo share |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in ov.iterrows():
        w(f"| {r.arm} | {r.budget_pct:g} | {r.rows} | {r.score_ms:.0f} | {r.select_ms:.3f} | {r.calls:.0f} | {r.rec:.0f} | {r.memo:.2f} |")
    (HERE / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote summary.md, curves.csv ({len(cur)}), pairs.csv ({len(prs)}), cross.csv ({len(crs)})")


if __name__ == "__main__":
    main(sys.argv[1:] or [str(HERE / "raw")])
