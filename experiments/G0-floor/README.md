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
2. **Vulkan's row-count dependence has two levels, not a smooth trend.** Blocks of 64 and 96 rows deviate from 512-row blocks
   by about 20× more than 2048-, 8- or 1-row blocks: K 0.011 against about 5e-4 all-layer mean.
   - 64 and 96 agree with each other to every printed digit, in all 1,440 per-context cells and all 28 tasks.
   - The Q4_K dispatch in `VulkanTransformerModel` explains this. We read this from the code; the kernels were not
     instrumented:
     - 1 row: the decode GEMV.
     - 2–16 rows: the small-row multi GEMV (`SmallRowKMaxRows` = 16).
     - 17–127 rows: dp4a MMQ with Q8_1-quantised activations.
     - ≥ 128 rows: the coopmat GEMM (`Q4KCoopmatPreferSeqLen` = 128).
   - Only the MMQ regime quantises activations to int8, so the effect dotLLM reported ("8 rows vs 96 rows, about 2e-2
     relative L2 on K") is the MMQ regime against the GEMV/coopmat regimes. We measure 0.011 all-layer mean and
     0.016–0.017 at the worst layer.
   - Within the MMQ regime, the result does not depend on the batch size (64 = 96 exactly). Every other block pairing
     differs by about 5e-4, including 512 vs 2048, which are both coopmat. That ~5e-4 is the non-MMQ baseline, so (b, 2048)
     is a non-zero floor.
3. **CPU vs Vulkan is about 2× the worst Vulkan batching effect:** K 0.023, V 0.045 all-layer mean.
   - It grows with depth: K 1.7e-3 at layer 0, 5.6e-3 at layer 1, 0.027–0.028 in layers 12–35, peaking at layer 33.
   - The CPU path quantises activations to Q8_K for its dot products, so even layer 0 differs.
   - Logits KL is 2.3e-3 (2K) and 2.9e-3 (8K) nats per continuation row; top-1 agreement is 0.984–0.986.
   - The masked-call greedy result is the same on all 42 tasks.
4. **8K looks like 2K** in the means (all-layer means within 0.001 absolute, 1.0–1.14×). Deep-layer p99s are higher: up
   to 1.25× for (a) and (b, 64), and up to 1.5× for the small (b, 2048) and (b, 8) floors. The floor does not blow up with
   context length up to 8K. 16K and 32K were not measured.
5. **The largest single rows are outliers and must not be used as a bound.** In pairs (a) and (b, 64), V rows reach a
   relative L2 of 15–30, which comes from rows with a tiny reference norm. Use p99s.

### Tolerance table (rule: pass = at most 1.5× the floor of the matching pair, unless the data say otherwise)

**Choosing the matching pair.**

| what is compared | matching pair |
|---|---|
| Vulkan vs Vulkan, same row counts, same process (rerun, host-write vs device-copy assembly, `ReadRows` round-trip). Also expected (not measured): a chunk at position 0 encoded alone in one forward with the same tokens and row count as the reference's first block | (c) |
| Vulkan result produced by forwards of 1 row | (b, 1) |
| … of 2–16 rows | (b, 8) |
| … of 17–127 rows | (b, 64) |
| … of ≥ 128 rows | (b, 2048) |
| mixed or unknown row counts (selective recompute with variable run lengths; chunk encodes whose lengths straddle 17–127, e.g. symbol chunks, median 107 tokens) | (b, 64), the worst Vulkan regime |
| Vulkan vs CPU (cross-checks, G1/G3 against the CPU E1/E4 tables) | (a) |

**Scope:** these floors are for lab runs on the real Qwen3-4B Q4_K_M. GPU-gated unit tests on the synthetic F32 model
(`SyntheticDenseGguf`) are **not** covered: no Q4_K dispatch regimes exist there, and CPU vs Vulkan agrees to about 1e-6
(Task 1: shift 5.96e-7, round-trips bit-exact). Expect ≤ 1e-5 there and use Task 1's numbers.

The size is the context size of the test (2K or 8K table). For 16K and 32K, use the 8K floor, with p99s × 1.5, until it is
measured. RoPE shifts on top of rows add at most the Task 1 shift error (max |Δ| 2.4e-7 at small deltas, 2.4e-4 at a
3e4 delta), which is negligible next to every non-zero floor here.

**Rules.**

| metric | applies to | tolerance | why |
|---|---|---|---|
| bit-exact | pair (c) | **0**: K, V and logits identical | The measured floor is 0. A 1.5× rule cannot be applied to 0, and any non-zero result there is a bug, not noise |
| per-layer K and V mean of row relative L2, pooled over ≥ 5 contexts | (a), (b) | ≤ **1.5×** the per-layer mean in `floor-<size>.csv` | The CI half-width of the all-layer mean is ≤ 0.12× the point at 2K (20 contexts) and ≤ 0.09× at 8K (5 contexts) |
| the same, on a single context | (a), (b, 64) | ≤ **2×** the per-layer floor mean | The worst context's all-layer mean is 1.11× (a) and 1.16 / 1.22× (b, 64, K / V) the pooled value at 2K. 1.5× leaves too little headroom |
| the same, on a single context | (b, 2048), (b, 8), (b, 1) | ≤ **3×** the per-layer floor mean | These small floors vary more between contexts: worst context 1.75× (b, 2048), 1.49× (b, 8), 1.31× (b, 1) at 2K. **1.5× would fail correct code** |
| per-layer p99 of row relative L2 | (a), (b) | ≤ **1.5×** the per-layer p99 in `floor-<size>.csv` | Only for ≥ 2K rows. Never bound the max row (finding 5) |
| logits KL mean, pooled over ≥ 20 tasks | (a), (b) | ≤ **1.5×** floor: 2K (a) 3.5e-3, (b, 64) 5.4e-4, (b, other) 4.2e-4; 8K (a) 4.4e-3, (b, 64) 6.6e-4 | KL CI half-width is about 0.2× the point at 2K and 0.4× at 8K. The 1.5× rule holds with ≥ 20 tasks |
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
  - Every arm runs on the same backend, so the floor that governs orderings is (b), not (a). Most selector-recompute
    forwards are runs of 1–127 rows: the MMQ and GEMV regimes. The full-prefill reference uses 512-row (coopmat) blocks.
  - Hence a recompute arm carries the (b, 64) floor, about 0.011 / 0.021 K / V and 3.6e-4 KL, **on top of** its reuse
    error, even at 100 % recompute. Task 4's "all positions = full prefill" check must use (b, 64) when its runs fall in
    17–127 rows, not (c).
- **Against E3's stale-chunk deviation (CPU):**
  - E3 combined relative deviation: 0.07 at layer 1, 0.17 in layers 2–11, peaking at 0.48 at layer 20.
  - The CPU-vs-Vulkan floor (K about 0.03, V about 0.05 in layers 12–35) is about 10–15 % of that in the middle and deep
    layers, but about 25 % at layer 1 (V 0.019 against 0.073).
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
- **Evaluation-block scope.** The logits metrics use the E4 evaluation blocks only: a 255-row prefix, then 32 all-row
  logits, with the same shapes on both sides of each pair. In pair (a) those blocks also run on different backends, so
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
