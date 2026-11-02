# G2: single-pass selective recompute on Vulkan, and does chunk reuse beat full prefill? (Phase G Task 4)

**Result in one line:** single-pass selective recompute on Vulkan is correct, but it is **slow**. It matches the per-run loop and the CPU
within the floors, and its attention kernel adds no more error than a 512-vs-2048-row batching change. With the current per-query-position
attention, **chunk reuse with recompute does not beat full prefill on this iGPU at any measured budget or context size**:
- At 2K, recomputing 5 % costs as much as a full prefill, and 20 % costs about 4× more.
- At 8K, even 5 % is slower than a full prefill.

The cause is one kernel. ATTN_QPOS (dotLLM #1534) costs ~15 µs per (recomputed row × visible key) over 36 layers, ~20× the ordinary
prefill attention on the same rows. Only naive concatenation (no recompute) is faster than full prefill (~20× at 2K), and it loses the
quality E4 measured. The request for the Vulkan owner is in `vulkan-primitive-requests.md` §5.

## Verdict: does chunk reuse beat full prefill here?

**No, not with recompute, and not with the current kernel.**
- Time to first token (TTFT) of a reused context = assembly (+ RoPE shift) + selective recompute.
- The query forward afterwards is the same in both flows and is left out.
- Ratios are full-prefill time / reuse TTFT (above 1 = reuse wins).
- All rows below use warm entries (device-resident chunks, device-copy assembly), the chunk_starts selection and the single pass.

| ctx | full prefill | naive (assembly only, device copy) | reuse, 5 % recompute | 10 % | 20 % | 20 % if ATTN_QPOS cost what the ordinary kernel costs (control arm) |
|---:|---:|---|---|---|---|---|
| 2K (8 contexts) | 1.66 s | 76 ms (**22× faster**) | 1.68 s (1.0×) | 3.29 s (0.5×) | 6.69 s (0.25×) | ~0.58 s (~2.9× faster) |
| 8K (2 contexts) | 19.1 s | 0.31 s (**62× faster**) | 26.3 s (0.7×) | 52.3 s (0.4×) | 104.6 s (0.2×) | ≤ ~9 s (≥ ~2× faster) |

Every other way of counting is worse for reuse:
- **Host entries** (the Phase S store's read path, `WriteRows`): assembly takes 0.5 s longer at 2K and 2.2 s longer at 8K.
- **Cold chunks** (encode + readback first): +5.6 s at 2K and +22 s at 8K.
  - The chunk encode alone (forward + G1's slow `ReadRows`) takes 3.4× the full prefill at 2K and 1.1× at 8K.
  - In a real store it is offline work, but here it never pays back.
- **Per-run instead of single pass:**
  - Few runs (chunk_starts): about the same (0.9×).
  - Scattered selections (random, ~1 forward per 1.25 rows): 1.7–1.8× slower.
  - The single pass removes the per-call overhead. It cannot remove the attention cost: in either mode, every recomputed row inside the
    cache goes through ATTN_QPOS.

**What it would take.**
- **Break-even:** at 2K the recompute must fit into full prefill − assembly ≈ 1.58 s. ATTN_QPOS must be about 1.0× / 2.0× / 4.2× faster at
  5 / 10 / 20 %. A 2× TTFT gain at 20 % needs it ~9× faster.
- **Ceiling:** the control arm recomputes the same 410 rows as the tail, through the ordinary kernel, in 0.51 s. A flash-class
  per-query-position kernel would therefore put 20 % recompute at ~0.6 s TTFT, 2.9× faster than full prefill at 2K.
- **Length does not help:** the recompute scales with rows × keys and the full prefill with keys², so at a fixed budget the ratio does not
  improve with L. A gain from reuse has to come from a fast kernel.
- **Quality is the second hurdle** (next sections):
  - Even at 20 %, chunk_starts gets 24 of 28 masked-call exact matches (full prefill: 28), and random selection 11 of 28.
  - E4's better selectors (query relevance, hybrid) need the Vulkan probe (Task 5).

## Speed (timing groups; medians over contexts of the per-context median over 3 repeats)

Full tables: `summary.md`. The worst max/min over a context's 3 repeats is ≤ 7 % on every recompute arm. Contexts differ by ≤ 10 %.

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
- **Per-run:** pays ~5 ms per extra forward. It wins slightly when there are few runs (chunk_starts), and loses badly with scattered rows.
- **ATTN_QPOS cost follows position:** it scales with each row's visible keys (its position), not with L. The 2K single-pass and control
  arms and the 8K arms all fit ~15 µs per (row × visible key) to within ~20 %.
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
  ≈ 1). With few runs, per-run is 10–25 % faster than the capped single pass: its forwards are small and are not batched at 128 rows.
- **Per-context spread:** the single pass on chunk_starts differs by ~20 % between the two contexts (afclaude 23.9 s, docagent 28.1 s at
  5 %). Random selections cost 10–17 % more than chunk_starts. Not instrumented.
- **The ideal column** in the verdict table uses the control arm's ordinary-kernel cost per row at 8K (5.3 ms) for 1,638 rows:
  ~8.7 s + 0.31 s assembly ≈ 9 s, against 19.1 s for full prefill. It is an upper bound: the control rows sit at the end of the context,
  where each row sees the most keys.

## Numerics: is the single pass right? (eval group, 2K, 20 contexts, 28 tasks)

- Tolerances are from `../G0-floor/README.md` (as of `1c0d418`).
- K/V: per-layer relative L2, pooled over contexts.
- Logits: on the E4 evaluation blocks (32 continuation rows per task).

| pair | what it isolates | K / V all-layer mean | worst layer vs floor (mean; p99) | logits | verdict |
|---|---|---|---|---|---|
| **(d)** Vulkan full prefill in 512-row blocks vs the same rows recomputed single-pass in 512-row batches over a cache one row longer | the ATTN_QPOS kernel vs the ordinary kernel, same tokens and forward shapes | **5.0e-4 / 9.5e-4** | vs (b, 2048): 1.66× / 1.61×; p99 1.50× / 1.50× | KL 2.6e-4 (max task 7.2e-4); top-1 differs on 1 row of 896; \|Δ masked NLL\| ≤ 0.031; EM 28 / 28 | **pass** (pooled bound 2×; p99 at the 1.5× edge). **New floor (d) = 5.0e-4 / 9.5e-4**, about (b, 2048) |
| per-run vs single pass, same selection (chunk_starts, random; 5/10/20 %) | one forward vs one per run | 2.9e-5 – 1.7e-3 / 5.5e-5 – 3.5e-3 | vs (b, 64): ≤ 0.20×; p99 ≤ 0.90× | median per-task KL 3e-4; 2 of 168 task cells exceed the (b) per-task bound 1.4e-3 | **pass** on K/V; logits: note 2 |
| **(a)** CPU per-run recompute vs Vulkan single pass, random 10 %, 6 contexts / 10 tasks | backend, on the recomputed (mostly stale) state | 0.023 / 0.047 | vs (a): mean 1.12× / 1.09×; p99 **2.67× (V, layer 2)** | KL 4.1e-3 (max task 7.5e-3; bound 8.1e-3); top-1 differs on 4 rows of 320 | K/V means **pass**; p99 fails in 5 of 72 layer-kinds (layers 2–5); masked NLL: note 3 |

1. **The attention-kernel floor (d) is now measured.** G0 had no pair that runs ATTN_QPOS.
   - Swapping the attention kernel alone moves K/V by about as much as G0's 512-vs-2048-row batching (b, 2048), and the logits by 2.6e-4 KL.
   - So Task 4's single-pass recompute carries (b, 2048) + (d) ≈ 2× (b, 2048) at ≥ 128 rows.
   - On the synthetic F32 model, ATTN_QPOS reproduces the CPU to ~5e-6, and the ordinary Vulkan kernel is the one that differs (tests).
     Whether ATTN_QPOS also moves the real model's Vulkan path *towards* the CPU was not measured here.
2. **Single pass vs per-run.**
   - K/V are within the (b, 64) floor by a factor of 5 or more. The per-run arm's runs are 1–40-row forwards, in the GEMV and MMQ regimes.
   - **Logits outliers:** the 2 cells over the KL bound each come from one confident row that flips. The extreme one has KL 28.7 on 1 of
     32 rows, with masked NLL 0.086 vs 0.089. Against the full prefill it is the per-run arm that flipped (max row KL 9.3, single 0.40).
   - **Masked-call NLL:** the differences exceed G0's full-prefill (b) bound (0.15 nats) on 5, 2 and 4 of 28 random-selection tasks at
     5 / 10 / 20 %, max 0.35. G0 noted that this absolute Δ scales with the NLL itself. These states are mostly stale (masked NLL 3.4–4.3,
     vs 0.43 for full prefill), and G0's NLL bounds, measured on full prefills, are too tight for them.
3. **CPU vs Vulkan on the recomputed state.**
   - K/V means sit at the (a) floor (1.09–1.12×), as for G1's naive caches. The p99 overshoot is in shallow layers 2–5 only.
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

8K_QUALITY

## Caveats

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
  - 8K_SUSPEND
- **TDR (`TdrDelay` 10 s):**
  - Submits were capped: 512 rows (~8 s) at 2K eval, 128 rows (≤ ~15 s) at 8K, 64 rows at 16K.
  - Before the caps, single submits of 30 s (2K smoke) and ~38–60 s (8K probe) ran without a device reset. That is not a licence to rely on
    it.
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
- **Repeats:** 3 per arm in the timing groups (repeat spread ≤ 3 %, see tables). Each timing group is its own process and never requests
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
  - Mutants: 16 / 16 killed in `git archive` copies (`logs/mutants-t4.log`, `logs/mutants-t4-round2.log`, driver `logs/mutate4.py`). Round 1
    killed 14; M9 (CPU backend accepts a Vulkan model) and M16 (no cache-length guard) survived and were killed after two new tests.
- **Measured on the synthetic model (tests):** ATTN_QPOS (plain F32) reproduces the **CPU** full prefill to ~5e-6, while the ordinary Vulkan
  prefill attention differs from both by ~3e-3 past layer 0. So on that model the Vulkan-vs-CPU gap past layer 0 (G0 Scope note) is the
  ordinary attention kernel, and an all-positions recompute through ATTN_QPOS is closer to the CPU than to the Vulkan full prefill.
