"""F16 vs F32 G2b speedups. usage: python speedup.py [f32_dir f16_dir]. Reads timing-*.csv; writes nothing (prints markdown).
Warm TTFT = asm_device + single (chunk_starts) per context (median over repeats); ordinary prefill = full512 (best of full*);
tiled prefill = d_qpos_all from the eval-group timing file of the same size. Medians over contexts."""
import csv, glob, os, statistics as st, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
dirs = {'F32': sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'G2-recompute-speed'), 'F16': HERE}


def load(d, labels):
    rows = []
    for lab in labels:
        for f in glob.glob(os.path.join(d, f'timing-{lab}.csv')):
            rows += list(csv.DictReader(open(f, newline='', encoding='utf-8')))
    return rows


def per_ctx(rows, arm, sel, b):
    v = defaultdict(list)
    for r in rows:
        if r['arm'] == arm and r['selector'] == sel and int(r['budget_pct']) == b:
            v[r['context_id']].append(float(r['ms']))
    return {k: st.median(x) for k, x in v.items()}


def run(name, d, size, timing, evals):
    t, e = load(d, timing), load(d, evals)
    full = {}
    for arm in ('full256', 'full512', 'full2048'):
        for k, v in per_ctx(t, arm, '', 100).items():
            full[k] = min(full.get(k, 1e18), v)
    asm = per_ctx(t, 'asm_device', '', 0)
    qall = per_ctx(e, 'd_qpos_all', '', 100)
    out = {'ctx': sorted(asm)}
    out['full'] = st.median(full.values()) if full else float('nan')
    out['qall'] = st.median(qall.values()) if qall else float('nan')
    for b in (5, 10, 20):
        s = per_ctx(t, 'single', 'chunk_starts', b)
        warm = {k: asm[k] + s[k] for k in s if k in asm}
        w = st.median(warm.values()) if warm else float('nan')
        out[b] = (w, st.median([full[k] / warm[k] for k in warm if k in full]) if warm else float('nan'),
                  st.median([qall[k] / warm[k] for k in warm if k in qall]) if any(k in qall for k in warm) else float('nan'))
    return out


SIZES = {'2K': (['b-2k', 'b-2k-r2'], ['b-2k-eval', 'b-2k-evalS']), '4K': (['b-4k'], ['b-4k-eval']), '8K': (['b-8k', 'b-8k-r2'], ['b-8k-eval'])}
print('| ctx | storage | n ctx | ordinary prefill | tiled prefill (d_qpos_all) | 5% warm (x ord / x tiled) | 10% | 20% |')
print('|---|---|---:|---:|---:|---|---|---|')
for size, (tm, ev) in SIZES.items():
    for name, d in dirs.items():
        o = run(name, d, size, tm, ev)
        if not o['ctx']:
            continue
        cells = [f"{o[b][0] / 1000:.2f} s ({o[b][1]:.1f}x / {o[b][2]:.1f}x)" for b in (5, 10, 20)]
        print(f"| {size} | {name} | {len(o['ctx'])} | {o['full'] / 1000:.2f} s | {o['qall'] / 1000:.2f} s | " + ' | '.join(cells) + ' |')
