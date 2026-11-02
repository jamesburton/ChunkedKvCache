"""G2 summary: speed of single-pass vs per-run selective recompute vs full prefill on Vulkan, TTFT of the assembled cache, and the
numerics (pair (d), single vs per-run, pair (a) on the recomputed state, E4 comparison). Writes summary.md next to this file.
usage: uv run summarize.py"""
import csv, gzip, math, os, sys, statistics as st
sys.stdout.reconfigure(encoding='utf-8')
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
G0 = os.path.join(HERE, '..', 'G0-floor')
E4 = os.path.join(HERE, '..', 'E4-structure-aware', 'results.csv.gz')
out = []


def p(s=''):
    out.append(s)


def read(name):
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return None
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def med(xs):
    return st.median(xs) if xs else float('nan')


def fmt_ms(x):
    if x != x:
        return '–'
    return f'{x / 1000:.2f} s' if x >= 1000 else f'{x:.0f} ms'


# ---------------------------------------------------------------- speed
def speed(label):
    if label == '8k':
        # 8K ran as two processes: context afclaude (timing-8k-a.csv, rows kept from the run the reboot interrupted, which had finished
        # that context) and context docagent (timing-8k-b.csv, rerun after the reboot).
        rows = (read('timing-8k-a.csv') or []) + (read('timing-8k-b.csv') or [])
    else:
        rows = read(f'timing-{label}.csv')
    if not rows:
        return
    ctxs = sorted({r['context_id'] for r in rows})
    L = med([int(r['context_tokens']) for r in rows])
    chunks = med([int(r['chunks']) for r in rows])
    # per context: median over repeats; then median (and range) over contexts
    per = defaultdict(lambda: defaultdict(list))
    meta = {}
    for r in rows:
        key = (r['arm'], r['selector'], int(r['budget_pct']))
        per[key][r['context_id']].append(float(r['ms']))
        meta.setdefault(key, []).append((int(r['rows']), int(r['runs']), int(r['forward_calls']), int(r['qpos_layers'])))

    def stat(key):
        ctxm = [med(v) for v in per[key].values()]
        return med(ctxm), min(ctxm) if ctxm else float('nan'), max(ctxm) if ctxm else float('nan'), ctxm

    def spread(key):
        # repeat spread: max/min over the repeats of a context, worst context
        worst = None
        for v in per[key].values():
            if len(v) > 1 and min(v) > 0:
                worst = max(worst or 0.0, max(v) / min(v))
        return '—' if worst is None else f'{worst:.2f}'

    p(f'## Speed, {label} ({len(ctxs)} contexts, median L {L:.0f}, median {chunks:.0f} symbol chunks)')
    p()
    p('Median over contexts of the per-context median over repeats; [min, max] over contexts; "rep" = worst max/min ratio over a context\'s repeats.')
    p()
    p('| arm | median | [min, max] | rep | tok/s |')
    p('|---|---:|---|---:|---:|')
    for arm in ['full256', 'full512', 'full2048', 'encode_host', 'upload_resident', 'asm_host', 'asm_device']:
        key = (arm, '', 100 if arm.startswith('full') else 0)
        if key not in per:
            continue
        m, lo, hi, _ = stat(key)
        p(f'| {arm} | {fmt_ms(m)} | [{fmt_ms(lo)}, {fmt_ms(hi)}] | {spread(key)} | {L / (m / 1000):,.0f} |')
    p()
    fulls = [stat((a, '', 100))[0] for a in ('full256', 'full512', 'full2048') if (a, '', 100) in per]
    if not fulls:
        return
    best_full = min(fulls)
    asm_d = stat(('asm_device', '', 0))[0]
    ups = stat(('upload_resident', '', 0))[0] if ('upload_resident', '', 0) in per else float('nan')
    asm_h = stat(('asm_host', '', 0))[0]
    enc_h = stat(('encode_host', '', 0))[0]
    if ('tail_qpos', '', max(k[2] for k in per)) in per or any(k[0] == 'tail_qpos' for k in per):
        kq = next(k for k in per if k[0] == 'tail_qpos')
        ko = ('tail_ordinary', '', kq[2])
        k_rows = med([m[0] for m in meta[kq]])
        q, o = stat(kq)[0], stat(ko)[0]
        # each qpos row at position ~L-k/2 sees ~L-k/2 keys; the ordinary-tail arm runs the same matmuls, so q - o is the extra attention cost
        keys = k_rows * (L - k_rows / 2)
        p(f'**Attention-kernel control** ({k_rows:.0f} contiguous rows, one forward each, same matmul shape): as the tail [L-k, L) '
          f'(ordinary kernel) {fmt_ms(o)}; one row earlier [L-k-1, L-1) (ATTN_QPOS) {fmt_ms(q)}: {q / o:.1f}×. ATTN_QPOS total '
          f'{q * 1000 / keys:.1f} µs per (row × visible key) over 36 layers; the ordinary tail {o / k_rows:.1f} ms per row.')
        p()
    p(f'Full prefill reference for the TTFT ratios: the fastest full-prefill block size measured, {fmt_ms(best_full)}.')
    p()
    p('| selector | budget | rows | runs (per-run forwards) | single-pass | forwards | per-run | per-run / single | '
      'TTFT warm = asm(device)+single | speedup vs full | best arm TTFT warm = asm(device)+min(single, per-run) | speedup | '
      'TTFT host = asm(host)+single | speedup | cold = encode(host)+asm(host)+single | speedup |')
    p('|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    sels = sorted({k[1] for k in per if k[0] == 'single'})
    for sel in sels:
        for b in sorted({k[2] for k in per if k[0] == 'single' and k[1] == sel}):
            s = stat(('single', sel, b))[0]
            pr = stat(('perrun', sel, b))[0]
            mrows = med([m[0] for m in meta[('single', sel, b)]])
            mruns = med([m[1] for m in meta[('single', sel, b)]])
            mcalls = med([m[2] for m in meta[('single', sel, b)]])
            warm = asm_d + s
            hostt = asm_h + s
            cold = enc_h + asm_h + s
            bestw = asm_d + min(s, pr)
            p(f'| {sel} | {b} % | {mrows:.0f} | {mruns:.0f} | {fmt_ms(s)} | {mcalls:.0f} | {fmt_ms(pr)} | {pr / s:.2f}× | {fmt_ms(warm)} | '
              f'{best_full / warm:.2f}× | {fmt_ms(bestw)} | {best_full / bestw:.2f}× | {fmt_ms(hostt)} | {best_full / hostt:.2f}× | {fmt_ms(cold)} | {best_full / cold:.2f}× |')
    p()


# ---------------------------------------------------------------- numerics
def g0_floor(size):
    rows = read(os.path.join('..', 'G0-floor', f'floor-{size}.csv'))
    f = {}
    for r in rows or []:
        if r['kind'] in ('K', 'V'):
            f[(r['pair'], int(r['layer']), r['kind'])] = (float(r['rel_l2_mean']), float(r['rel_l2_p99']))
        else:
            f[(r['pair'], 'logits')] = float(r['kl_mean'])
    return f


def kv_vs_floor(label, size, pair_map):
    pooled = read(f'kvpooled-{label}.csv')
    if not pooled:
        return
    floor = g0_floor(size)
    p(f'### K/V pooled over contexts ({label}), against G0 {size}')
    p()
    p('All-layer = mean of the 36 per-layer means. Ratio = worst per-layer mean (p99) over the matching G0 per-layer mean (p99).')
    p()
    p('| pair | contexts | K all-layer | V all-layer | worst-layer mean ratio K / V | worst-layer p99 ratio K / V | G0 pair | G0 K / V all-layer |')
    p('|---|---:|---:|---:|---|---|---|---|')
    by = defaultdict(dict)
    nctx = defaultdict(set)
    for r in read(f'kv-{label}.csv') or []:
        nctx[r['pair']].add(r['context_id'])
    nctx = {k: len(v) for k, v in nctx.items()}
    for r in pooled:
        by[r['pair']][(int(r['layer']), r['kind'])] = (float(r['rel_l2_mean']), float(r['rel_l2_p99']))
    for pair, d in by.items():
        g0pair = next((g for pre, g in pair_map if pair.startswith(pre)), None)
        layers = sorted({l for l, _ in d})
        k_all = st.mean(d[(l, 'K')][0] for l in layers)
        v_all = st.mean(d[(l, 'V')][0] for l in layers)
        if g0pair and (g0pair, 0, 'K') in floor:
            rm = {kind: max(d[(l, kind)][0] / floor[(g0pair, l, kind)][0] for l in layers) for kind in 'KV'}
            rp = {kind: max(d[(l, kind)][1] / floor[(g0pair, l, kind)][1] for l in layers) for kind in 'KV'}
            gk = st.mean(floor[(g0pair, l, 'K')][0] for l in layers)
            gv = st.mean(floor[(g0pair, l, 'V')][0] for l in layers)
            p(f'| {pair} | {nctx[pair]} | {k_all:.3g} | {v_all:.3g} | {rm["K"]:.2f} / {rm["V"]:.2f} | {rp["K"]:.2f} / {rp["V"]:.2f} | {g0pair} | {gk:.3g} / {gv:.3g} |')
        else:
            p(f'| {pair} | {nctx[pair]} | {k_all:.3g} | {v_all:.3g} | – | – | – | – |')
    p()


def tasks_table(label):
    rows = read(f'tasks-{label}.csv')
    if not rows:
        return
    p(f'### Logits per pair ({label}): mean over tasks')
    p()
    p('| pair | selector | budget | tasks | KL mean | KL max (task) | top-1 | mean |Δ mask NLL| | max |Δ mask NLL| | EM ref / cmp |')
    p('|---|---|---:|---:|---:|---:|---:|---:|---:|---|')
    g = defaultdict(list)
    seen = set()
    for r in rows:
        key = (r['context_id'], r['task_index'], r['pair'], r['selector'], r['budget_pct'])
        if key in seen:
            continue
        seen.add(key)
        g[(r['pair'], r['selector'], int(r['budget_pct']))].append(r)
    for (pair, sel, b), rs in sorted(g.items()):
        kl = [float(r['kl_mean']) for r in rs]
        d = [abs(float(r['mask_nll']) - float(r['ref_mask_nll'])) for r in rs]
        p(f'| {pair} | {sel} | {b} | {len(rs)} | {st.mean(kl):.3g} | {max(kl):.3g} | {st.mean(float(r["top1"]) for r in rs):.3f} | '
          f'{st.mean(d):.3g} | {max(d):.3g} | {sum(int(r["ref_mask_em"]) for r in rs)} / {sum(int(r["mask_em"]) for r in rs)} |')
    p()


def e4_compare(label):
    rows = read(f'tasks-{label}.csv')
    if not rows or not os.path.exists(E4):
        return
    e4 = defaultdict(dict)
    with gzip.open(E4, 'rt', newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['chunker'] == 'symbol' and r['seed'] == '0' and r['mode'] == 'kept':
                e4[(r['task_id'], r['arm'], int(float(r['budget_pct'])))] = r
    p(f'### Against E4 (CPU per-run) on the same tasks and selections ({label})')
    p()
    p('Same context, task and selection (E4 random seed formula and budget rounding). Masked-call NLL is absolute, so CPU-per-run (E4) and '
      'Vulkan single-pass compare directly; the G0 (a) per-task bound at 2K is 0.23 nats.')
    p()
    p('| arm | budget | tasks | E4 CPU mask NLL mean | Vulkan single-pass mean | mean |Δ| | max |Δ| | over 0.23 | EM E4 / Vulkan |')
    p('|---|---:|---:|---:|---:|---:|---:|---:|---|')
    g = defaultdict(list)
    for r in rows:
        if r['pair'] == 'single_vs_vk512':
            k = (r['task_id'], r['selector'], int(r['budget_pct']))
            if k in e4:
                g[(r['selector'], int(r['budget_pct']))].append((float(e4[k]['mask_nll']), float(r['mask_nll']), int(e4[k]['mask_em']), int(r['mask_em'])))
        if r['pair'] == 'naive_vs_vk512':
            k = (r['task_id'], 'naive', 0)
            if k in e4:
                g[('naive', 0)].append((float(e4[k]['mask_nll']), float(r['mask_nll']), int(e4[k]['mask_em']), int(r['mask_em'])))
            k = (r['task_id'], 'full', 100)
            if k in e4:
                g[('full', 100)].append((float(e4[k]['mask_nll']), float(r['ref_mask_nll']), int(e4[k]['mask_em']), int(r['ref_mask_em'])))
    for (arm, b), v in sorted(g.items()):
        d = [abs(a - c) for a, c, _, _ in v]
        p(f'| {arm} | {b} | {len(v)} | {st.mean(a for a, _, _, _ in v):.3f} | {st.mean(c for _, c, _, _ in v):.3f} | {st.mean(d):.3f} | {max(d):.3f} | '
          f'{sum(x > 0.23 for x in d)} | {sum(e for _, _, e, _ in v)} / {sum(e for _, _, _, e in v)} |')
    p()


p('# G2 summary (generated by summarize.py)')
p()
p('# Part 1: G2 (reference ATTN_QPOS kernel, dotLLM #1534)')
p()
for label in ['2k', '2k-cap128', '2k-profile', '8k', '16k-first', '16k-rerun-partial', '16k-profile', '8k-probe-cap256']:
    speed(label)
PAIRS = [('d_vk2048_vs_qpos', 'b_vk512_vs_vk2048'), ('d_vk128_vs_qpos', 'b_vk512_vs_vk2048'), ('d_vk512_vs_qpos128', 'b_vk512_vs_vk2048'), ('d_vk512_vs_qpos', 'b_vk512_vs_vk2048'),
         ('perrun_vs_single', 'b_vk512_vs_vk64'), ('a_cpuperrun', 'a_cpu_vs_vk512')]
for label in ['b-2k', 'b-2k-r2', 'b-2k-ref', 'b-8k', 'b-8k-r2', 'b-16k', 'b-32k']:
    if label == 'b-2k':
        p('# Part 2: G2b (tiled ATTN_QPOS, dotLLM #1540 / PR #1541; 128-row cap)')
        p()
    speed(label)
for label, size in [('2k-eval', '2k'), ('8k-eval', '8k'), ('b-2k-eval', '2k'), ('b-2k-eval-ref', '2k'), ('b-8k-eval', '8k')]:
    if read(f'tasks-{label}.csv'):
        p(f'## Numerics and quality, {label}')
        p()
        kv_vs_floor(label, size, PAIRS)
        tasks_table(label)
        if size == '2k':
            e4_compare(label)  # E4 ran at 2K only
with open(os.path.join(HERE, 'summary.md'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(out) + '\n')
print('\n'.join(out))
