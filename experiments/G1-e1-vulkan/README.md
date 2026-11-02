# G1: E1 on the dotLLM Vulkan backend (Phase G Task 3)

**Result in one line:** chunk encode, RoPE shift and assembly run on the Vulkan iGPU and reproduce the CPU E1 picture. Naive
concatenation's loss against full prefill is the same within a few percent of the gap. Inside Vulkan, every check that should be
bit-exact is bit-exact. Full prefill is about 10× faster than on the CPU. Device-copy assembly runs at about 70,000 tok/s. Host-write
assembly runs at about 9,000 tok/s, no faster than the CPU, because each `WriteRows` call costs about 1.5 ms. Chunk readback is
slow (about 145 MB/s). CPU vs Vulkan on the same naive cache: KV is within 1.3× of the (a) floor everywhere. Top-1 exceeds the (a)
bound from 8K up, but a control shows the full prefill of the same 8K tasks does too (6 vs 7 of 192 rows), so that is task
variance. KL is somewhat higher on the stale state (1.56× at 8K), which is a hypothesis with 3 tasks per size.

## Setup

- **Engine:** dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-vulkan`, branch `feature/chunk-reuse-vulkan`, commit
  `c93fd1bf` (dirty 0). `ChunkKvLab e1 --backend vulkan --cross-check cpu`, Release build.
- **Hardware:** AMD Radeon 8060S (gfx1151), AMD proprietary driver 26.10.1 (LLPC), Vulkan 1.4.359. Ryzen AI MAX+ 395, Windows 11.
  The provenance block is at the top of each `logs/results-*.log`. GPU lock holder: `chunk-vulkan-t3`.
- **Model:** `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` Q4_K_M @ `ae44f08e1392f39c0e474af10c3ff8355c8b6688`, read in place
  from the HF hub cache. F32 KV on both backends.
- **Corpus:** pinned. `git archive 4a781829 src` of dotLLM, with chunk-id SHA-256 `b02b1e6e…c90dc800` enforced by
  `--expect-hash`: 1086 documents, 7257 chunks of 512 tokens. This is the snapshot E1's main run and E2 used (E2 reproduced E1's
  naive rows to every digit), so the 2K/4K/8K seeds 0–2 here are the **same contexts** as the CPU E1 table and pair by seed.
  CPU E1 16K ran on the live tree (7259 chunks), so it does not pair; it is shown for trend only.
- **Protocol:** identical to E1: 512-token chunks; full prefill in 512-row blocks; the request reorders the second half of the base
  order; 64-token held-out continuation (teacher-forced all-row logits) and 16 greedy tokens.
  - Every method runs on Vulkan, and the reference is **Vulkan full prefill**.
  - `naive_concat` = Vulkan-encoded chunks (`ChunkEncoder.Encode(model, VulkanChunkBackend, …)`, one 512-row forward per chunk),
    assembled with `WriteRows`, then a device shift.
  - `prefix_reuse` = the full cache rolled back to the matched prefix, then the suffix prefilled.
- **Extra arms in the same process:**
  - **Device-copy assembly:** the same entries, made resident (one upload), assembled with `CopyRowsFrom`.
  - **Chunk 0 vs the full prefill's first block:** both are 512-row forwards of the same tokens at positions 0–511, into caches of
    different capacity.
  - **CPU cross-check:** the CPU model encodes and assembles the same chunks. Its naive cache and logits are compared with the Vulkan
    naive cache. This is G0 pair (a), the CPU reference against Vulkan.
- **Seeds:** 0, 1, 2 at every size (2K, 4K, 8K, 16K, 32K).
- **Tolerances:** G0 README, tolerance table as of ChunkedkvCache `1c0d418`.
  - Within Vulkan, the same forwards → pair (c), bit-exact.
  - CPU vs Vulkan → pair (a). Single context: per-layer mean ≤ 2× and p99 ≤ 3× the floor. KL per task ≤ 8.1e-3 (2K; also used at
    4K) or 7.4e-3 (8K and above). Top-1 disagreement ≤ 2.1 % / 2.4 % of rows + 1 row.
  - 16K and 32K use the 8K floor, with p99 × 1.6.
  - All 512-token chunks are encoded in one ≥ 128-row forward (coopmat regime), so the 17–127-row MMQ regime does not apply here.
    Symbol chunks in G3 will carry (b, 64).

## Results

The generated tables are in `summary.md` (`uv run summarize.py`). Raw data: `results-{small,16k,32k}.csv` (`RunRow`) and their
`-details`, `-timing`, `-kv` (per-layer K/V row relative L2) and `-xcheck` (logits cross-checks) companions.

### E1 on Vulkan next to the CPU E1 table (top-1, KL and EM: mean over 3 seeds; Vulkan TTFT: median over seeds; CPU TTFT: mean, from E1)

| method | ctx | top-1 Vulkan / CPU | mean KL Vulkan / CPU | EM Vulkan / CPU | TTFT Vulkan / CPU (s) |
|---|---:|---|---|---|---|
| full | 2048 | 1 / 1 | 0 / 0 | 1 / 1 | 1.66 / 20.0 |
| prefix_reuse | 2048 | 1 / 1 | 0 / 0 | 1 / 1 | 1.03 / 12.0 |
| naive_concat | 2048 | 0.865 / 0.875 | 0.128 / 0.131 | 0.438 / 0.438 | 0.24 / 0.25 |
| full | 4096 | 1 / 1 | 0 / 0 | 1 / 1 | 5.11 / 49.8 |
| prefix_reuse | 4096 | 1 / 1 | 0 / 0 | 1 / 1 | 3.46 / 25.3 |
| naive_concat | 4096 | 0.901 / 0.906 | 0.187 / 0.174 | 1 / 1 | 0.46 / 0.39 |
| full | 8192 | 1 / 1 | 0 / 0 | 1 / 1 | 19.2 / 196 |
| prefix_reuse | 8192 | 1 / 1 | 0 / 0 | 1 / 1 | 14.0 / 146 |
| naive_concat | 8192 | 0.771 / 0.760 | 0.527 / 0.549 | 0.417 / 0.417 | 0.93 / 0.60 |
| full | 16384 | 1 / *1* | 0 / *0* | 1 / *1* | 72.2 / *946* |
| prefix_reuse | 16384 | 1 / *1* | 0 / *0* | 1 / *1* | 52.9 / *714* |
| naive_concat | 16384 | 0.792 / *0.734* | 0.621 / *0.668* | 0.25 / *0.125* | 1.83 / *1.21* |
| full | 32768 | 1 / not run | 0 / – | 1 / – | 275 (seed 1 stalled, see Speed) / – |
| prefix_reuse | 32768 | 1 / not run | 0 / – | 1 / – | 201 / – |
| naive_concat | 32768 | 0.583 / not run | 1.175 (0.78, 1.23, 1.52) / – | 0.167 / – | 3.5 / – |

Italic CPU values at 16K are E1's single seed-0 run on the live dotLLM tree (7259 chunks): different contexts, trend only.
16K Vulkan per-seed naive KL: 0.83 / 0.96 / 0.07. The seed spread is larger than on the CPU at 4K (0.06–0.25).

**Naive vs full, paired with CPU E1 by seed (2K–8K, 9 cells):**
- The Vulkan naive KL-to-full differs from the CPU one by −0.045 to +0.027 nats. The mean ΔKL is −0.004.
- On average that is 8.5 % of the naive→full gap (mean of per-cell shares; ratio of means 5.7 %, median share 5.0 %): 0.6–7.4 % at
  2K and 8K, and up to 39 % at 4K seed 2, where the gap itself is only 0.06 nats.
- Top-1 differs by at most 2 of 64 rows in every cell. Greedy exact match against each backend's own full prefill is identical in
  all 9 cells.
- **These differences have no matching floor.** The plan asks for "mean KL and top-1 within the floor-derived tolerance" against the
  CPU table, but the (a) floor bounds the difference between the two backends' outputs on the same state, not a difference of two
  methods' scores against two different references (each backend's own full prefill). So the Δ figures above are descriptive. The
  test that (a) does govern is the direct one in "CPU vs Vulkan on the same naive cache" below: it passes at 2K–4K and fails on
  top-1 from 8K up.
- With only 3 seeds per size, the bootstrap interval is descriptive. The difference is small, not a sign that Vulkan does better.
- **E1's conclusions carry over unchanged:**
  - Naive concatenation loses clearly measurable quality, and the loss grows with the number of chunks (0.13 → 0.19 → 0.53 nats at
    2K/4K/8K).
  - Prefix reuse is exact.

### Within-Vulkan bit-exact checks (pair (c)): all hold

| check | cells | result |
|---|---:|---|
| `prefix_reuse` logits vs full prefill | 15 | bit-identical |
| device-copy assembly vs host-write assembly: logits, and K/V of every row and layer | 15 | bit-identical |
| chunk 0 encoded alone (512-row forward, encode-sized cache) vs the full prefill's first 512 rows: K/V, every layer | 15 | bit-identical |

The last row is pair (c), **measured here**; G0 still lists the case as (b, 2048). What it shows is narrow: the two forwards have the
same row count (512), positions and tokens, and differ only in cache capacity, and they are bit-identical. The proposal for the G0
owner (not applied to `G0-floor/README.md`) is therefore: **(c) when the encode's forward has the same row count, positions and
tokens as a block of the reference prefill, at any cache capacity; otherwise unchanged**, i.e. (b, 2048) for ≥ 128 rows and (b, 64)
for 17–127 rows. A 200-row encode against the first 200 rows of a 512-row block is a different forward shape (G0: 512 vs 2048 rows
already differ by ~5e-4). Symbol chunks (median 107 tokens) never align with 512-row blocks, so they stay at (b, 64).

### CPU vs Vulkan on the same naive cache (pair (a))

| ctx | KL(CPU‖Vulkan) per seed | pooled KL (bound) | top-1 disagreement, pooled rows (bound) | worst-layer K / V mean ratio to (a) | worst-layer K / V p99 ratio | all-layer K / V (floor) |
|---:|---|---|---|---|---|---|
| 2048 | 2.5e-3, 3.7e-3, 2.2e-3 | 2.8e-3 (8.1e-3) | 5 of 192 (5.03) | 1.24 / 1.21 | 1.80 / 1.76 | 0.025 / 0.048 (0.023 / 0.045) |
| 4096 | 3.2e-3, 3.1e-3, 4.4e-4 | 2.3e-3 (8.1e-3) | 1 of 192 (5.03) | 1.30 / 1.27 | 1.98 / 2.02 | 0.026 / 0.050 (0.023 / 0.045) |
| 8192 | 5.4e-3, 4.3e-3, 4.9e-3 | 4.9e-3 (7.4e-3) | **7 of 192 (5.61)** | 1.21 / 1.21 | 1.66 / 1.78 | 0.025 / 0.049 (0.023 / 0.046) |
| 16384 | 4.8e-3, 2.9e-3, 3.8e-4 | 2.7e-3 (7.4e-3) | **6 of 192 (5.61)** | 1.22 / 1.23 | 1.06 / 1.07 (p99 bound ×1.6) | 0.026 / 0.050 (8K floor 0.023 / 0.046) |
| 32768 | **8.4e-3**, 6.1e-3, 4.5e-3 | 6.3e-3 (7.4e-3) | **9 of 192 (5.61)** | 1.22 / 1.22 | 1.06 / 1.06 (p99 bound ×1.6) | 0.026 / 0.050 (8K floor 0.023 / 0.046) |

- **KV:** every layer of every cell is within the single-context bounds: means ≤ 1.30× (bound 2×) and p99s ≤ 2.02× (bound 3×).
  The all-layer means are 1.06–1.12× the (a) floor. At 16K and 32K the KV is 1.22× the 8K floor's mean and about 1.06× its p99
  (× 1.6). CPU and Vulkan chunk encodes differ as much as full prefills do.
- **Logits:**
  - Per-task KL is within the (a) single-task bound up to 16K. At 32K, one seed (8.4e-3) exceeds it (7.4e-3).
  - Top-1 disagreement, pooled per size, exceeds the bound from 8K up: 7 / 6 / 9 of 192 rows at 8K / 16K / 32K, against 5.61.
    This uses the strict pooled reading: rate × 192 rows + 1 row once. The per-task reading, 3 × 2.54 = 7.6 rows, would pass 8K and
    16K.
  - Pooled KL: 8K 4.9e-3 is 1.7× the 8K pooled full-prefill floor (2.9e-3) and above its provisional 1.5× bound (4.4e-3). 32K
    6.3e-3 is 2.2× the 8K floor. Fewer than 20 tasks per size, so the single-task bound is the applicable one.
  - Greedy: the CPU and Vulkan naive greedy streams diverge in 3 of 15 cells (8K seed 1: 0.25 common-prefix share; 16K seed 1:
    0.19; 32K seed 0: 0.75). One flipped token cascades. EM against each backend's own full prefill is identical in every cell.

### Control: CPU vs Vulkan on the full prefill of the same tasks (review S4)

Run `results-control*` (2K/4K/8K, the same 9 contexts, `--cross-check cpu+full`, dotLLM `6025b79d`). It repeats the naive
cross-check (bit-identical to the main run) and adds CPU vs Vulkan on the **full** prefill of each context: the G0 (a) pair, on
these tasks.
- **Cross-process reproducibility, measured:** the control run's `results` rows (top-1, KL, EM) and its naive cross-check rows
  are identical, to every printed digit, to the main run's, which was a different process on another day. The control run
  itself was suspended by Modern Standby from 05:18 to 05:54 UTC: `run.ps1` held only `ES_SYSTEM_REQUIRED` then, which does not
  prevent it, and the heartbeat log shows the gap. Values are unaffected; its timings are not used. `run.ps1` and the lab now
  hold display- and execution-required requests (`KeepAwake.cs`, dotLLM `1e6fc40e`).

| ctx | KL full, per seed | KL naive, per seed | top-1 disagree full / naive, pooled (bound) | pooled KL full / naive |
|---:|---|---|---|---|
| 2048 | 2.6e-3, 3.1e-3, 2.1e-3 | 2.5e-3, 3.7e-3, 2.2e-3 | 3 / 5 (5.03) | 2.6e-3 / 2.8e-3 |
| 4096 | 2.4e-3, 2.6e-3, 1.1e-3 | 3.2e-3, 3.1e-3, 4.4e-4 | 4 / 1 (5.03) | 2.0e-3 / 2.3e-3 |
| 8192 | 4.0e-3, 2.5e-3, 2.9e-3 | 5.4e-3, 4.3e-3, 4.9e-3 | **6** / 7 (5.61) | 3.1e-3 / 4.9e-3 |

- **The top-1 excess is not a stale-cache effect.** On the full prefill of the same 8K tasks, CPU vs Vulkan also disagrees on 6 of
  192 rows, above the same bound, while G0's 8K tasks gave 1.6 %. Per-cell top-1 counts are about equal on the two states (full
  2, 2, 2 vs naive 3, 2, 2 at 8K). So the overshoot is task variance on these contexts: the (a) top-1 bound comes from G0's own 14
  tasks at 8K and does not transfer to E1's continuations. The greedy divergences are not stale-cache-specific either: the full
  state diverges in 2 of 9 cells (2K seed 1 0.94, 8K seed 0 0.81), the naive state in 1 of 9 (8K seed 1).
- **KL is slightly higher on the stale state.** Naive KL exceeds full KL in 7 of 9 cells and in all three 8K cells, pooled 1.56×
  at 8K, and 1.1× at 2K and 4K. A modest amplification of the backend difference on stale caches is plausible, but with 3 tasks
  per size it is a **hypothesis**, not a measured mechanism. No 16K/32K full-prefill control was run (the CPU full prefill takes
  16–60+ min per cell).
- **Why this is not a reuse bug: the KV comparison and the unit oracles.**
  - KV on the naive cache is at the (a) floor on every layer and cell (above). A wrong shift, wrong offset or layer mix-up would
    put the shifted rows at O(1) relative L2.
  - The GPU unit tests check against an independent oracle: layer 0 of the assembled chunk equals the model's own full prefill at
    the shifted positions (1.2e-6). On every layer, the device shift equals the host `RopeShift` to 6e-7.
  - The mutants for delta sign, skipped shift, wrong layer and wrong offset (T1–T5, T13) are all killed.
  - The paired naive KL-to-full against CPU E1 (±0.045 nats per cell) is too noisy to say anything at the scale of this excess
    (1e-3 to 3e-3 nats), so it is not part of the argument. The within-Vulkan bit-exact checks are not independent evidence for the
    shift either, because the same kernel runs on both sides.
- **Consequence for G3:** do not take a floor from these 3 tasks per size. Measure the (a) pair on the reuse state itself, with
  ≥ 20 tasks, alongside the same tasks' full-prefill (a) pair, as here. Judge reuse-arm cross-backend checks against that, not
  against G0's full-prefill top-1 rate.

### Speed (Vulkan, median over seeds)

| ctx | full prefill (tok/s) | CPU full prefill (tok/s, E1) | assembly, host write: ms (tok/s) | assembly, device copy: ms (tok/s) | shift per chunk (all 36 layers, one submit) | first token after full / naive |
|---:|---:|---:|---|---|---:|---|
| 2048 | 1.64 s (1,251) | 20.0 s (102) | 223 (9,200) | 28 (72,600) | 0.8 ms | 20 / 20 ms |
| 4096 | 5.09 s (805) | 49.8 s (82) | 438 (9,300) | 58 (71,100) | 0.8 ms | 26 / 25 ms |
| 8192 | 19.2 s (427) | 196 s (42) | 891 (9,200) | 113 (72,400) | 0.8 ms | 37 / 36 ms |
| 16384 | 72.2 s (227) | *946 s (17)*, other corpus | 1,774 (9,200) | 231 (70,800) | 0.8 ms | 59 / 58 ms |
| 32768 | 274.4 s (119; median) | not run | 3,362 (9,700) | 515 (63,600) | 0.8 ms | 102 / 135 ms |

Values are medians over seeds. **32K seed 1's full prefill took 4,723 s instead of about 274 s** (seeds 0 and 2: 274.4 s and
273.6 s). The same process's prefix-reuse suffix prefill right after it ran at normal speed (202 s), and the lock was ours.
- **The stall coincides, to within 10 s, with the Modern Standby session 03:02:03–04:16:22 UTC** (Kernel-Power 506 enter / 507
  exit). Its excess is 4,449 s; the session is 4,459 s. The prefill ran from about 03:01:23 to 04:20:06.
- The process ran normally afterwards, although the log shows the box re-entering Modern Standby at 04:16:22 (no 507 after that,
  while seed 2's prefill took a normal 273.6 s). So the exact trigger was a deep-idle phase within that session, not the standby
  state as such. A host thread blocked in a fence wait for minutes, with the GPU busy, looks idle to the power manager.
- `Stopwatch` counted through the stall. The Vulkan work resumed without a device loss, and the seed's quality numbers are
  unaffected (prefix reuse bit-exact).
- **Since the fix round, `run.ps1` holds a power request** (`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`) while a
  group runs, and the lab logs a heartbeat every 5 min, so a future stall shows as a gap in the run log. `powercfg /requests`
  needs an elevated prompt, so the request was not verified from this session.
- **The GPU-lock refresher (the `run.ps1` loop) was presumably frozen too.** The gap was ~75 min against the lock's 90-min
  staleness limit; a longer standby would have let another agent take the GPU lock in the middle of the run.

- **Chunk encode** (512 tokens, 336 encodes): Vulkan 1.35 s median, against 2.6 s on the CPU in the same process (3.4–3.9 s in
  E1, uncontended CPU).
  - The Vulkan encode splits into a ~270 ms forward, ~30 ms cache creation and **~1,050 ms host readback** of 36 layers × K/V
    (144 MiB).
  - `VulkanKvCache.ReadRows` stages through uncached host memory, about 145 MB/s (`vulkan-primitive-requests.md` §1).
  - A resident encode (`ChunkEncoder.EncodeResident`, no readback) costs only the forward.
- **Assembly:**
  - Host-write assembly is about 9,000 tok/s on Vulkan, against CPU E1 build times of 139 ms (2K), 265 ms (4K) and 534 ms (8K).
    So with host entries, Vulkan naive TTFT is no faster than the CPU's: equal at 2K (0.24 vs 0.25 s) and **1.2–1.55× slower at
    4K–16K** (0.46 vs 0.39 s, 0.93 vs 0.60 s, 1.83 vs 1.21 s; 16K's CPU value is from the other corpus).
  - 98 % of the host-write time is `WriteRows`: 1.5 ms per call, two fenced submits each (`vulkan-primitive-requests.md` §2).
  - Device-copy assembly is about 8× faster.
  - The RoPE shift is no longer a cost. It is recorded for all layers into one command buffer: about 0.8 ms per chunk (median;
    1.3 ms for the first call after warm-up), where Task 1 paid about 330 ms for row IO plus a per-layer shift.
- **TTFT naive / full:** with host-write assembly, 0.147 (2K), 0.091 (4K), 0.048 (8K), 0.025 (16K) and 0.013 (32K). With device
  copy it would be about 0.03, 0.016, 0.008, 0.004 and 0.002.
- **Memory at 32K.** The lab process peaked at about 56 GB private (host entries for both backends, the CPU naive cache and logits).
  Vulkan caches of about 9.4 GB each (full, naive and device copy, plus 9.2 GB of resident entries) sat in shared GPU memory. Nothing
  failed.

## Caveats

- **One model, one GPU, one driver.** These are lab measurements with 3 seeds per size; each cell is one context and one 64-row
  continuation.
- **Contention.** The CPU cross-check shares the process. Another agent's CPU jobs may have run, so CPU encode times are
  contended. Vulkan numbers come from a GPU held under the lock.
- **Measurement ordering.** The full-prefill time is measured after a warm-up encode, and the first context of a seed includes no
  JIT. Prefix reuse starts from the full prefill's own cache (rollback), as in E1.
- **Device-copy arm.** Resident entries are uploaded from the host entries (same bits a resident encode holds; the unit test
  `DeviceCopyAndHostWrite_AssembleIdentically` uses `EncodeResident`). Its timing excludes the upload.
- **CPU 16K was not re-run on the pinned corpus** (about 30 min of CPU). The 16K comparison with the CPU table is trend only, and no
  CPU 32K exists.

## Method and reproduction

- `./run.ps1 -Corpus <dir with git-archive 4a781829 src>` runs the size groups `small` (2K, 4K, 8K), `16k` and `32k`, holding the
  GPU lock per group and refreshing it every 10 min. Then run `uv run summarize.py`.
- Every output is written as `*.partial` and renamed only when its run finishes. Each log has the provenance block, then step
  markers (`[seed s ctx L +t s] step`).
- **Library and tests:** dotLLM `4503f67f`, `5d7ac6ef` and `c93fd1bf`.
  - `IChunkBackend.ForwardDeviceId` and `CopyRows`.
  - `ChunkEncoder.Encode(model, backend, …)` and `EncodeResident`.
  - `ResidentChunkKvEntry` and a resident `ChunkAssembler.Assemble` overload.
  - A one-submit Vulkan `ShiftKeys`.
  - `VulkanAssemblyTests` (2 CPU tests, 5 GPU tests on the synthetic F32 model on Vulkan).
- **Red phase:** a compile failure, `logs/red-build.log`.
- **Mutants:** 14 of 15 killed in `git archive` copies (`logs/mutants-t3*.log`, driver `logs/mutate3.py`). The 15th (T11, encoding
  with deviceId −1 on Vulkan) is equivalent: `VulkanTransformerModel` ignores `deviceId`.
- **Fix round 1** (review `review-task3-report.md`): dotLLM `6025b79d`, `6b667cdc` and `1e6fc40e`.
  - The assembler rolls the destination back to its start length on any failure while writing, and refuses a backend bound to
    other RoPE parameters.
  - Resident entries refuse use after `Dispose`, and the assembler refuses a destination that is a chunk's own cache.
  - `ShiftKeys` documents its contract and checks the range at delta 0.
  - The lab gained `--cross-check cpu+full`, a 5-min heartbeat and `KeepAwake`.
  - Red phase: `logs/red-build-fix1.log`.
  - Mutants: 9 of 10 killed (`logs/mutants-fix1.log`, driver `logs/mutate-fix1.py`), run in the live worktree as directed and
    restored byte for byte. F4 (the assembler's own disposed check) is redundant with the `Cache` getter guard.
  - The S4 control is `./run.ps1 -Groups control` (`results-control*`, `logs/results-control.log`).
