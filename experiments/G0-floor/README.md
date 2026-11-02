# G0: numerical floor of the dotLLM Vulkan path (Phase G Task 2, Step 0)

**What this is for.** Every later Vulkan parity result (encode, assemble, shift, recompute, probe, E1/E4 on Vulkan) is
reported as a ratio to a measured floor, not as bit equality. This experiment measures that floor on full prefills of
real contexts. There is no chunk reuse anywhere in it: it only measures how far two correct prefills of the same tokens
drift apart because of backend, batching, or rerun.

**Setup.** Qwen3-4B-Instruct-2507 Q4_K_M, F32 KV, dotLLM CPU and Vulkan (Radeon 8060S iGPU).
- 2K: 20 contexts (symbol chunker, seed 0, kept tasks), 28 tasks, 40,915 context rows. 18 contexts are E4's own (6 per
  corpus); their 23 tasks are every E4 symbol/seed-0 kept instance. The other 2 are extra kept-mode contexts.
- 8K: 5 contexts, unfiltered generator plans, 14 tasks, 40,886 context rows.

Comparison pairs (reference first):

| pair | reference | compared | what it isolates |
|---|---|---|---|
| (a) `a_cpu_vs_vk512` | CPU full prefill, 512-row blocks | Vulkan full prefill, 512-row blocks | backend (CPU kernels are batch-invariant, so the CPU block size does not matter: E2, and `FloorMetricsTests`) |
| (b) `b_vk512_vs_vk{n}` | Vulkan, 512-row blocks | Vulkan, n-row blocks; n = 2048 (whole 2K context), 96, 64, 8, 1 (2K only) | Vulkan row-count dependence (the "8-row vs 96-row" effect) |
| (c) `c_vk512_rerun` | Vulkan, 512-row blocks | the same prefill again in a fresh cache | determinism |

## Results

The full tables are in `summary.md`, per layer in `floor-{2k,8k}.csv`, and per context in `contexts-*.csv`. Per-row
relative L2 is ‖ΔX_row‖ / ‖X_ref,row‖ over the whole KV row (8 heads × 128). Per-layer values are pooled over all rows of
all contexts. "All-layer" is the mean of the 36 per-layer means. Intervals are 95 % bootstrap over contexts.

| pair | K all-layer mean | V all-layer mean | worst layer mean K / V | worst layer p99 K / V | KL mean (nats) [95 % CI] | top-1 | mask EM agreement |
|---|---|---|---|---|---|---|---|
| **2K** (a) CPU vs Vulkan | **0.023** [0.022, 0.023] | **0.045** [0.044, 0.046] | 0.034 (L33) / 0.059 (L22) | 0.17 / 0.29 (L33) | **2.3e-3** [1.8e-3, 2.8e-3] | 0.986 | 28/28 |
| 2K (b) 512 vs 2048 | 4.7e-4 | 8.9e-4 | 7.8e-4 / 1.4e-3 | 3.7e-3 / 5.7e-3 | 2.5e-4 | 1.000 | 28/28 |
| 2K (b) 512 vs **96 = 64** | **0.011** [0.011, 0.011] | **0.021** [0.020, 0.022] | 0.016 / 0.029 | 0.084 / 0.13 | **3.6e-4** [2.8e-4, 4.4e-4] | 1.000 | 28/28 |
| 2K (b) 512 vs 8 | 5.4e-4 | 1.0e-3 | 8.7e-4 / 1.6e-3 | 4.4e-3 / 6.6e-3 | 2.7e-4 | 0.997 | 28/28 |
| 2K (b) 512 vs 1 | 5.3e-4 | 1.0e-3 | 8.4e-4 / 1.5e-3 | 4.5e-3 / 7.0e-3 | 2.8e-4 | 0.997 | 28/28 |
| 2K (c) rerun | **0 (bit-exact)** | 0 | 0 | 0 | 0 | 1.000 | 28/28 |
| **8K** (a) CPU vs Vulkan | **0.023** [0.022, 0.023] | **0.046** [0.045, 0.046] | 0.035 / 0.061 | 0.21 / 0.34 | **2.9e-3** [2.1e-3, 4.0e-3] | 0.984 | 14/14 |
| 8K (b) 512 vs 2048 | 4.9e-4 | 9.4e-4 | 8.6e-4 / 1.5e-3 | 5.4e-3 / 8.0e-3 | 3.2e-4 | 0.993 | 14/14 |
| 8K (b) 512 vs 96 = 64 | 0.011 | 0.021 | 0.017 / 0.029 | 0.11 / 0.16 | 4.4e-4 | 0.993 | 14/14 |
| 8K (b) 512 vs 8 | 6.1e-4 | 1.2e-3 | 1.1e-3 / 1.8e-3 | 6.7e-3 / 0.010 | 2.9e-4 | 0.995 | 14/14 |
| 8K (c) rerun | **0 (bit-exact)** | 0 | 0 | 0 | 0 | 1.000 | 14/14 |

1. **Vulkan is deterministic.** Re-running the same prefill into a fresh cache gives bit-identical K/V and logits on every
   row, layer and context at 2K and 8K.
2. **Vulkan's row-count dependence is dominated by one regime, not a smooth trend.** Blocks of 64 and 96 rows deviate from
   512-row blocks by about 20× more than 2048-, 8- or 1-row blocks: K 0.011 against about 5e-4 all-layer mean.
   - At depth that looks like two levels. Layer 0 K actually shows three: 1.3e-6 (2048 rows; coopmat on both sides),
     6.3e-5 (8 or 1 rows; GEMV) and 9.5e-4 (64 or 96 rows; MMQ). The ~5e-4 all-layer figure for the non-MMQ blocks is
     tiny matmul and attention differences amplified with depth, not a property of one kernel.
   - The 64- and 96-row arms give identical summaries against the 512-row reference, to every printed digit: 1,440 of
     1,440 per-context cells and 28 of 28 tasks at 2K; 360 of 360 cells and 14 of 14 tasks at 8K. They were not compared
     with each other directly, and only these two MMQ sizes were run.
   - The Q4_K dispatch in `VulkanTransformerModel` explains this. We read this from the code; the kernels were not
     instrumented:
     - 1 row: the decode GEMV.
     - 2–16 rows: the small-row multi GEMV (`SmallRowKMaxRows` = 16).
     - 17–127 rows: dp4a MMQ with Q8_1-quantised activations.
     - ≥ 128 rows: the coopmat GEMM (`Q4KCoopmatPreferSeqLen` = 128).
   - Only the MMQ regime quantises activations to int8, so the effect dotLLM reported ("8 rows vs 96 rows, about 2e-2
     relative L2 on K") is the MMQ regime against the GEMV/coopmat regimes. We measure 0.011 all-layer mean and
     0.016–0.017 at the worst layer.
   - So, within the MMQ regime, the result appears not to depend on the batch size. That is inferred from 64 and 96 only,
     and extrapolated to the whole 17–127 range. Every non-MMQ block size measured differs from the 512-row reference by
     about 5e-4, including 2048 rows, which is coopmat like the reference. Only pairings against 512 rows were measured.
     (b, 2048) is therefore a non-zero floor.
3. **CPU vs Vulkan is about 2× the worst Vulkan batching effect:** K 0.023, V 0.045 all-layer mean.
   - It grows with depth: K 1.7e-3 at layer 0, 5.6e-3 at layer 1, 0.027–0.028 in layers 12–35, peaking at layer 33.
   - The CPU path quantises activations to Q8_K for its dot products, so even layer 0 differs.
   - Logits KL is 2.3e-3 (2K) and 2.9e-3 (8K) nats per continuation row; top-1 agreement is 0.984–0.986.
   - The masked-call greedy result is the same on all 42 tasks.
4. **8K looks like 2K** in the means (all-layer means within 0.001 absolute, 1.0–1.14×). Deep-layer p99s are higher: up
   to 1.25× for (a) and (b, 64), and up to 1.58× for the small (b, 2048) and (b, 8) floors (worst: (b, 8) V). The floor does not blow up with
   context length up to 8K. 16K and 32K were not measured.
5. **The largest single rows are outliers and must not be used as a bound.** In pairs (a) and (b, 64), V rows reach a
   relative L2 of 15–30 at 2K (14.6 at most at 8K), which comes from rows with a tiny reference norm. Use p99s.

### Tolerance table (rule: pass = at most 1.5× the floor of the matching pair, unless the data say otherwise)

**Choosing the matching pair.**

| what is compared | matching pair |
|---|---|
| Vulkan vs Vulkan, the same forwards on the same tokens in the same process (rerun; host-write vs device-copy assembly of the same entries; `ReadRows` round-trip) | (c) |
| Vulkan result whose compared rows come from forwards of 1 row | (b, 1) |
| … of 2–16 rows | (b, 8) |
| … of 17–127 rows | (b, 64) |
| … of ≥ 128 rows | (b, 2048) |
| a chunk at position 0 encoded alone vs the full prefill (Task 3). Bit-exactness is **unmeasured**: cache capacity, buffer sizing or attention tiling may differ between an encode-sized cache and the full cache | by the encode's row count: (b, 2048) if ≥ 128 rows, (b, 64) if 17–127, (b, 8) if 2–16; tighten to (c) only after a bit-exact measurement |
| **Task 4 single-pass selective recompute**: one `Forward(subsetIds, subsetPositions, cache)` whose row count is the total selected count (205–410 rows at 10–20 % of 2K, 2,048 at 100 %) | by that total: (b, 2048) for ≥ 128 rows, which covers every Task 4 budget ≥ 7 % at 2K. Not (b, 64): that would be about 20× too permissive (K 0.011 vs about 5e-4) and would let a real recompute bug pass. See the ATTN_QPOS note below |
| row counts mixed across forwards (the CPU per-run `SelectiveRecomputer` path; chunk encodes whose lengths straddle 17–127, e.g. symbol chunks, median 107 tokens) | (b, 64), the worst Vulkan regime |
| Vulkan vs CPU (cross-checks, G1/G3 against the CPU E1/E4 tables) | (a) |

**ATTN_QPOS is not covered.** Task 4's single-pass recompute routes attention through the non-flash per-query-position kernel
(`ATTN_QPOS`; non-contiguous positions, or a run inside a filled cache). No G0 pair runs that kernel: all prefills here use the
ordinary path. So the attention-kernel difference in "all positions = full prefill" has **no measured floor**. Task 4 must
measure it, for example as a pair (d): full prefill vs a single-pass forward of all positions over the same cache layout. Until
then, (b, 2048) is a lower bound, not a tolerance.

**Scope:** these floors are for lab runs on the real Qwen3-4B Q4_K_M. GPU-gated unit tests on the synthetic F32 model
(`SyntheticDenseGguf`) are **not** covered: no Q4_K dispatch regimes exist there. On that model the Vulkan shift and row IO
agree with the CPU to about 1e-6 (Task 1: shift 5.96e-7, round-trips bit-exact), and so do layer-0 K/V (Task 3: 7e-7 / 1.4e-6).
**Past layer 0, CPU vs Vulkan K/V differ by about 1e-3 to 2e-3 absolute** on values of magnitude ~5 (Task 3 spike: 1.1e-3 / 1.3e-3
at layer 1, 1.6e-3 / 2.1e-3 at layer 2), so ≤ 1e-5 holds only for the shift, row IO and layer 0. Task 3's GPU tests use 1e-2 for
deeper cross-backend layers (their own choice, about 5× headroom). *(Corrected in Phase G Task 3's fix round, with the Task 2
owner's approval.)*

The size is the context size of the test (2K or 8K table). For 16K and 32K, use the 8K floor, with p99s × 1.6, until it is
measured. That may be tight for the small floors. RoPE shifts on top of rows add at most the Task 1 shift error (max |Δ| 2.4e-7 at small deltas, 2.4e-4 at a
3e4 delta), which is negligible next to every non-zero floor here.

**Rules.**

| metric | applies to | tolerance | why |
|---|---|---|---|
| bit-exact | pair (c) | **0**: K, V and logits identical | The measured floor is 0. A 1.5× rule cannot be applied to 0, and any non-zero result there is a bug, not noise |
| per-layer K and V mean of row relative L2, pooled over ≥ 5 contexts | (a), (b, 64), (b, 8), (b, 1) | ≤ **1.5×** the per-layer mean in `floor-<size>.csv` | Over 2,000 random 5-of-20 context subsets (2K), the worst per-layer ratio to the full pool is 1.13 (a), 1.34 (b, 64), 1.32 (b, 8), 1.30 (b, 1) |
| the same, pooled over ≥ 5 contexts | (b, 2048) | ≤ **2×** | The worst 5-of-20 subset reaches 1.55× at one layer (V; 0.15 % of subsets), so 1.5× would occasionally fail correct code |
| the same, on a single context | (a), (b, 64) | ≤ **2×** the per-layer floor mean | Worst single context, per layer, against the pooled value: (a) 1.20 K / 1.26 V; (b, 64) 1.26 / **1.60** at 2K; ≤ 1.16 at 8K |
| the same, on a single context | (b, 8), (b, 1) | ≤ **3×** | Per layer, worst context: (b, 8) 1.80 / 1.85, (b, 1) 1.54 / 1.56 at 2K; ≤ 1.42 at 8K. **1.5× would fail correct code** |
| the same, on a single context | (b, 2048) | ≤ **4×** | Per layer, worst context: **2.26 / 2.45** (L34) at 2K, so 3× leaves only 1.2× headroom with 20 samples; ≤ 1.20 at 8K |
| per-layer p99 of row relative L2, pooled over ≥ 5 contexts | (a), (b) | ≤ **1.5×** the per-layer p99 in `floor-<size>.csv` | Valid only for pooled comparisons; never bound the max row (finding 5) |
| per-layer p99, on a single context | (a), (b) | ≤ **3×** the per-layer floor p99 | One context's per-layer p99 reaches 2.41× the pooled p99 at 2K ((a) K, L28). Across pairs the worst is 1.96–2.41×, and 5–7 of 20 contexts fail 1.5× in some layer. At 8K it is ≤ 1.42×. Prefer band or all-layer means on single contexts; p99 is the noisiest statistic |
| logits KL mean, pooled over ≥ 20 tasks | (a), (b) | ≤ **1.5×** floor: 2K (a) 3.5e-3, (b, 64) 5.4e-4, (b, other) 4.2e-4; 8K (provisional) (a) 4.4e-3, (b, 64) 6.6e-4 | KL CI half-width is about 0.2× the point at 2K (28 tasks). The 8K floor rests on only 14 tasks (half-width about 0.33×), so treat the 8K values as provisional until measured on ≥ 20 tasks |
| logits KL mean, single task | (a), (b) | ≤ **1.5×** the largest per-task floor: 2K (a) 8.1e-3, (b) 1.4e-3; 8K (a) 7.4e-3, (b) 1.3e-3 | Per-task KL varies 1.5–3.3× around the pooled mean. A per-task 1.5× pooled bound would fail correct code |
| top-1 agreement | (a), (b) | disagreement ≤ 1.5× floor + 1 row: (a) ≤ 2.1 % (2K) / 2.4 % (8K) + 1 row, (b) ≤ 0.5 % (2K) / 1.0 % (8K) + 1 row | Disagreements are rare events (1–3 per 1,000 rows on (b)). The +1 row absorbs the granularity |
| masked-call NLL, abs Δ per task | (a), (b) | 2K: ≤ 1.5× the largest per-task floor: (a) 0.23, (b) 0.15 nats. 8K: (a) 1.1, (b) 0.69 nats | The masked NLL is a sum over the masked tokens. Its abs Δ scales with the NLL itself: 8K tasks are unvalidated, and several have NLL 9–44 nats |
| masked-call greedy EM | (a), (b) | must agree on every task in the matching set | It agreed on 42 / 42 tasks for every pair |

## What the floor means for the E4 conclusions (E4 ran on the CPU)

Scales below are on the 23 E4 instances that are shared with this run. Reproduction check: on those instances, this run's
CPU full-prefill masked NLL equals E4's `full` row within 4.2e-6, which is E4's printed precision.

- **Against the naive→full gap: small.**
  - CPU vs Vulkan changes the masked-call NLL by 0.033 nats on average. That is **0.7 % of the mean naive→full gap**
    (4.52 nats), and at most 4.6 % of any one instance's own gap.
  - KL(CPU ‖ Vulkan) per row is 2.3e-3, against 0.38 nats for naive concatenation on the same tasks (1/160).
  - The Vulkan batching floor (b) is 0.2–0.3 % of the gap.
  - So naive-vs-full and the gap-recovered shares carry over to Vulkan essentially unchanged.
- **Against selector differences: small for the headline differences, comparable to the hairline ones.**
  - E4's main contrasts:
    - Hybrid(QR) − QR: +0.04–0.05 of the gap at 10–20 %.
    - The 5 % losses: −0.10 to −0.15.
    - The ORACLE window: +0.15 at 5 %.
    - Graph worse than QR with fixed chunks: −0.13 to −0.23.
  - These are 6–30× the CPU-vs-Vulkan mean NLL shift expressed as a gap share (0.007), and 13–100× the Vulkan-internal
    floor (0.002–0.003).
  - In KL, E4's post-query differences at 20 % on these tasks are about 0.008–0.04 nats:
    - ChunkStarts 0.079, QR 0.058, Graph 0.066, Hybrid 0.040.
    - That is 3–17× the CPU-vs-Vulkan KL floor and 18–150× the Vulkan-internal one.
  - Some E4 differences sit **within the floor**, and a backend change could flip them:
    - Fixed-512 Hybrid(QR) − QR at 20 %: −0.008 [−0.011, −0.000].
    - ChunkStarts vs QR KL at 15 %: 0.0735 vs 0.0722.
    - Several "±0.01 of QR" statements.
  - Treat these as ties, as E4 already does in words.
- **For G3 (E4 on Vulkan).**
  - Every arm runs on the same backend, so the floor that governs orderings is (b), not (a). It is keyed on the actual
    forward row count.
  - With Task 4's single-pass recompute, one forward of the whole selection (≥ 128 rows at the 10–20 % budgets), a
    recompute arm carries about the (b, 2048) floor, about 5e-4 / 9e-4 K / V and 2.5e-4 KL. On top of that comes the
    unmeasured ATTN_QPOS attention difference.
  - Only forwards that really are 17–127 rows (the CPU per-run path, or short chunk encodes) carry the (b, 64) floor, about
    0.011 / 0.021 and 3.6e-4 KL.
- **Against E3's stale-chunk deviation (CPU):**
  - E3 combined relative deviation: 0.07 at layer 1, 0.17 in layers 2–11, peaking at 0.48 at layer 20.
  - The CPU-vs-Vulkan floor (K about 0.03, V about 0.05 in layers 12–35) is about 10–15 % of that in the middle and deep
    layers.
  - At layer 1 it is between 8 % and 26 %. The combined ‖(ΔK, ΔV)‖ / ‖(K, V)‖ floor lies between K 0.0056 and V 0.019; only
    K and V were stored separately, so the exact combined value is not available. E3's figure is 0.073.
  - Vulkan deviation profiles therefore need a floor subtraction or ratio at shallow layers before they are compared with
    E3.

## Caveats

- **One model, one GPU, one driver.** Qwen3-4B Q4_K_M only (Q4_K and Q6_K weights). Other quants take other dispatch
  regimes, so re-measure before reusing these thresholds for another model.
- **Contexts.**
  - 2K uses the E4 symbol/seed-0 kept contexts: the first 6 per corpus are E4's own; 2 extra contexts were added (7 / 7 /
    6). The 8K contexts are unfiltered and unvalidated, and only 5 of them (2 / 2 / 1).
  - These are not three generator seeds. The plan's "3 seeds" rule makes less sense for a floor, where the unit is the
    context and the CPU and Vulkan paths are deterministic. Intervals are over contexts instead.
  - Contexts are not independent of corpus: every 2K context of a corpus shares its source repository.
- **No whole-context forward at 8K.** The largest Vulkan block there is 2048 rows. An 8192-row single submit risks the
  Windows TDR, which resets the GPU for every process on the box, so it was not attempted. The 1-row arm ran at 2K only
  (75 s per context).
- **Same-process determinism only.** Pair (c) reruns inside one process, which shares pipelines and buffers. A
  cross-process rerun was not measured. Task 1's backend-check reruns and the bit-exact `ReadRows` round-trip suggest no
  difference.
- **Timings are contaminated.** Another agent's E4b CPU jobs ran during the 2K run, and the GPU lock was held by another
  agent between the two sizes. CPU prefill measured 29 s (2K) and 248 s (8K), against 20 s and 196 s uncontended
  (`LLMs.md`). Vulkan prefill measured about 1,100 tok/s at 2K and 390 tok/s at 8K in 512-row blocks; the 8K figure is
  attention-dominated. Values are unaffected: the CPU masked NLL reproduces E4.
- **Evaluation-block scope.** The logits metrics use the E4 evaluation blocks only: the task's query prefix (up to 256
  tokens, minus its last), then one all-row logits forward over the continuation. That gives 875 rows for 28 tasks at 2K,
  at least 11 per task. Shapes are the same on both sides of each pair, so values are comparable; continuations of ≤ 16 rows
  run in the small-row GEMV regime, longer ones in MMQ. In pair (a) those blocks also run on different backends, so
  (a) KL includes the evaluation forward's own CPU/Vulkan difference, as a CPU-vs-Vulkan E4 rerun would.
- **Pooling is by row.** Contexts are weighted by their row count. All 2K contexts are 2,041–2,048 tokens and all 8K
  contexts 8,128–8,192, so this makes no difference.

## Method and reproduction

- Command: `ChunkKvLab floor` (dotLLM `feature/chunk-reuse-vulkan` @ `2feffbaf`, `benchmarks/ChunkKvLab/FloorCommand.cs`).
  - It loads the model on the CPU and on Vulkan in one process.
  - Per context:
    - Vulkan 512-block reference.
    - Rerun.
    - Each `--blocks` size.
    - CPU 512 blocks.
  - Each arm is read back through `IChunkBackend.ReadRows` into `KvDeviation` (new reader overload), and its logits
    blocks are compared with `FloorMetrics.CompareLogits`.
  - Outputs are written as `*.partial` and renamed only when every context finished.
- Metric helpers were test-driven:
  - `tests/DotLLM.Tests.Unit/ChunkReuse/FloorMetricsTests.cs` has 5 tests: the nearest-rank p99, row pooling, the reader
    overload on planted rows, CPU read-back with a planted delta, and logits KL / top-1 / masked NLL against known answers.
  - Red phase: a compile failure (`logs/red-build.log`).
  - 13 / 13 mutants were killed in a `git archive 2feffbaf` copy (`logs/mutants-t2.log`): percentile off-by-one / max /
    interpolating, mean n−1, replacing pool, V reads K, reading the reference twice, swapped KL direction, masked NLL over
    all rows, top-1 against the target, the reader writing into the reference buffers, the reused-row norm, and
    stride − 1.
- Provenance is at the top of `logs/floor-{2k,8k}.log`:
  - dotLLM `2feffbaf`, dirty files 0.
  - GPU lock holder `chunk-vulkan-t2`, one hold per size, refreshed every 10 min.
  - AMD Radeon 8060S, AMD proprietary driver 26.10.1 (LLPC), Vulkan 1.4.359, Windows driver 32.0.32015.7029.
  - `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` @ `ae44f08e1392f39c0e474af10c3ff8355c8b6688` (2,497,280,736 bytes).
  - Corpus snapshots with enforced chunk-id SHA-256 (`../corpus.md`).
  - Run times: 64.1 min (2K) and 63.5 min (8K).
- Reproduce: `./run.ps1 -Snapshots <dir holding the t8-corpus-* snapshots>`, then `uv run summarize.py`.

| file | content |
|---|---|
| `run.ps1` | Runs both sizes under the GPU lock and writes the provenance block to each log |
| `floor-{2k,8k}.csv` | Pooled floor: per pair × layer × K/V the n, mean, p99 and max; a `logits` row per pair with KL mean / p99 / max, top-1, abs Δ masked NLL and EM agreement |
| `contexts-*.csv` | Per context × pair × layer × K/V: n, mean, p99, max |
| `tasks-*.csv` | Per task × pair: KL mean / max, top-1, masked NLL on each side, EM on each side (task ids join to E4 `results.csv.gz`) |
| `timing-*.csv` | Prefill ms per arm and context |
| `summarize.py` → `summary.md`, `tolerance.csv` | Band tables, context bootstrap CIs, per-context spread, E4 comparison |
| `logs/` | Run logs, red build, mutant log (force-added) |
