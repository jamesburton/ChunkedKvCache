# G1: E1 on the dotLLM Vulkan backend (Phase G Task 3)

**Result in one line:** chunk encode, RoPE shift and assembly run on the Vulkan iGPU and reproduce the CPU E1 picture. Naive
concatenation's loss against full prefill is the same within a few percent of the gap. Inside Vulkan, every check that should be
bit-exact is bit-exact. Full prefill is about 10× faster than on the CPU. Device-copy assembly runs at about 70,000 tok/s. Host-write
assembly runs at about 9,000 tok/s, no faster than the CPU, because each `WriteRows` call costs about 1.5 ms. Chunk readback is
slow (about 145 MB/s). One concern: on the stale naive cache, the logits differ more between CPU and Vulkan than the full-prefill
floor (a) allows from 8K up (top-1 pooled 7 / 6 / 9 of 192 rows at 8K / 16K / 32K against 5.6). KV stays within 1.3× of the floor.

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

### E1 on Vulkan next to the CPU E1 table (mean over 3 seeds)

| method | ctx | top-1 Vulkan / CPU | mean KL Vulkan / CPU | EM Vulkan / CPU | TTFT Vulkan / CPU (s) |
|---|---:|---|---|---|---|
| full | 2048 | 1 / 1 | 0 / 0 | 1 / 1 | 1.66 / 20.0 |
| prefix_reuse | 2048 | 1 / 1 | 0 / 0 | 1 / 1 | 1.04 / 12.0 |
| naive_concat | 2048 | 0.865 / 0.875 | 0.128 / 0.131 | 0.438 / 0.438 | 0.25 / 0.25 |
| full | 4096 | 1 / 1 | 0 / 0 | 1 / 1 | 5.1 / 49.8 |
| prefix_reuse | 4096 | 1 / 1 | 0 / 0 | 1 / 1 | 3.0 / 25.3 |
| naive_concat | 4096 | 0.901 / 0.906 | 0.187 / 0.174 | 1 / 1 | 0.48 / 0.39 |
| full | 8192 | 1 / 1 | 0 / 0 | 1 / 1 | 19.2 / 196 |
| prefix_reuse | 8192 | 1 / 1 | 0 / 0 | 1 / 1 | 13.6 / 146 |
| naive_concat | 8192 | 0.771 / 0.760 | 0.527 / 0.549 | 0.417 / 0.417 | 0.94 / 0.60 |
| full | 16384 | 1 / *1* | 0 / *0* | 1 / *1* | 72.2 / *946* |
| prefix_reuse | 16384 | 1 / *1* | 0 / *0* | 1 / *1* | 52.9 / *714* |
| naive_concat | 16384 | 0.792 / *0.734* | 0.621 / *0.668* | 0.25 / *0.125* | 1.83 / *1.21* |
| full | 32768 | 1 / not run | 0 / – | 1 / – | 274.5 (median; seed 1 stalled, see below) / – |
| prefix_reuse | 32768 | 1 / not run | 0 / – | 1 / – | 201 / – |
| naive_concat | 32768 | 0.583 / not run | 1.175 (0.78, 1.23, 1.52) / – | 0.167 / – | 3.5 / – |

Italic CPU values at 16K are E1's single seed-0 run on the live dotLLM tree (7259 chunks): different contexts, trend only.
16K Vulkan per-seed naive KL: 0.83 / 0.96 / 0.07. The seed spread is as large as on the CPU at 4K.

**Naive vs full, paired with CPU E1 by seed (2K–8K, 9 cells):**
- The Vulkan naive KL-to-full differs from the CPU one by −0.045 to +0.027 nats. The mean ΔKL is −0.004.
- On average that is 8.5 % of the naive→full gap: 0.6–7.4 % at 2K and 8K, and up to 39 % at 4K seed 2, where the gap itself is only
  0.06 nats.
- Top-1 differs by at most 2 of 64 rows. Greedy exact match against each backend's own full prefill is identical in all 9 cells.
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

The last row **measures** what the G0 table lists as "unmeasured" (a chunk at position 0 encoded alone vs the full prefill). For
≥ 128-row (coopmat) encodes it is bit-exact, so pair (c) applies there despite the different cache capacity. 17–127-row encodes
stay unmeasured. This is a proposal for the G0 owner; `G0-floor/README.md` was not edited here.

### CPU vs Vulkan on the same naive cache (pair (a))

| ctx | KL(CPU‖Vulkan) per seed | pooled KL (bound) | top-1 disagreement, pooled rows (bound) | worst-layer K / V mean ratio to (a) | worst-layer K / V p99 ratio | all-layer K / V (floor) |
|---:|---|---|---|---|---|---|
| 2048 | 2.5e-3, 3.7e-3, 2.2e-3 | 2.8e-3 (8.1e-3) | 5 of 192 (5.03) | 1.24 / 1.21 | 1.80 / 1.76 | 0.025 / 0.048 (0.023 / 0.045) |
| 4096 | 3.2e-3, 3.1e-3, 4.4e-4 | 2.3e-3 (8.1e-3) | 1 of 192 (5.03) | 1.30 / 1.27 | 1.98 / 2.02 | 0.026 / 0.050 (0.023 / 0.045) |
| 8192 | 5.4e-3, 4.3e-3, 4.9e-3 | 4.9e-3 (7.4e-3) | **7 of 192 (5.61)** | 1.21 / 1.21 | 1.66 / 1.78 | 0.025 / 0.049 (0.023 / 0.046) |
| 16384 | 4.8e-3, 2.9e-3, 3.8e-4 | 2.7e-3 (7.4e-3) | **6 of 192 (5.61)** | 1.22 / 1.23 | 1.06 / 1.07 (p99 bound ×1.6) | 0.026 / 0.050 (8K floor 0.023 / 0.046) |
| 32768 | **8.4e-3**, 6.1e-3, 4.5e-3 | 6.3e-3 (7.4e-3) | **9 of 192 (5.61)** | 1.22 / 1.22 | 1.06 / 1.06 (p99 bound ×1.6) | 0.026 / 0.050 (8K floor 0.023 / 0.046) |

- **KV:** every layer of every cell is within the single-context bounds: means ≤ 1.30× (bound 2×) and p99s ≤ 2.02× (bound 3×).
  The all-layer means are 1.07–1.13× the (a) floor. CPU and Vulkan chunk encodes differ exactly as much as full prefills do.
- **Logits:**
  - Per-task KL is within the (a) single-task bound up to 16K.
  - **Top-1 at 8K is not.** Seed 0 disagrees on 3 rows (bound 2.54), and the pooled 8K count is 7 of 192 (bound 5.61, i.e.
    3.6 % against 2.4 %).
  - The pooled 8K KL (4.9e-3) is 1.7× the pooled 8K full-prefill floor (2.9e-3).
  - The same holds at 16K (6 of 192) and 32K (9 of 192, about 4.7 %). At 32K, one seed's KL (8.4e-3) also exceeds the single-task
    bound (7.4e-3).
  - KV at 16K and 32K is still 1.22× the 8K floor's mean and about 1.06× its p99 (× 1.6).
- **Interpretation: not a Vulkan reuse bug.**
  - A placement or shift bug would make the Vulkan naive cache worse than the CPU one. It is not: the paired naive KL-to-full is
    within ±7 % of the gap at 8K, and lower in 2 of 3 seeds.
  - The KV deviation equals the full-prefill floor at every layer.
  - The device shift agrees with the host shift to about 1e-7, and the layer-0 oracle passes.
  - What fails is the transfer of the (a) floor, measured on confident full-prefill logits, to logits over a stale cache. There the
    same KV perturbation moves the distribution about twice as much.
- **Consequence for G3:** cross-backend comparisons of reuse arms need a floor measured on the reuse state itself, not (a). This
  table is a provisional naive-state floor: about 3–6e-3 nats pooled and 3–5 % top-1 at 8K–32K, from 3 tasks of 64 rows per
  size. The difference grows with how stale the cache is: naive KL-to-full rises from 0.13 to 1.18 nats between 2K and 32K.

### Speed (Vulkan, median over seeds)

| ctx | full prefill (tok/s) | CPU full prefill (tok/s, E1) | assembly, host write: ms (tok/s) | assembly, device copy: ms (tok/s) | shift per chunk (all 36 layers, one submit) | first token after full / naive |
|---:|---:|---:|---|---|---:|---|
| 2048 | 1.64 s (1,251) | 20.0 s (102) | 223 (9,200) | 28 (72,600) | 0.8 ms | 20 / 20 ms |
| 4096 | 5.09 s (805) | 49.8 s (82) | 438 (9,300) | 58 (71,100) | 0.8 ms | 26 / 25 ms |
| 8192 | 19.2 s (427) | 196 s (42) | 891 (9,200) | 113 (72,400) | 0.8 ms | 37 / 36 ms |
| 16384 | 72.2 s (227) | 946 s (17) | 1,774 (9,200) | 231 (70,800) | 0.8 ms | 59 / 58 ms |
| 32768 | 274.4 s (119; median) | not run | 3,362 (9,700) | 515 (63,600) | 0.8 ms | 102 / 135 ms |

Values are medians over seeds. **32K seed 1's full prefill took 4,723 s instead of about 274 s** (seeds 0 and 2: 274.4 s and
273.6 s). The same process's prefix-reuse suffix prefill right after it ran at normal speed (202 s), and the lock was ours, so
this is an external stall (another process, memory pressure or a host suspend), not a property of the code. Its quality numbers
are unaffected.

- **Chunk encode** (512 tokens, 336 encodes): Vulkan 1.35 s median, against 2.6 s on the CPU in the same process (3.4–3.9 s in
  E1, uncontended CPU).
  - The Vulkan encode splits into a ~270 ms forward, ~30 ms cache creation and **~1,060 ms host readback** of 36 layers × K/V
    (144 MiB).
  - `VulkanKvCache.ReadRows` stages through uncached host memory, about 145 MB/s (`vulkan-primitive-requests.md` §1).
  - A resident encode (`ChunkEncoder.EncodeResident`, no readback) costs only the forward.
- **Assembly:**
  - Host-write assembly is about 9,000 tok/s on Vulkan, against CPU E1 build times of 139 ms (2K), 265 ms (4K) and 534 ms (8K). So
    with host entries, naive TTFT is about the same on both backends.
  - 98 % of the host-write time is `WriteRows`: 1.5 ms per call, two fenced submits each (`vulkan-primitive-requests.md` §2).
  - Device-copy assembly is about 8× faster.
  - The RoPE shift is no longer a cost. It is recorded for all layers into one command buffer: about 1 ms per chunk, where Task 1
    paid about 330 ms for row IO plus a per-layer shift.
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
