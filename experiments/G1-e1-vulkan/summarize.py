"""G1: E1 on Vulkan, summary tables against the CPU E1 table and the G0 floor.

usage: uv run summarize.py [<dir with results-*.csv and their -timing/-kv/-xcheck companions>]   (default: this directory)
writes summary.md into that directory. Standard library only.

Inputs
- results-<group>.csv (+ -details, -timing, -kv, -xcheck): ChunkKvLab e1 --backend vulkan --cross-check cpu.
- ../E1-baselines/results.csv: the CPU E1 table (2K/4K/8K, seeds 0-2, same pinned corpus: E2 reproduced its naive rows exactly).
  ../E1-baselines/results-16k.csv is CPU 16K seed 0 on the LIVE dotLLM src (7,259 chunks, not the 4a781829 snapshot), so it is
  shown for trend only, never paired.
- ../G0-floor/floor-{2k,8k}.csv: per-layer floor of pair (a) CPU vs Vulkan (512-row blocks).

Tolerances (G0 README tolerance table as of ChunkedkvCache commit 1c0d418, "G0 floor fix round 1"; the scalar bounds below are
copied from it, so re-check them if that table changes):
- (c) bit-exact: prefix_vs_full and dev_vs_host logits identical, dev_vs_host and chunk0_vs_full KV max 0.
- cpu_vs_vk_naive is pair (a): CPU naive cache (reference) vs Vulkan naive cache, same tokens and chunks.
  * per layer K/V mean, single context: <= 2x the (a) per-layer floor mean; per-layer p99, single context: <= 3x the (a) p99
    (16K/32K: 8K floor, p99 x 1.6).
  * logits KL mean, single task (one seed x size = one task of 64 rows): <= 1.5x the largest (a) per-task floor:
    2K 8.1e-3, 8K 7.4e-3. 4K is not measured: the 2K bound is used (the larger one). 16K/32K: the 8K bound.
  * top-1 disagreement <= (a) 2.1 % (2K, 4K) / 2.4 % (8K and up) of the rows + 1 row.
"""
import csv
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
E1 = HERE.parent / 'E1-baselines'
G0 = HERE.parent / 'G0-floor'


def read(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load(suffix):
    rows = []
    for p in sorted(DATA.glob(f'results-*{suffix}.csv')):
        stem = p.name[:-len(suffix) - 4] if suffix else p.stem
        if 'smoke' in p.name or (not suffix and any(s in p.name for s in ('-details', '-timing', '-kv', '-xcheck'))):
            continue
        rows += read(p)
    return rows


def floor_size(L):
    return '2k' if L <= 4096 else '8k'


def kl_bound(L):
    return 8.1e-3 if L <= 4096 else 7.4e-3


def top1_bound(L):
    return 0.021 if L <= 4096 else 0.024


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float('nan')


def boot_ci(values, n=2000, seed=0):
    """Percentile bootstrap of the mean over the given cluster values (one value per seed)."""
    if len(values) < 2:
        return (float('nan'), float('nan'))
    rnd = random.Random(seed)
    ms = sorted(mean(rnd.choice(values) for _ in values) for _ in range(n))
    return (ms[int(0.025 * n)], ms[int(0.975 * n) - 1])


def fmt(x, p=4):
    if isinstance(x, float) and math.isnan(x):
        return '-'
    return f'{x:.{p}g}' if isinstance(x, float) else str(x)


out = []
res = load('')
timing = load('-timing')
kv = load('-kv')
xc = load('-xcheck')
if not res:
    sys.exit(f'no results-*.csv in {DATA}')

floor = {}
for size in ('2k', '8k'):
    for r in read(G0 / f'floor-{size}.csv'):
        if r['pair'] == 'a_cpu_vs_vk512' and r['kind'] in ('K', 'V'):
            floor[(size, int(r['layer']), r['kind'])] = (float(r['rel_l2_mean']), float(r['rel_l2_p99']))

cpu = defaultdict(dict)  # (method, size) -> seed -> row
for r in read(E1 / 'results.csv'):
    cpu[(r['Method'], int(r['ContextTokens']))][int(r['Seed'])] = r
cpu16 = {(r['Method'], int(r['ContextTokens'])): r for r in read(E1 / 'results-16k.csv')}

vk = defaultdict(dict)
for r in res:
    vk[(r['Method'], int(r['ContextTokens']))][int(r['Seed'])] = r
sizes = sorted({int(r['ContextTokens']) for r in res})

# 1. E1 table on Vulkan, next to CPU ----------------------------------------------------------------------------------------
out.append('## 1. E1 on Vulkan next to the CPU E1 table\n')
out.append('Mean over seeds (Vulkan: every seed run; CPU: E1-baselines `results.csv`, seeds 0-2 at 2K-8K; CPU 16K is seed 0 on a '
           'different corpus snapshot, shown in italics for trend only). TTFT = build + first token, seconds; the Vulkan TTFT '
           'is the median over seeds (32K seed 1 includes a host suspend).\n')
out.append('| method | ctx | seeds (Vulkan) | top-1 Vulkan | top-1 CPU | mean KL Vulkan [95 % CI over seeds] | mean KL CPU | EM Vulkan | EM CPU | TTFT Vulkan (s) | TTFT CPU (s) |')
out.append('|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|')
for L in sizes:
    for m in ('full', 'prefix_reuse', 'naive_concat'):
        v = vk.get((m, L), {})
        if not v:
            continue
        c = cpu.get((m, L), {})
        kls = [float(r['MeanKl']) for r in v.values()]
        lo, hi = boot_ci(kls)
        if c:
            ct1 = fmt(mean(float(r['Top1Agreement']) for r in c.values()), 3)
            ckl = fmt(mean(float(r['MeanKl']) for r in c.values()))
            cem = fmt(mean(float(r['ExactMatch']) for r in c.values()), 3)
            ctt = fmt(mean(float(r['TtftMs']) for r in c.values()) / 1000, 3)
        elif (m, L) in cpu16:
            r = cpu16[(m, L)]
            ct1, ckl, cem, ctt = (f"*{fmt(float(r['Top1Agreement']), 3)}*", f"*{fmt(float(r['MeanKl']))}*",
                                  f"*{fmt(float(r['ExactMatch']), 3)}*", f"*{fmt(float(r['TtftMs']) / 1000, 3)}*")
        else:
            ct1 = ckl = cem = ctt = 'not run'
        out.append(f"| {m} | {L} | {len(v)} | {fmt(mean(float(r['Top1Agreement']) for r in v.values()), 3)} | {ct1} | "
                   f"{fmt(mean(kls))} [{fmt(lo)}, {fmt(hi)}] | {ckl} | {fmt(mean(float(r['ExactMatch']) for r in v.values()), 3)} | {cem} | "
                   f"{fmt(sorted(float(r['TtftMs']) for r in v.values())[len(v) // 2] / 1000, 3)} | {ctt} |")
out.append('')

# 2. Paired naive comparison per seed ---------------------------------------------------------------------------------------
out.append('## 2. Naive concatenation, Vulkan vs CPU E1, paired by seed\n')
out.append('Δ = Vulkan − CPU. "share of gap" = |ΔKL| / CPU naive KL (the naive→full gap). The (a) single-task KL bound is shown for '
           'scale; it bounds KL between the two backends\' outputs (section 3), not a difference of two KLs.\n')
out.append('| ctx | seed | KL CPU | KL Vulkan | ΔKL | share of gap | top-1 CPU | top-1 Vulkan | Δ top-1 rows | EM CPU | EM Vulkan |')
out.append('|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
pooled = defaultdict(list)
for L in sizes:
    c = cpu.get(('naive_concat', L), {})
    for s, v in sorted(vk.get(('naive_concat', L), {}).items()):
        if s not in c:
            continue
        kc, kv_ = float(c[s]['MeanKl']), float(v['MeanKl'])
        tc, tv = float(c[s]['Top1Agreement']), float(v['Top1Agreement'])
        pooled[s].append((kv_ - kc, abs(kv_ - kc) / kc))
        out.append(f"| {L} | {s} | {fmt(kc)} | {fmt(kv_)} | {kv_ - kc:+.4f} | {abs(kv_ - kc) / kc:.1%} | {tc:.3f} | {tv:.3f} | "
                   f"{round((tv - tc) * 64):+d} | {float(c[s]['ExactMatch']):.3f} | {float(v['ExactMatch']):.3f} |")
if pooled:
    d = [mean(x[0] for x in xs) for xs in pooled.values()]
    sh = [mean(x[1] for x in xs) for xs in pooled.values()]
    lo, hi = boot_ci(d)
    out.append('')
    out.append(f'Pooled over the paired cells (cluster = seed): mean ΔKL {mean(d):+.4f} [bootstrap over {len(d)} seeds: {lo:+.4f}, {hi:+.4f}; '
               f'with 3 clusters only 27 distinct resamples exist, so this is descriptive], mean |ΔKL| share of the gap {mean(sh):.1%}.')
out.append('')

# 3. Cross-check: CPU naive vs Vulkan naive in one process (pair (a)) ---------------------------------------------------------
out.append('## 3. In-process cross-check: CPU naive cache vs Vulkan naive cache (G0 pair (a))\n')
out.append('One row per seed × size (a single task of 64 teacher-forced rows). KV ratios are the worst layer\'s ratio to the (a) '
           'per-layer floor (single-context bounds: mean ≤ 2×, p99 ≤ 3×; 16K/32K use the 8K floor and p99 × 1.6).\n')
out.append('| ctx | seed | KL(CPU‖Vulkan) | KL bound | top-1 | disagree rows (bound) | greedy agree | worst K mean ratio | worst V mean ratio | worst K p99 ratio | worst V p99 ratio | pass |')
out.append('|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---|')
kvx = defaultdict(list)
for r in kv:
    if r['pair'] == 'cpu_vs_vk_naive':
        kvx[(int(r['context_tokens']), int(r['seed']))].append(r)
all_pass = True
for r in sorted((r for r in xc if r['pair'] == 'cpu_vs_vk_naive'), key=lambda r: (int(r['context_tokens']), int(r['seed']))):
    L, s = int(r['context_tokens']), int(r['seed'])
    rows = int(r['rows'])
    klm, t1 = float(r['kl_mean']), float(r['top1'])
    dis = round((1 - t1) * rows)
    dis_bound = top1_bound(L) * rows + 1
    fs = floor_size(L)
    p99_scale = 1.6 if L > 8192 else 1.0
    worst = {'K': (0.0, 0.0), 'V': (0.0, 0.0)}
    for k in kvx[(L, s)]:
        fm, fp = floor[(fs, int(k['layer']), k['kind'])]
        rm = float(k['rel_l2_mean']) / fm
        rp = float(k['rel_l2_p99']) / (fp * p99_scale)
        wm, wp = worst[k['kind']]
        worst[k['kind']] = (max(wm, rm), max(wp, rp))
    ok = (klm <= kl_bound(L) and dis <= dis_bound and worst['K'][0] <= 2 and worst['V'][0] <= 2
          and worst['K'][1] <= 3 and worst['V'][1] <= 3)
    all_pass &= ok
    out.append(f"| {L} | {s} | {klm:.2e} | {kl_bound(L):.1e} | {t1:.3f} | {dis} ({dis_bound:.2f}) | {float(r['greedy_agree']):.3f} | "
               f"{worst['K'][0]:.2f} | {worst['V'][0]:.2f} | {worst['K'][1]:.2f} | {worst['V'][1]:.2f} | {'yes' if ok else '**no**'} |")
out.append('')
out.append(f'All cross-check rows within the (a) tolerances: **{"yes" if all_pass else "no"}**.\n')

# pooled top-1 and KL per size (all seeds of a size together)
out.append('Pooled per size (all seeds; top-1 bound = (a) rate × rows + 1 row; KL against the single-task bound, since there are '
           'fewer than 20 tasks):\n')
out.append('| ctx | rows | disagree rows (bound) | KL mean | KL bound | pass |')
out.append('|---:|---:|---|---:|---:|---|')
for L in sizes:
    cells = [r for r in xc if r['pair'] == 'cpu_vs_vk_naive' and int(r['context_tokens']) == L]
    if not cells:
        continue
    nrows = sum(int(r['rows']) for r in cells)
    dis = sum(round((1 - float(r['top1'])) * int(r['rows'])) for r in cells)
    klp = sum(float(r['kl_mean']) * int(r['rows']) for r in cells) / nrows
    b = top1_bound(L) * nrows + 1
    out.append(f"| {L} | {nrows} | {dis} ({b:.2f}) | {klp:.2e} | {kl_bound(L):.1e} | "
               f"{'yes' if dis <= b and klp <= kl_bound(L) else '**no**'} |")
out.append('')

# all-layer means of the cross-check against the floor's all-layer means
out.append('All-layer mean (mean of the 36 per-layer means) of the cross-check, per size, against the (a) floor:\n')
out.append('| ctx | K cross-check | K floor (a) | V cross-check | V floor (a) |')
out.append('|---:|---:|---:|---:|---:|')
for L in sizes:
    ks = [float(k['rel_l2_mean']) for (LL, _), v in kvx.items() if LL == L for k in v if k['kind'] == 'K']
    vs = [float(k['rel_l2_mean']) for (LL, _), v in kvx.items() if LL == L for k in v if k['kind'] == 'V']
    if not ks:
        continue
    fk = mean(floor[(floor_size(L), l, 'K')][0] for l in range(36))
    fv = mean(floor[(floor_size(L), l, 'V')][0] for l in range(36))
    out.append(f'| {L} | {mean(ks):.4f} | {fk:.4f} | {mean(vs):.4f} | {fv:.4f} |')
out.append('')

# 4. Bit-exact (c) checks -------------------------------------------------------------------------------------------------------
out.append('## 4. Within-Vulkan bit-exact checks (pair (c))\n')
out.append('| check | cells | all bit-identical |')
out.append('|---|---:|---|')
for pair in ('prefix_vs_full', 'dev_vs_host'):
    cells = [r for r in xc if r['pair'] == pair]
    out.append(f"| logits {pair} | {len(cells)} | {'yes' if cells and all(r['bit_identical'] == '1' for r in cells) else '**no**'} |")
for pair in ('dev_vs_host', 'chunk0_vs_full'):
    cells = [r for r in kv if r['pair'] == pair]
    mx = max((float(r['rel_l2_max']) for r in cells), default=float('nan'))
    n = len({(r['seed'], r['context_tokens']) for r in cells})
    out.append(f"| KV {pair} (max row rel L2 {mx:g}) | {n} | {'yes' if cells and mx == 0 else '**no**'} |")
out.append('')

# 5. Timing --------------------------------------------------------------------------------------------------------------------
out.append('## 5. Timing (Vulkan, ms; median over seeds: 32K seed 1\'s full prefill stalled for 79 min, see README)\n')
tm = defaultdict(list)
for r in timing:
    tm[(r['backend'], int(r['context_tokens']), r['step'])].append((float(r['ms']), int(r['tokens']), int(r['calls'])))


def tsum(L, step, backend='vulkan'):
    """Median over seeds of the per-seed total ms (and calls) of a step (robust to one stalled seed)."""
    by_seed = defaultdict(lambda: [0.0, 0])
    for r in timing:
        if r['backend'] == backend and int(r['context_tokens']) == L and r['step'] == step:
            by_seed[r['seed']][0] += float(r['ms'])
            by_seed[r['seed']][1] += int(r['calls'])
    if not by_seed:
        return float('nan'), 0
    ms = sorted(v[0] for v in by_seed.values())
    calls = sorted(v[1] for v in by_seed.values())
    return ms[len(ms) // 2], calls[len(calls) // 2]


out.append('| ctx | full prefill ms | full tok/s | prefix suffix ms | assemble host ms (write / shift) | host assembly tok/s | '
           'assemble device ms (copy / shift) | device assembly tok/s | shift ms per call | first token full / naive ms | TTFT naive host / full |')
out.append('|---:|---:|---:|---:|---|---:|---|---:|---:|---|---:|')
for L in sizes:
    fp, _ = tsum(L, 'full_prefill')
    ps, _ = tsum(L, 'prefix_suffix_prefill')
    ah, _ = tsum(L, 'assemble_host')
    aw, _ = tsum(L, 'assemble_host.write_rows')
    ash, shc = tsum(L, 'assemble_host.shift_keys')
    ad, _ = tsum(L, 'assemble_device')
    ac, _ = tsum(L, 'assemble_device.copy_rows')
    ads, _ = tsum(L, 'assemble_device.shift_keys')
    ff, _ = tsum(L, 'first_token_full')
    fn, _ = tsum(L, 'first_token_naive')
    out.append(f'| {L} | {fp:.0f} | {L / fp * 1000:.0f} | {ps:.0f} | {ah:.0f} ({aw:.0f} / {ash:.0f}) | {L / ah * 1000:,.0f} | '
               f'{ad:.0f} ({ac:.0f} / {ads:.0f}) | {L / ad * 1000:,.0f} | '
               f'{ash / shc if shc else float("nan"):.2f} | {ff:.0f} / {fn:.0f} | {(ah + fn) / (fp + ff):.3f} |')
out.append('')
enc = [r for r in timing if r['backend'] == 'vulkan' and r['step'] == 'encode_chunk']
rd = [float(r['ms']) for r in timing if r['backend'] == 'vulkan' and r['step'] == 'encode_chunk.read_rows']
cr = [float(r['ms']) for r in timing if r['backend'] == 'vulkan' and r['step'] == 'encode_chunk.create_cache']
cenc = [float(r['ms']) for r in timing if r['backend'] == 'vulkan' and r['step'] == 'cpu_encode_chunk']
if enc:
    e = sorted(float(r['ms']) for r in enc)
    out.append(f'Chunk encode (512 tokens, {len(e)} encodes): Vulkan median {e[len(e) // 2]:.0f} ms '
               f'(create cache {mean(cr):.0f}, host readback of 36 layers {mean(rd):.0f}, forward ≈ {mean(e) - mean(rd) - mean(cr):.0f} ms mean); '
               f'CPU median {sorted(cenc)[len(cenc) // 2] if cenc else float("nan"):.0f} ms ({len(cenc)} encodes, same process).\n')

(DATA / 'summary.md').write_text('# G1 summary (generated by summarize.py)\n\n' + '\n'.join(out) + '\n', encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
print('\n'.join(out))
