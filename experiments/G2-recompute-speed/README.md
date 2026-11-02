# G2: single-pass selective recompute on Vulkan, and does chunk reuse beat full prefill? (Phase G Task 4)

## G2b: tiled ATTN_QPOS kernel (dotLLM #1540 / PR #1541) — reuse with recompute now beats full prefill

**Result in one line:** with the tiled per-query-position attention, chunk reuse with single-pass selective recompute beats full prefill
**at every measured budget (5–20 %) and size (2K–32K) when the chunks are device-resident**:
- Speedups grow with context: ~4–8× at 2K, ~9–20× at 8K, ~13–37× at 16K; 61–67× at 32K (5 %).
- **Host-write entries** (the Phase S store's read path) still win: 1.5–1.8× at 2K, 3.7–4.8× at 8K, 6.7–10× at 16K.
- **Cold reuse** (encode + readback before the request) loses at 2K / 8K (0.22× / 0.5×) and roughly breaks even from 16K (1.1–1.2×).
- **Numerics are unchanged:**
  - Tiled vs the old reference kernel, on the same contexts and forward shape: pair (d) K 9.4e-4 vs 8.9e-4, KL 2.73e-4 for both.
  - Quality vs Vulkan full prefill and the comparison with E4 match G2 to within a task or two.
- The old G2 sections below (Part 1) measured the reference kernel and stay as they were.

**Build and kernel.**
- Merge: dotLLM `feature/chunk-reuse-vulkan-tiled` = `feature/chunk-reuse-vulkan` (`bac190ab`) plus a merge of
  `perf/vulkan-attn-qpos-tiled` @ `9ddf5f00` (PR #1541, before merge). The merge is `1421f319`.
- Our commits on top:
  - `9236e053`: the recomputer refuses a model without ATTN_QPOS up front (`SupportsQueryPositionAttention`); the tests know about the
    tiled kernel; new tiled-vs-reference test.
  - `7bef8f38`: the lab logs the kernel and a `qpos_tiled_layers` column.
- **Measured commit:** `9ddf5f00`'s kernel. The later `3ebc0959` (regenerated scalar GQA blobs; `*_qpos` blobs unchanged) and the dev merge
  of #1541 were not re-measured.
- The `ref` arms set `DOTLLM_VULKAN_ATTN_QPOS=ref`, which loads the old #1534 kernel only.
- Every timed recompute arm records `qpos_tiled_layers` = 36 × forwards (tiled) or 0 (ref), so the routing is verified per row of the CSVs.
- **Every single-pass forward is capped at 128 rows**, so each GPU submit stays short (≤ ~0.3 s for recompute submits; full prefill uses
  512-row blocks, 256 at 32K).

### Tests (synthetic model, `logs/g2b-unit-tests.log`)

- ChunkReuse + query-position suite:
  - Tiled: 307 / 308 pass, 1 skipped (their benchmark).
  - `DOTLLM_VULKAN_ATTN_QPOS=ref`: 306 / 308 pass, 2 skipped (benchmark; our tiled-vs-ref test).
- **Two of our tests had pinned the reference kernel's plain-F32 exactness.** They are now kernel-aware: tight when the reference kernel ran,
  the cross-kernel 1e-2 when the tiled one did.
  - All positions recomputed vs the CPU full prefill: 1e-4 (reference) or 1e-2 (tiled).
  - Row 0 and single-vs-per-run at L-1 (the per-run tail row takes the ordinary kernel): same pattern.
- **Tiled vs the CPU on the synthetic model:** 1.8e-3 (the reference kernel gave 5e-6). Tiled vs the Vulkan full prefill: 2.6e-3.
- **New test:** tiled vs reference kernel on a scattered selection, within 1e-2, with the routing checked through
  `AttentionQueryPositionsTiledCount`.

### Speed (timing groups, 3 repeats, median over contexts of the per-context median; every arm `qpos_tiled_layers` > 0)

Warm TTFT = device-copy assembly (incl. RoPE shift) + single-pass recompute, chunk_starts selection; ratio = full prefill / TTFT.

| ctx (contexts) | full prefill | 5 % | 10 % | 20 % | host-write entries (5–20 %) | cold: encode + host write (5–20 %) |
|---|---:|---|---|---|---|---|
| 2K (8) | 1.56 s | 0.20 s (**7.8×**) | 0.27 s (**5.9×**) | 0.38 s (**4.1×**) | 1.5–1.8× | 0.22× |
| 8K (2) | 19.7 s | 1.00 s (**19.7×**) | 1.33 s (**14.9×**) | 2.10 s (**9.4×**) | 3.8–4.8× | 0.48–0.50× |
| 16K (1) | 71.0 s | 1.94 s (**36.6×**) | not run | 5.01 s (**14.2×**) | 7.0–10.0× | 1.13–1.19× |
| 32K (1, 1 repeat) | 305 s (256-row blocks; G1's 512-row prefill of another 32K context: 274 s) | 4.5 s (**67×**; 61× against 274 s) | not run | not run | 21–24× (5 %) | 2.4–2.7× (5 %) |

**Repeat runs (the 2K and 8K timing groups were rerun because of the disclosed GPU overlap; `timing-b-{2k,8k}-r2.csv`):**
- The **reuse side reproduces.** Warm TTFT at 2K: 0.25 / 0.33 / 0.46 s at 5 / 10 / 20 %, against 0.20 / 0.27 / 0.38 s. At 8K: 0.98 / 1.32 / 2.12 s,
  against 1.00 / 1.33 / 2.10 s.
- The reruns were noisier: from 21:59 UTC another session's full Debug unit-test run (`chunk-cache` worktree, `testhost` PID 9368) ran
  alongside, holding neither lock.
  - At 8K it inflated one context's full prefill to 31 s, against 19 s.
  - Its speedups (2K 4.0–7.4×, 8K 11.7–25.7×) are therefore not used. The first-run figures above are the primary ones.
- The first run had dotllm-97's ~60 short unit tests at an unknown time, but its repeat spreads were ≤ 1.16 on every recompute and
  full-prefill arm. The exceptions were a few assembly repeats (up to 4.3×, one repeat each; the medians absorb them).

- **The attention-kernel control flips.** The same 128 rows recomputed one row inside the cache (ATTN_QPOS) are now **faster** than as the
  tail through the ordinary kernel:

  | ctx | tiled ATTN_QPOS | ordinary flash-coopmat tail |
  |---|---:|---:|
  | 2K | 74 ms | 177 ms |
  | 8K | 145 ms | 655 ms |
  | 16K | 226 ms | 1.25 s |

  The old reference kernel took 3.3 s (2K) to 18.5 s (8K) for the same rows.
- **Same-build A/B (`ref` arm, 2K, afclaude, chunk_starts 5 %):**
  - Single pass: 1.34 s (ref) vs 0.11 s (tiled), 12× faster.
  - 102-row control: 2.53 s vs ~0.07 s.
- **Random selections cost the same as chunk_starts in the single pass** (within ~10 %).
- **Per-run is now the slow mode:** 2.5–5× slower than the single pass for chunk_starts, and 17–34× for random selections, which need one
  forward per ~1.25 rows. Only the single pass makes reuse pay.
- **Where the time goes at 20 %:**
  - The recompute is ~75 % of TTFT at 2K and 8K (0.29 / 0.38 s; 1.59 / 2.10 s); assembly is the rest.
  - At 2K, host-write assembly (0.77 s) is now the largest cost when entries are not device-resident.
  - Encode + readback (6 s at 2K, 36 s at 8K, 52 s at 16K) is what keeps cold reuse from winning. G1's `ReadRows` request still matters
    for the store's write path.

### Break-even (with the tiled kernel)

Reuse is not near any break-even with warm entries: 20 % recompute at 2K costs 0.29 s of a 1.48 s budget (full prefill − assembly).
- **Highest budget that still breaks even at 2K:** the recompute is ~linear in rows at ~0.7 ms per row (0.11 s / 102 rows → 0.29 s /
  410 rows). It would take ~2,000 rows, essentially the whole context, so at 2K reuse with recompute wins for any budget up to ~100 %.
  This is an extrapolation.
- **With host-write assembly at 2K:** break-even near ~95 % (0.77 s assembly + 0.7 ms per row against 1.56 s). Also an extrapolation.

### Numerics (2K eval, 20 contexts / 28 tasks, and 8K eval, 2 contexts; 128-row batches)

| pair | 2K tiled | 2K ref (5 contexts, same shape) | 8K tiled | floor |
|---|---|---|---|---|
| (d) Vulkan prefill in 128-row blocks vs all positions single-pass in 128-row batches over a cache one row longer | K 7.9e-4 / V 1.5e-3 (20 contexts); same 5 contexts: 9.4e-4 / 1.8e-3; KL 2.65e-4, top-1 0.997, \|Δ NLL\| ≤ 0.031, EM 28/28 | K 8.9e-4 / V 1.7e-3; KL 2.73e-4 | K 6.3e-4 / V 1.2e-3; KL 2.7e-4 | G2 (d) at 512 rows: 5.0e-4 / 9.5e-4, KL 2.6e-4 |
| per-run vs single pass, per recomputed row | ≤ 0.80× (b, 64) all-layer, ≤ 1.03× worst layer | — | ≤ 0.2× (b, 64) whole cache | (b, 64) |
| CPU per-run vs Vulkan single pass (random 10 %, 6 contexts / 10 tasks) | K/V 1.12× / 1.09× of (a); KL 4.0e-3 | — | — | (a) |

- **Pair (d) at 128 rows sits ~1.6–2.4× the (b, 2048) floor on means, with heavy p99 tails (up to ~20×).** The reference kernel shows the
  same at this shape on the same contexts (K 8.9e-4 vs 9.4e-4; p99 ratio 20.8 vs 20.3). So the tail belongs to the 128-row pair, not to
  the tiled kernel. Logits are unaffected: KL 2.7e-4 either way, the same as G2's 512-row (d).
- **The tiled kernel adds nothing measurable to the recompute numerics:** every K/V and logits figure is within a few % of the reference
  kernel at the same shape.

### Quality (2K, 28 tasks, single pass, tiled; vs Vulkan full prefill)

| arm | KL vs full | top-1 | masked-call NLL (full 0.43) | EM (full 28) |
|---|---:|---:|---:|---:|
| naive | 0.372 | 0.827 | 4.86 | 5 |
| chunk_starts 5 / 10 / 20 % | 0.112 / 0.116 / 0.068 | 0.93 / 0.94 / 0.96 | 1.79 / 1.92 / 0.99 | 18 / 17 / 24 |
| random 5 / 10 / 20 % | 0.337 / 0.326 / 0.281 | 0.84 / 0.84 / 0.85 | 4.27 / 4.11 / 3.42 | 8 / 6 / 11 |

- Same tasks and selections as E4 (CPU): arm means within 0.04 nats, except random 20 % (−0.11). EM within 1 task, except random 20 %
  (+3).
- The kernel does not change quality. What limits reuse now is quality, not speed:
  - Even at 20 %, chunk_starts gets 24 of 28 masked calls (full prefill: 28), and random 11.
  - Better selectors (query relevance, hybrid; Task 5 probe) are the next lever. At 8K the KL to full is 0.19–0.37 for chunk_starts
    (5 unvalidated tasks).

### Verdict

**Yes: with the tiled kernel, reuse with single-pass recompute beats full prefill on this iGPU** at every measured budget (5–20 %) and size
(2K–32K), when the chunks are device-resident (4–37×). With host-written entries it also wins (1.5–10×). Only cold reuse loses at 2K / 8K.
The remaining gap to full-prefill quality (EM 24 / 28 at 20 % with the best structural selector) is now the binding constraint, not speed.

Caveats:
- Seed 0; 8 / 2 / 1 / 1 contexts; medians without bootstrap intervals.
- 16K and 32K are one context each (32K: one repeat).
- The tiled kernel was measured at `9ddf5f00` before its merge.
- **Overlap (disclosed by dotllm-97):** their #1540 agent ran ~60 short GPU unit tests during the first G2b timing groups, without the lock.
  Rerunning 2K and 8K reproduced the reuse timings. The reruns were themselves overlapped by another session's unit-test run, and their
  full-prefill times are inflated, so the first run stays primary.
- No machine misbehaviour during G2b (no heartbeat gaps, no resets).

---

# Part 1: G2 with the reference ATTN_QPOS kernel (dotLLM #1534), as measured before #1540

**Result in one line:** single-pass selective recompute on Vulkan is correct, but it is **slow**. It matches the per-run loop and the CPU
within the floors, and its attention kernel adds no more error than a 512-vs-2048-row batching change. With the current per-query-position
attention, **chunk reuse with recompute roughly ties full prefill at the smallest budget on the smallest context, and loses everywhere
else**. Taking the faster of single-pass and per-run at each point:
- 2K, 5 % with chunk_starts: 1.07× (a tie within the per-context spread; seed 0, no intervals).
- 2K, 10 % and 20 %: 0.56× and 0.28×.
- 8K, 5 %: 0.96×; 8K, 20 %: 0.20×.
- 16K, 5 %: ~0.7–0.85× (estimate; the measured 16K recompute arms ran ~3.5× slow, see the 16K section).

The cause is one kernel. ATTN_QPOS (dotLLM #1534) is 18–28× slower than the ordinary prefill attention on the same rows at 2K, 8K and
16K (control arm). As whole-forward time per (recomputed row × visible key) over 36 layers, that is 13–19 µs at every size. A GPU-timestamp
profile puts 97–99.6 % of the ATTN_QPOS forward in the attention kernel. Only naive
concatenation (no recompute) is clearly faster than full prefill (22× at 2K), and it loses the quality E4 measured. The request for the
Vulkan owner is in `vulkan-primitive-requests.md` §5.

## Verdict: does chunk reuse beat full prefill here?

**Not with recompute, and not with the current kernel.** It is a tie at best (2K, 5 %) and a loss at every larger budget or context.
- Time to first token (TTFT) of a reused context = assembly (+ RoPE shift) + selective recompute.
- The query forward afterwards is the same in both flows and is left out.
- Ratios are full-prefill time / reuse TTFT (above 1 = reuse wins).
- All rows below use warm entries (device-resident chunks, device-copy assembly) and the chunk_starts selection.
- Each cell takes the faster recompute arm. With these few, long runs that is per-run at every point; the single-pass value is in
  brackets.
- **Point estimates only:** seed 0, 8 / 2 / 1 contexts, no bootstrap intervals (deviation from the plan's "≥ 3 seeds with paired,
  cluster-bootstrapped intervals").
  - At 2K, single-pass chunk_starts 5 % alone ranges 0.95–1.80 s across the 8 contexts.
  - The 1.07× and 0.96× cells are therefore ties, not wins or losses.

| ctx | full prefill | naive (assembly only, device copy) | reuse, 5 % recompute | 10 % | 20 % | 20 % if ATTN_QPOS cost what the ordinary kernel costs (control arm) |
|---:|---:|---|---|---|---|---|
| 2K (8 contexts) | 1.66 s | 76 ms (**22× faster**) | 1.54 s (1.07×) [single 1.68 s, 0.99×] | 2.97 s (0.56×) [3.29 s, 0.50×] | 5.99 s (0.28×) [6.69 s, 0.25×] | ≤ ~0.58 s (~2.8× faster) |
| 8K (2 contexts) | 19.1 s | 0.31 s (**62× faster**) | 20.0 s (0.96×) [26.3 s, 0.73×] | 46.3 s (0.41×) [52.3 s, 0.37×] | 93.5 s (0.20×) [104.5 s, 0.18×] | ≤ ~9 s (≥ ~2× faster) |
| 16K (1 context) | 68.6 s | 0.64 s (**107× faster**) | est. ~80–100 s (~0.7–0.85×) [est. ~100–125 s]; measured 285 / 365 s in a run with ATTN_QPOS ~3.5× slow | not run | not run | 20 % not run; at 5 %: ≤ ~12 s (≥ ~5.7× faster) |

How other choices change this:
- **Host entries** (the Phase S store's read path, `WriteRows`): assembly takes 0.5 s longer at 2K and 2.2 s longer at 8K. That turns
  the 2K 5 % tie into a loss (2.0 s).
- **Cold chunks** (encode + readback first): +5.6 s at 2K and +22 s at 8K.
  - The chunk encode alone (forward + G1's slow `ReadRows`) takes 3.4× the full prefill at 2K and 1.2× at 8K.
  - In a real store it is offline work, but here it never pays back.
- **Single pass vs per-run:**
  - chunk_starts (few long runs): per-run is **faster**, 0.9× of the single-pass time at 2K and 0.76–0.89× at 8K (and 0.78× in the slow 16K run). This is
    unexplained (not instrumented). It is not the 128-row cap: the uncapped single pass at 2K shows the same ~10 % gap.
  - random (~1 forward per 1.25 rows): per-run is 1.7–1.8× slower at 2K and ~1.04× at 8K, where attention dominates.
  - Either way every recomputed row inside the cache goes through ATTN_QPOS, so neither mode removes the attention cost.

**What it would take.**
- **Two targets.** The figures below are needed speedups of the whole recompute. Speedups of the ATTN_QPOS kernel alone follow: the
  non-attention work (matmuls, KV write, norms) does not shrink with a better kernel.
- **Bounding the non-attention work:** it is at most the ordinary-tail control's forward time for the same number of rows (0.51 s for
  410 rows at 2K, 5.3 ms per row at 8K, 13.7 ms per row at 16K).
- **Needed speedups of the ATTN_QPOS kernel** (single pass; range from "non-attention ≈ 0" to "= the control bound"):

  | point | kernel speedup to break even | kernel speedup for a 2× TTFT gain |
  |---|---|---|
  | 2K, 5 % | ~1.0× | 2.1–2.4× |
  | 2K, 10 % | 2.0–2.2× | 4.3–5.9× |
  | 2K, 20 % | 4.2–5.7× | 8.8–25× |
  | 8K, 5 % | 1.4× | 2.8–3.4× |
  | 8K, 20 % | 5.5–9.5× | ≥ 11×, and impossible if the non-attention work is at the bound (8.8 s of a 9.3 s budget) |
  | 16K, 5 % (estimated recompute 100–125 s) | 1.5–2.0× | 3.1–5.1× |

- **Ceiling:** the control arm recomputes the same 410 rows as the tail, through the ordinary kernel, in 0.51 s. A per-query-position
  kernel as fast as the ordinary one would put 20 % recompute at 2K at ≤ 0.58 s TTFT, 1.656 / 0.584 = **2.8×** faster than full prefill.
- **Length neither helps nor hurts much with this kernel:** its cost per (row × key) stays at 13–19 µs from 2K to 16K. The ratio at a fixed
  budget is set by the kernel gap, not by L.
- **With a flash-class kernel, the budget would set the ratio.** Both the recompute (f·L rows, each seeing ~L/2 keys) and the full prefill
  scale with L², so the ideal ratio is set mainly by the budget fraction f: ~2.8× at 20 % (2K) and ~5.7× at 5 % (16K). Assembly becomes
  negligible as L grows.
- **Quality is the second hurdle** (next sections):
  - Even at 20 %, chunk_starts gets 24 of 28 masked-call exact matches (full prefill: 28), and random selection 11 of 28.
  - E4's better selectors (query relevance, hybrid) need the Vulkan probe (Task 5).

## Speed (timing groups; medians over contexts of the per-context median over 3 repeats)

Full tables: `summary.md`.
- **Repeat spread** (worst max/min over a context's 3 repeats): ≤ 1.16 at 2K and ≤ 1.15 at 8K, with one exception.
- **The exception:** 8K afclaude chunk_starts 20 % rep 0 took 177 s against 93.6 / 93.8 s. It coincides with an 84-s process suspension
  (heartbeat gap 10:54–11:00 UTC); the median absorbs it.

### 2K (8 contexts, L ≈ 2,048, 12–20 symbol chunks)

| arm | time | notes |
|---|---:|---|
| full prefill, 512-row blocks / one 2048-row forward | 1.66 s / 1.66 s | 1,236 tok/s; G1 had 1.64 s |
| chunk encode, host entries (forward + readback) | 5.64 s | G1's readback (~145 MB/s) dominates |
| upload host entries to resident caches | 0.92 s | `WriteRows` |
| assembly, host write / device copy (incl. shift) | 588 ms / 76 ms | G1: 223 / 28 ms for 4 × 512-token chunks. Symbol chunks are 15 per context, so ~3.5× more calls |
| **control:** 410 rows as the tail (ordinary attention) / one row earlier (ATTN_QPOS) | **0.51 s / 11.4 s (22×)** | same forward shape and matmuls; ATTN_QPOS 15.1 µs per (row × visible key) |

| selection | rows | runs | single pass | forwards | per-run | per-run / single |
|---|---:|---:|---:|---:|---:|---:|
| chunk_starts 5 % | 102 | 14 | 1.60 s | 1 | 1.47 s | 0.9× |
| chunk_starts 10 % | 205 | 14 | 3.21 s | 1 | 2.90 s | 0.9× |
| chunk_starts 20 % | 410 | 12 | 6.61 s | 1 | 5.91 s | 0.9× |
| random 5 % | 102 | 98 | 1.72 s | 1 | 3.07 s | 1.8× |
| random 10 % | 205 | 183 | 3.23 s | 1 | 5.91 s | 1.8× |
| random 20 % | 410 | 328 | 6.51 s | 1 | 10.98 s | 1.7× |

- **Single pass:** linear in the selected rows (~16 ms per row at 2K), whether or not they are scattered.
- **Per-run:** pays ~5 ms per extra forward. It is ~10 % faster than the single pass with few runs (chunk_starts; unexplained), and
  1.7–1.8× slower with scattered rows.
- **ATTN_QPOS cost follows position:** it scales with each row's visible keys (its position), not with L.
  - The 2K single-pass and control arms and the 8K arms all fit ~15 µs per (row × visible key) to within ~20 %.
  - That figure is the whole forward (matmuls included) divided by row-keys. Net of the ordinary-tail forward it is ~14.4 µs at 2K.
- **Row cap:** `2k-cap128` (2 contexts) batches the single pass into forwards of ≤ 128 rows. At 20 % it takes 6.62 s vs 6.61 s uncapped.
  Batching costs nothing measurable, which is why the 8K/16K runs could cap every submit.

### 8K (2 contexts, L ≈ 8,190, 58 and 66 symbol chunks; single pass capped at 128 rows per forward)

The two contexts ran in two processes. A reboot at ~13:29 UTC killed the first run after it had finished context afclaude
(`timing-8k-a.csv`; the interrupted run's raw CSV and log are in `logs/`). Context docagent was rerun after the reboot
(`timing-8k-b.csv`, group `8k-timing-b`). Each value below is the mean of the two per-context medians.

| arm | time | notes |
|---|---:|---|
| full prefill, 512-row / 2048-row blocks | 19.2 s / 19.1 s | 428 tok/s; G1 had 19.2 s |
| chunk encode, host entries | 22.7 s | 1.2× the full prefill |
| upload to resident / assembly host write / device copy | 3.9 s / 2.5 s / 0.31 s | |
| **control:** 128 rows as the tail (ordinary) / one row earlier (ATTN_QPOS) | **0.68 s / 18.5 s (27×)** | ATTN_QPOS 17.8 µs per (row × visible key) |

| selection | rows | runs | single pass (forwards) | per-run | per-run / single |
|---|---:|---:|---:|---:|---:|
| chunk_starts 5 % | 410 | 61 | 26.0 s (4) | 19.7 s | 0.8× |
| chunk_starts 10 % | 819 | 56 | 52.0 s (7) | 46.0 s | 0.9× |
| chunk_starts 20 % | 1,638 | 52 | 104.2 s (13) | 93.2 s | 0.9× |
| random 5 % | 410 | 388 | 30.6 s (4) | 31.9 s | 1.0× |
| random 10 % | 819 | 735 | 60.7 s (7) | 63.1 s | 1.0× |
| random 20 % | 1,638 | 1,304 | 113.9 s (13) | 118.7 s | 1.0× |

- **Attention dominates at 8K.** The per-call overhead that made per-run slow with scattered rows at 2K is noise here (per-run / single
  ≈ 1.04).
- **With few runs, per-run is 11–24 % faster than the single pass.** This is unexplained (not instrumented). The 2K uncapped single pass
  shows the same ~10 % gap, so it is not the 128-row cap.
- **Per-context spread:** the single pass on chunk_starts differs by ~20 % between the two contexts (afclaude 23.9 s, docagent 28.1 s at
  5 %). Random selections cost 10–17 % more than chunk_starts. Not instrumented.
- **The ideal column** in the verdict table uses the control arm's ordinary-kernel cost per row at 8K (5.3 ms) for 1,638 rows:
  ~8.7 s + 0.31 s assembly ≈ 9 s, against 19.1 s for full prefill. It is an upper bound: the control rows sit at the end of the context,
  where each row sees the most keys.

### 16K (1 context, codesharp, L = 16,384, 91 symbol chunks; chunk_starts 5 % only; 64-row cap)

Three processes ran this context.

| arm | first run (16:46 UTC) | rerun (17:18 UTC, froze, see Caveats) | profiled run (17:15 UTC) |
|---|---:|---:|---:|
| full prefill, 512-row blocks | 68.6 s | 68.5 s | 68.7 s |
| chunk encode (host) / upload / assembly device | 59.9 / 10.0 / 0.64 s | 47.7 / 6.4 / 0.51 s | 52.6 / 6.5 / 0.63 s |
| **control:** 64 rows as the tail (ordinary) / one row earlier (ATTN_QPOS) | 0.88 s / **68.4 s (78×)** | 0.69 s / **19.6 s (28×)** | 0.71 s / **19.7 s (28×)** |
| chunk_starts 5 % (819 rows, 86 runs): single pass (13 forwards) / per-run | 364 s / 285 s | not reached | not run |

- **The first run's ATTN_QPOS was ~3.5× slower than in two later runs** on the same context. Its full prefill and the ordinary-kernel arms
  were normal.
  - Its 65 µs per (row × key) and "78×" are an anomaly, not a 16K effect. The two later runs give 18.7–18.8 µs, the same as 2K / 8K.
  - The cause is unknown: other agents' CPU jobs may have contended for memory, or the GPU may have been degrading. Of the two box freezes
    (Caveats), the second came ~20 min after this run.
  - Its recompute arms are therefore not used directly. **Estimate:** divide by the control's 3.5× (single ≈ 104 s, per-run ≈ 82 s), or
    use 18.8 µs × rows × mean position (single ≈ 126 s, ~13 % high at 8K). That gives a best TTFT of ~80–100 s against a 68.6 s full
    prefill, ~0.7–0.85×.
  - A clean 16K recompute timing was not obtained: the rerun froze the box during its first single-pass batches.
- **The first 16K attempt (afclaude) was really 8.5K:** the afclaude corpus has only 12.7K tokens, so the generator capped the context at
  8,549. It is kept as `logs/timing-16k-afclaude-capped-at-8549.csv` and agrees with the 8K numbers.
- **32K was not run.** At ~19 µs per (row × key), 5 % of 32K would take ~7 min of recompute against a ~275 s full prefill (G1).

### GPU-timestamp profile of the control arm (`DOTLLM_VULKAN_PREFILL_PROFILE=gpu`; review item 6)

One profiled control-only run per size (`logs/profile-{2k,16k}-profile.txt`, `timing-{2k,16k}-profile.csv`; `logs/fixround-gpu.sh`):

| ctx, rows | ordinary tail: forward / attention (GPU) | ATTN_QPOS: forward / attention (GPU) | attention kernel ratio | non-attention per forward |
|---|---|---|---:|---|
| 2K, 128 | 178 ms / 122 ms (68 %) | 3,273 ms / 3,187 ms (97.4 %) | 26× | 56–86 ms |
| 16K, 64 | 707 ms / 639 ms (90 %) | 19,720 ms / 19,640 ms (99.6 %) | 31× | 68–80 ms |

- The ATTN_QPOS forward is almost all attention, so the kernel-speedup targets above are close to their "non-attention ≈ 0" ends.
- The attention-kernel gap itself (26–31×) is slightly larger than the whole-forward control ratio (18–28×).
- The profiled 16K run did **not** reproduce the first 16K run's 68 s.

## Numerics: is the single pass right? (eval group, 2K, 20 contexts, 28 tasks)

- Tolerances are from `../G0-floor/README.md` (as of `1c0d418`).
- K/V: per-layer relative L2, pooled over contexts.
- Logits: on the E4 evaluation blocks (32 continuation rows per task).

| pair | what it isolates | K / V all-layer mean | worst layer vs floor (mean; p99) | logits | verdict |
|---|---|---|---|---|---|
| **(d)** Vulkan full prefill in 512-row blocks vs the same rows recomputed single-pass in 512-row batches over a cache one row longer | the ATTN_QPOS kernel vs the ordinary kernel, same tokens and forward shapes | **5.0e-4 / 9.5e-4** | vs (b, 2048): 1.66× / 1.61×; p99 1.50× / 1.50× | KL 2.6e-4 (max task 7.2e-4); top-1 differs on 1 row of 896; \|Δ masked NLL\| ≤ 0.031; EM 28 / 28 | **pass** (pooled bound 2×; p99 at the 1.5× edge). **New floor (d) = 5.0e-4 / 9.5e-4**, about (b, 2048) |
| per-run vs single pass, same selection (chunk_starts, random; 5/10/20 %) | one forward vs one per run | **per recomputed row:** K 2.9e-4 – 8.8e-3 / V 5.5e-4 – 1.8e-2 (whole cache: 2.9e-5 – 1.7e-3) | per recomputed row vs (b, 64): all-layer ≤ 0.81×, worst layer ≤ 1.03× | median per-task KL 3e-4; 2 of 168 task cells exceed the (b) per-task bound 1.4e-3 | **pass** on K/V; logits: note 2 |
| **(a)** CPU per-run recompute vs Vulkan single pass, random 10 %, 6 contexts / 10 tasks | backend, on the recomputed (mostly stale) state | 0.023 / 0.047 | vs (a): mean 1.12× / 1.09×; p99 **2.67× (V, layer 2)** | KL 4.1e-3: above the pooled (a) bound 3.5e-3 (1.78× the floor), which formally needs ≥ 20 tasks; max task 7.5e-3 (single-task bound 8.1e-3); top-1 differs on 4 rows of 320 | K/V means **pass**; p99 over in 5 of 72 layer-kinds (layers 2–5); mean KL over the pooled bound (10 tasks, not a formal fail); masked NLL: note 3 |

1. **The attention-kernel floor (d) is now measured.** G0 had no pair that runs ATTN_QPOS.
   - Swapping the attention kernel alone moves K/V by about as much as G0's 512-vs-2048-row batching (b, 2048), and the logits by 2.6e-4 KL.
   - So Task 4's single-pass recompute carries (b, 2048) + (d) ≈ 2× (b, 2048) at ≥ 128 rows.
   - On the synthetic F32 model, ATTN_QPOS reproduces the CPU to ~5e-6, and the ordinary Vulkan kernel is the one that differs (tests).
     Whether ATTN_QPOS also moves the real model's Vulkan path *towards* the CPU was not measured here.
2. **Single pass vs per-run.**
   - **K/V, per recomputed row** (non-selected rows are bit-identical in both caches, so the whole-cache means are diluted by 1/f):
     - ≈ 0.8× of (b, 64) all-layer, ≈ 1.0× at the worst layer, wherever one side runs 17–127-row MMQ forwards. Those are the per-run
       chunk_starts runs (~40 rows), and the single pass at 2K 5 % (102 rows).
     - ≈ 0.03× elsewhere: per-run random (1–2-row forwards) vs a ≥ 128-row single pass, i.e. at the (b, 1) level.
     - That is what the forward sizes predict, so it is a pass, but at the floor, not far below it.
   - **8K:** 0.07–0.17× of (b, 64), except chunk_starts 20 % at 0.78×.
   - **Logits outliers:** the 2 cells over the KL bound each come from one confident row that flips. The extreme one has KL 28.7 on 1 of
     32 rows, with masked NLL 0.086 vs 0.089. Against the full prefill it is the per-run arm that flipped (max row KL 9.3, single 0.40).
   - **Masked-call NLL:** the differences exceed G0's full-prefill (b) bound (0.15 nats) on 5, 2 and 4 of 28 random-selection tasks at
     5 / 10 / 20 %, max 0.35. G0 noted that this absolute Δ scales with the NLL itself. These states are mostly stale (masked NLL 3.4–4.3,
     vs 0.43 for full prefill), and G0's NLL bounds, measured on full prefills, are too tight for them.
3. **CPU vs Vulkan on the recomputed state.**
   - K/V means sit at the (a) floor (1.09–1.12×), as for G1's naive caches. The p99 overshoot is in shallow layers 2–5 only.
   - The mean KL (4.1e-3) is above the pooled (a) bound (3.5e-3), as G1 also saw on naive caches. With 10 tasks the pooled rule does not
     formally apply, but it points the same way as the NLL.
   - The masked-call NLL differs by more than the (a) bound (0.23) on 3 of 10 tasks (max 1.48).
   - The E4 comparison below shows the same for **naive** caches (5 of 23 tasks over 0.23, max 1.8). So this is the stale state amplifying
     the backend difference, not the recompute. That was G1's hypothesis; it now holds on 23 tasks.

## Quality: recomputed cache vs Vulkan full prefill, and vs E4 on the CPU (2K, 28 tasks)

| arm | KL vs full (mean) | top-1 | masked-call NLL (full 0.43) | EM (full 28 / 28) |
|---|---:|---:|---:|---:|
| naive | 0.372 | 0.827 | 4.86 | 5 |
| chunk_starts 5 / 10 / 20 %, single pass | 0.113 / 0.116 / 0.059 | 0.93 / 0.94 / 0.96 | 1.80 / 1.94 / 0.99 | 16 / 16 / 24 |
| random 5 / 10 / 20 %, single pass | 0.338 / 0.325 / 0.281 | 0.84 / 0.84 / 0.85 | 4.29 / 4.10 / 3.40 | 7 / 7 / 11 |

Per-run gives the same numbers to within 0.01 KL and 1 EM. The table below compares E4 on the CPU per-run path with the Vulkan single pass
on the same 23 tasks and the **same selections** as E4 (E4's random seed formula and budget rounding):

| arm | E4 CPU masked NLL | Vulkan single pass | mean \|Δ\| | tasks over 0.23 | EM E4 / Vulkan |
|---|---:|---:|---:|---:|---|
| full | 0.442 | 0.438 | 0.033 | 0 | 23 / 23 |
| naive | 4.963 | 5.020 | 0.220 | 5 | 5 / 5 |
| chunk_starts 5 % | 2.051 | 2.083 | 0.149 | 6 | 13 / 12 |
| chunk_starts 10 % | 1.948 | 1.996 | 0.149 | 6 | 15 / 14 |
| chunk_starts 20 % | 1.151 | 1.121 | 0.091 | 3 | 21 / 20 |
| random 5 % | 4.493 | 4.498 | 0.250 | 8 | 5 / 5 |
| random 20 % | 3.622 | 3.494 | 0.226 | 6 | 6 / 9 |

- **E4's picture carries over.** Arm means agree to within 0.06 nats and EM to within 1 task, except random 20 % (−0.13 nats, +3 EM).
- **On full prefill**, the per-task CPU-vs-Vulkan NLL difference stays inside G0's (a) bound.
- **On every reuse state**, 3–8 of 23 tasks exceed it.

## Numerics and quality at 8K (eval group, 2 contexts, 5 unvalidated tasks)

- Single pass and pair (d) ran in 128-row batches, which are in the coopmat regime (≥ 128 rows), so the matching floor is (b, 2048) at 8K.
- **Pair (d)** (Vulkan full prefill in 128-row blocks vs the same rows recomputed single-pass in 128-row batches over a cache one row
  longer):
  - K 6.1e-4 / V 1.2e-3 all-layer, 1.24× the 8K (b, 2048) floor.
  - Worst layer 2.03× (layer 1, single-context bound 4×); layers ≥ 2 ≤ 1.66×.
  - Logits: KL 3.1e-4, top-1 0.994, \|Δ masked NLL\| ≤ 0.10. **Pass.**
- **Single pass vs per-run** (same selections):
  - K/V per recomputed row: 0.07–0.17× of (b, 64), except chunk_starts 20 % at 0.78× (whole-cache figures in `summary.md` are diluted by
    the 80–95 % unrecomputed rows).
  - KL ≤ 8e-4 per task.
  - \|Δ masked NLL\| ≤ 0.32 (8K (b) bound 0.69). **Pass.**
- **Quality vs Vulkan full prefill** (mean KL over the 5 tasks):
  - Naive 1.28.
  - chunk_starts 5 / 10 / 20 %: 0.37 / 0.26 / 0.19.
  - random: 1.24 / 1.17 / 1.05.
  - The 8K tasks are unvalidated: full prefill itself gets 1 of 5 masked calls right, so EM says nothing here.
- **The 8K (d) against the 512-row reference** (`d_vk512_vs_qpos128`) adds a 512-vs-128-row shape change on top of the kernel swap. Its
  layer 0 is 6–9× the (b, 2048) floor in relative terms. In absolute terms that is 9e-6 / 5e-5, where the floor itself is coopmat vs
  coopmat at ~1e-6.
- No CPU cross-check at 8K: the CPU per-run path takes minutes per selection there.


## Caveats

- **Deviation from the plan's statistics rule:** the plan asks for "≥ 3 seeds with paired, cluster-bootstrapped intervals".
  - G2 is seed 0 only: E4's selections on E4's contexts.
  - It reports medians over contexts with [min, max], and no bootstrap intervals.
  - The 18–28× kernel gaps and the losses at ≥ 10 % are far outside any plausible interval. The 2K 5 % (1.07×), 8K 5 % (0.96×)
    and the estimated 16K 5 % (0.7–0.85×) cells are not: they are reported as ties or estimates.
- **8K and 16K scope:** 8K has 2 contexts, and 16K is 1 context with 1 repeat at 5 % only, against 8 contexts at 2K.
- **One model, one GPU, one driver:** Qwen3-4B Q4_K_M (Q4_K/Q6_K weights). The ATTN_QPOS cost is a property of the current shader, not of
  selective recompute. The verdict is "not with this kernel", and the control arm bounds what a better kernel could give.
- **Symbol chunks** (12–20 at 2K, ~58 at 8K) make assembly several times slower than G1's 512-token chunks, because there are more calls.
  With 512-token chunks assembly would take ~28 ms at 2K (G1), which changes nothing in the verdict.
- **Selections** are structural (chunk_starts) or random. Query-relevance and graph selections need the Vulkan probe (Task 5). Their
  recompute cost per row is the same, so the speed verdict holds for them.
- **Suspension during the 2K eval run:** the lab process was suspended 08:51–09:54 UTC.
  - The run log shows a 65-min heartbeat gap. Kernel-Power logged a session transition (17→18) at 08:54 and 506/507 at 09:54.
  - The script held `ES_DISPLAY_REQUIRED` and the process held its power requests throughout.
  - Values are unaffected (eval timings are not used), and the GPU lock stayed ours (90-min staleness not reached).
  - The 8K timing run had one 84-s suspension (see Speed); one repeat was inflated and the median is unaffected.
- **Reboot:** the box rebooted at ~13:29 UTC during the 8K timing run (second context). The completed first context was kept, and the second was rerun after the reboot.
- **TDR (`TdrDelay` 10 s):**
  - Submits were capped: 512 rows (~8 s) at 2K eval, 128 rows (≤ ~19 s) at 8K, 64 rows (~20 s) at 16K.
  - Single submits of 30 s (2K smoke), ~38–60 s (8K probe) and 68 s (the slow 16K run) completed without a device reset.
- **Two unclean reboots, both while G2 ATTN_QPOS work was running** (Kernel-Power 41, "rebooted without cleanly shutting down"; no bugcheck or TDR event):
  - **First:** the 8K timing run's last heartbeat was at 11:35 UTC (context 2, chunk_starts 10 % per-run, short forwards). The box came back
    at 13:29.
  - **Second:** the 16K rerun's last log line was at ~17:20 UTC, during its first 64-row single-pass batches. The box came back at 18:51.
  - The cause is unknown. Other agents' jobs may also have been running, there is no bugcheck or TDR event, and neither freeze happened in
    a long submit. Running G2-style ATTN_QPOS workloads on this box is nonetheless **not known to be safe**. No further runs were made
    after the second freeze.
- **8K probe** (`timing-8k-probe-cap256.csv`, 1 context, 256-row cap): the cap split its "tail_ordinary" control into one ATTN_QPOS batch
  and one tail batch (fixed in `b3fd24a6`). Use only its full / encode / assembly / single / per-run rows.
- **Descriptor-set overflow:** `EncodeResident` of ~58 chunks per 8K context overflows the Vulkan model's `DescriptorSetCache` (request
  §6). Resident entries are therefore uploaded host entries, which hold the same bits (G1).


## Setup

- **Engine:** dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-vulkan`, branch `feature/chunk-reuse-vulkan`; library commits
  `91b9ddb2`, `c678c06f`, `7167d101`; lab commits `49e1da8c`, `aea9678e`, `b3fd24a6` (runs at `b3fd24a6`, dirty 0; provenance block at the
  top of each `logs/recompute-*.log`). `ChunkKvLab recompute`, Release build.
- **Hardware:** AMD Radeon 8060S (gfx1151), AMD proprietary driver 26.10.1 (LLPC), Vulkan 1.4.359; Ryzen AI MAX+ 395; Windows 11.
  GPU lock holder `chunk-vulkan-t4`, refreshed every 10 min; the script and the lab hold the keep-awake power requests (G1).
  `TdrDelay` is 10 s on this box.
- **Model:** `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` Q4_K_M @ `ae44f08e…`, F32 KV.
- **Contexts:** E4's (symbol chunker, seed 0) from the G0 corpus snapshots: 2K kept contexts (timing: the first 3/3/2 per corpus; eval: all
  20, 7/7/6, which include E4's own 18), 8K unfiltered contexts (2), 16K (1). Chunks are Roslyn symbol chunks (median ~107 tokens; 12–20
  per 2K context, ~58 per 8K context).
- **Selections:** `chunk_starts` (the first tokens of every chunk: few long runs) and `random` (E4's seed formula: many 1–2-row runs) at
  5/10/20 % of L, rounded as E4 does, so they are E4's own selections on its contexts.
- **Arms (all on Vulkan):**
  - `full512`, `full2048`: full prefill in 512- or 2048-row blocks (the TTFT reference is the faster).
  - `encode_host`: every chunk encoded (one forward into its own cache) and read back to host (`ReadRows`, G1's slow readback).
  - `upload_resident`: host entries written into their own device caches once (what a device-resident store would hold).
  - `asm_host` / `asm_device`: assembly by `WriteRows` from host entries or `CopyRowsFrom` from resident entries, each with the one-submit
    RoPE shift.
  - `single`: `SelectiveRecomputer.Recompute(..., RecomputeMode.SinglePass)`: one `Forward(selectedIds, selectedPositions, cache)` through
    the per-query-position attention (ATTN_QPOS, dotLLM #1534), batched by `--max-rows` at 8K/16K (each batch one submit).
  - `perrun`: the same selection as one `Forward` per maximal run of consecutive positions (the CPU path's algorithm, on Vulkan; every run
    inside the cache also takes ATTN_QPOS).
  - `tail_ordinary` / `tail_qpos` (control): the same k contiguous rows recomputed as the tail `[L-k, L)` (a run ending at the cache length:
    the ordinary flash/coopmat attention) or one row earlier `[L-k-1, L-1)` (ATTN_QPOS). Same forward shape and matmul regime; only the
    attention kernel differs. k = the largest budget, capped by `--max-rows`.
  - Before every recompute the naive cache is re-assembled by device copy (bit-exact each time, G1), outside the timed region.
- **Repeats:** 3 per arm in the timing groups (repeat spread ≤ 1.16, one 8K repeat excepted; see Speed). Each timing group is its own process and never requests
  all-row logits (Vulkan's all-row limit is grow-only; once widened every short forward also runs the LM head). The eval groups' timings
  are not used.
- **Eval groups** (`--eval 1`, 1 repeat): each task's E4 evaluation block (query prefix, then 32 continuation rows teacher-forced) on every
  arm against the Vulkan full prefill (KL, top-1, masked-call NLL and greedy EM); K/V of single-pass vs per-run; pair (d); the CPU per-run
  recompute of the same random-10 % selection against the Vulkan single pass on the first 6 contexts (pair (a)).

## Method and reproduction

- `./run.ps1 -Snapshots <dir with the t8-corpus-* snapshots>` (groups `2k-timing`, `2k-cap128`, `2k-eval`, `8k-timing`, `8k-eval`,
  `16k-point`), then `uv run summarize.py` → `summary.md`. Outputs are written as `*.partial` and renamed only when a run finishes.
- **Library:** `SelectiveRecomputer.Recompute(model, backend, cache, chunks|tokens, selection, mode = Auto, maxRowsPerForward)`. `Auto` is
  the single pass on Vulkan and the per-run loop on the CPU (bit-identical to the old `Run`). Refusals before anything is written: single
  pass on the CPU backend, a host model with the Vulkan backend and vice versa, a cache the backend does not accept, a non-positive row cap,
  an invalid selection. After each Vulkan forward that needs ATTN_QPOS (non-contiguous rows, or rows not ending at the cache length) the
  recomputer checks `AttentionQueryPositionsCount` moved by the layer count and throws otherwise (a model loaded without
  `attention_f32_qpos.spv` falls back to the ordinary kernel, which masks by `positions[0] + row`). The result reports the ATTN_QPOS layer
  count.
- **Tests:** `tests/DotLLM.Tests.Unit/ChunkReuse/VulkanRecomputeTests.cs`: 6 CPU tests and 8 GPU tests on the synthetic F32 model
  (`Recompute_AllPositions_EqualsFullPrefillWithinFloor`, `Recompute_SinglePosition_EqualsPerRunPathWithinFloor`,
  `Recompute_RandomSubset_VulkanVsCpu_WithinFloor`, `Recompute_NonContiguousSubset_UsesOneForwardCall` (one forward, one ATTN_QPOS dispatch
  per layer, counted with the model's counter), `Recompute_FirstAndLastPosition_Edge`, plus row-cap batching, refusals, and a model without
  the ATTN_QPOS shader). The ChunkReuse suite: 273 / 273 pass with the GPU.
  - Red phase: compile failure, `logs/red-build.log`.
  - Mutants: 17 of 18 killed in `git archive` copies (`logs/mutants-t4.log`, `logs/mutants-t4-round2.log`, `logs/mutants-t4-round3.log`;
    driver `logs/mutate4.py`).
    - Round 1 killed 14 of 16. M9 (CPU backend accepts a Vulkan model) and M16 (no cache-length guard) survived and were killed after two
      new tests.
    - Review round: M18 (descending batch order under the row cap) is killed.
    - M17 (the guard only catches a total fallback, `ran == 0`) survives. It is equivalent under the current refusals: a partial-layer
      fallback needs per-layer attention sinks or windowed layers, and the backend refuses both before any write.
- **Measured on the synthetic model (tests):** ATTN_QPOS (plain F32) reproduces the **CPU** full prefill to ~5e-6, while the ordinary Vulkan
  prefill attention differs from both by ~3e-3 past layer 0. So on that model the Vulkan-vs-CPU gap past layer 0 (G0 Scope note) is the
  ordinary attention kernel, and an all-positions recompute through ATTN_QPOS is closer to the CPU than to the Vulkan full prefill.
