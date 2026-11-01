# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.1.3", "pandas==2.2.3", "matplotlib==3.9.2"]
# ///
"""E4 quality-vs-budget curves from curves.csv (run summarize.py first): figures/{gap,em}-{light,dark}.png.
Panels = chunker (symbol, fixed) for the kept-valid set, corpora pooled; 95 % cluster-bootstrap bands for the
query / graph / hybrid arms. Usage: uv run plot.py"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
# Reference categorical palette (dataviz skill), fixed slot order per arm; light / dark steps.
ARMS = [  # arm, label, slot, marker, band
    ("query", "QueryRelevance (best E2)", 0, "o", True),
    ("graph", "Graph", 1, "s", True),
    ("hybrid_query", "Hybrid(QR)", 2, "D", True),
    ("hybrid_dev", "Hybrid(Dev)", 3, "^", False),
    ("chunk_starts", "ChunkStarts", 4, "v", False),
    ("deviation", "DeviationTopK", 6, "P", False),
    ("oracle_def_fill", "Oracle def + fill", 7, "X", False),
]
OTHER = [("first_k", "FirstK", "--", "."), ("random", "Random (control)", ":", "x")]
LIGHT = dict(surface="#fcfcfb", ink="#1f1f1d", muted="#6b6a64", grid="#e4e3dd",
             series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"])
DARK = dict(surface="#1a1a19", ink="#f0efec", muted="#a3a29a", grid="#33332f",
            series=["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"])


def draw(cur, metric, ylabel, theme, out):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True, facecolor=theme["surface"])
    for ax, chunker in zip(axes, ["symbol", "fixed"]):
        ax.set_facecolor(theme["surface"])
        c = cur[cur.set == f"kept-valid|{chunker}|pooled"]
        if c.empty:
            ax.set_title(f"{chunker}: no data", color=theme["ink"])
            continue
        for arm, label, ls, mk in OTHER:
            r = c[(c.arm == arm) & c.budget.notna()].sort_values("budget")
            if not r.empty:
                ax.plot(r.budget, r[metric], color=theme["muted"], lw=1.5, ls=ls, marker=mk, ms=7, label=label)
        for arm, label, slot, marker, band in ARMS:
            r = c[(c.arm == arm) & c.budget.notna()].sort_values("budget")
            if r.empty:
                continue
            col = theme["series"][slot]
            if band:
                ax.fill_between(r.budget, r[metric + "_lo"], r[metric + "_hi"], color=col, alpha=0.12, lw=0)
            ax.plot(r.budget, r[metric], color=col, lw=2, marker=marker, ms=8, label=label,
                    markeredgecolor=theme["surface"], markeredgewidth=1.5)
        n =int(c.n.iloc[0])
        k = int(c.clusters.iloc[0])
        ax.set_title(f"{chunker} chunks (n = {n} task instances, {k} clusters)", color=theme["ink"], fontsize=11)
        ax.set_xlabel("recompute budget (% of context tokens)", color=theme["ink"])
        ax.set_xticks([5, 10, 15, 20])
        ax.grid(True, color=theme["grid"], lw=0.8)
        ax.axhline(1.0 if metric == "gap_nll" else c[c.arm == "full"][metric].iloc[0], color=theme["muted"], lw=1, ls=":")
        ax.axhline(0.0 if metric == "gap_nll" else c[c.arm == "naive"][metric].iloc[0], color=theme["muted"], lw=1, ls=":")
        for s in ax.spines.values():
            s.set_color(theme["grid"])
        ax.tick_params(colors=theme["muted"])
    axes[0].set_ylabel(ylabel, color=theme["ink"])
    h, l = axes[0].get_legend_handles_labels()
    leg = fig.legend(h, l, loc="lower center", ncol=5, frameon=False, fontsize=9)
    for t in leg.get_texts():
        t.set_color(theme["ink"])
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(out, dpi=130, facecolor=theme["surface"])
    plt.close(fig)


def main():
    cur = pd.read_csv(HERE / "curves.csv")
    (HERE / "figures").mkdir(exist_ok=True)
    for name, theme in [("light", LIGHT), ("dark", DARK)]:
        draw(cur, "gap_nll", "share of naive->full masked-call NLL gap recovered", theme, HERE / "figures" / f"gap-{name}.png")
        draw(cur, "em", "masked-call exact match (dotted: naive, full)", theme, HERE / "figures" / f"em-{name}.png")
    print("wrote figures/gap-*.png, figures/em-*.png")


if __name__ == "__main__":
    main()
