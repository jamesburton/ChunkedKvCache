# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib==3.9.2", "numpy==2.1.3"]
# ///
"""E3 figures from heatmap.csv and capture-curves.csv (written by summarize.py).

Usage:  uv run plot.py     (writes figures/*-light.png and figures/*-dark.png; the README picks one by colour scheme)
"""
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

HERE = Path(__file__).resolve().parent
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

MODES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
                  mid="#f0efec", series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100"], blue="#184f95", red="#b8322f"),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a", axis="#383835",
                 mid="#383835", series=["#3987e5", "#d95926", "#199e70", "#c98500"], blue="#6da7ec", red="#e66767"),
}
GROUPS = [("role", "ChunkStart", "ChunkStart"), ("role", "DefinitionSite", "Definition"), ("role", "UseSite", "Use"),
          ("role", "Import", "Import"), ("role", "Other", "Other"), ("label", "cs16", "first 16*"),
          ("label", "def_after_cs16", "def after 16*"), ("label", "qtarget", "query target*"), ("role", "Query", "query rows")]

heat = defaultdict(dict)
for r in csv.DictReader(open(HERE / "heatmap.csv", encoding="utf-8")):
    heat[r["chunker"]][(int(r["layer"]), r["kind"], r["group"])] = (float(r["rel"]), float(r["enrichment"]))
caps = list(csv.DictReader(open(HERE / "capture-curves.csv", encoding="utf-8")))
CHUNKERS = [c for c in ("symbol", "fixed") if c in heat]
LAYERS = 1 + max(k[0] for c in CHUNKERS for k in heat[c])


def style(ax, m):
    ax.set_facecolor(m["surface"])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(m["axis"])
    ax.tick_params(colors=m["muted"], labelcolor=m["ink2"], labelsize=8)
    ax.xaxis.label.set_color(m["ink2"])
    ax.yaxis.label.set_color(m["ink2"])
    ax.title.set_color(m["ink"])


for mode, m in MODES.items():
    plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9})

    # 1. heatmap: layer x role, enrichment over all stale tokens (log scale, diverging around 1) ------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10, 7), facecolor=m["surface"], constrained_layout=True)
    cmap = LinearSegmentedColormap.from_list("div", [m["blue"], m["mid"], m["red"]])
    cmap.set_bad(m["surface"])
    norm = TwoSlopeNorm(vmin=-3, vcenter=0, vmax=3)
    for ax, chk in zip(axes, CHUNKERS):
        def cell(l, k, g):
            e = heat[chk].get((l, k, g), (0.0, float("nan")))[1]
            # layer 0 is exact up to RoPE-shift float error (~1e-6): its ratios are noise, so it is left blank
            return float("nan") if l == 0 or e != e else math.log2(max(e, 1 / 64))

        grid = [[cell(l, k, g) for k, g, _ in GROUPS] for l in range(LAYERS)]
        im = ax.imshow(grid, aspect="auto", cmap=cmap, norm=norm, interpolation="nearest")
        ax.set_xticks(range(len(GROUPS)), [lbl for _, _, lbl in GROUPS], rotation=40, ha="right")
        ax.set_yticks(range(0, LAYERS, 5))
        ax.set_ylabel("layer")
        ax.set_title(f"{chk}-512 chunks", loc="left", fontsize=10)
        style(ax, m)
    cb = fig.colorbar(im, ax=axes, shrink=0.6, ticks=[-3, -2, -1, 0, 1, 2, 3])
    cb.ax.set_yticklabels(["1/8x", "1/4x", "1/2x", "1x", "2x", "4x", "8x"], color=m["ink2"], fontsize=8)
    cb.outline.set_visible(False)
    cb.set_label("relative deviation vs all stale tokens (same layer)", color=m["ink2"])
    fig.suptitle("E3: where the K/V deviation sits, by token role and layer (* = multi-label group; layer 0 blank: exact)", color=m["ink"], x=0.02, ha="left")
    fig.savefig(FIG / f"heatmap-{mode}.png", dpi=150, facecolor=m["surface"])
    plt.close(fig)

    # 2. depth profile ---------------------------------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7, 3.6), facecolor=m["surface"], constrained_layout=True)
    for i, chk in enumerate(CHUNKERS):
        ys = [heat[chk][(l, "label", "stale_all")][0] if (l, "label", "stale_all") in heat[chk] else float("nan") for l in range(LAYERS)]
        ax.plot(range(LAYERS), ys, color=m["series"][i], lw=2, marker="o", ms=4, label=f"{chk}-512")
        ax.annotate(f"{chk}", (LAYERS - 1, ys[-1]), xytext=(4, 0), textcoords="offset points", color=m["ink2"], va="center", fontsize=8)
    ax.grid(axis="y", color=m["grid"], lw=0.6)
    ax.set_xlabel("layer")
    ax.set_ylabel("mean ||(dK,dV)|| / ||(K,V)_full||")
    ax.set_title("Relative K/V deviation of stale tokens by layer", loc="left", fontsize=10)
    leg = ax.legend(frameon=False, labelcolor=m["ink2"], fontsize=8)
    style(ax, m)
    fig.savefig(FIG / f"depth-{mode}.png", dpi=150, facecolor=m["surface"])
    plt.close(fig)

    # 3. concentration at k = 10 % vs baselines, per layer ------------------------------------------------------------------
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), facecolor=m["surface"], constrained_layout=True, sharey=True)
    for ax, chk in zip(axes, CHUNKERS):
        rows = [r for r in caps if r["chunker"] == chk and r["metric"] == "kv_rel" and float(r["k_pct"]) == 10.0]
        rows.sort(key=lambda r: int(r["layer"]))
        xs = [int(r["layer"]) for r in rows][1:]
        for i, (col, lbl) in enumerate([("share_top", "top-10% (oracle)"), ("share_position", "first tokens of each chunk"),
                                        ("share_layer1set", "top-10% at layer 1")]):
            ax.plot(xs, [float(r[col]) for r in rows][1:], color=m["series"][i], lw=2, label=lbl)
        ax.plot(xs, [float(r["share_random"]) for r in rows][1:], color=m["muted"], lw=1.5, ls="--", label="random 10%")
        ax.set_ylim(0, 0.5)
        ax.grid(axis="y", color=m["grid"], lw=0.6)
        ax.set_xlabel("layer")
        ax.set_title(f"{chk}-512", loc="left", fontsize=10)
        style(ax, m)
    axes[0].set_ylabel("share of the layer's deviation (rel)")
    axes[1].legend(frameon=False, labelcolor=m["ink2"], fontsize=8, loc="upper right", ncol=2)
    fig.suptitle("Share of each layer's relative deviation held by 10% of the stale tokens", color=m["ink"], x=0.02, ha="left")
    fig.savefig(FIG / f"capture-{mode}.png", dpi=150, facecolor=m["surface"])
    plt.close(fig)
print(f"figures -> {FIG}")
