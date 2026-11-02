# Requests for the dotLLM Vulkan owner (from Phase G Task 4; not filed, needs the user's approval)

No Vulkan code or shader was changed by this task. G1's requests (`../G1-e1-vulkan/vulkan-primitive-requests.md`: slow `ReadRows`
staging, per-call fenced `WriteRows`/`CopyRowsFrom`, no device identity on `VulkanKvCache`, `SubmitContext.Begin()` clearing the
hazard tracker) still stand. Two more:

## 5. The per-query-position attention (`ATTN_QPOS`, #1534) is ~20x slower per row than the prefill attention

**Why it matters.** Selective recompute over an assembled chunk cache must run every recomputed row through `ATTN_QPOS` (rows sit inside
a filled cache, and are usually non-contiguous). With the current kernel, recomputing 5 % of a 2K context costs as much as a full
prefill, and 20 % costs about 4x more, so chunk reuse with recompute cannot beat full prefill on this iGPU (G2 README, verdict).

**Observed** (Qwen3-4B Q4_K_M, F32 KV, Radeon 8060S, driver 26.10.1; `ChunkKvLab recompute`, dotLLM `feature/chunk-reuse-vulkan`):
- A single forward of k rows recomputed inside a 2K cache: ~15-17 ms per row (102 rows 1.6 s, 205 rows 3.4 s, 409 rows 7.1 s, 2045 rows
  30 s), linear in k. A full prefill of the 2045 rows (512- or 2048-row blocks, ordinary attention) takes 1.66 s, ~0.8 ms per row.
- Control arm: the same k rows, same forward shape and matmul regime; only the attention kernel differs. The k rows run as the tail
  `[L-k, L)` (ordinary kernel) vs one row earlier `[L-k-1, L-1)` (`ATTN_QPOS`).
- Control arm results:
  - 2K: 410 rows, 0.51 s vs 11.4 s (22×).
  - 8K: 128 rows, 0.68 s vs 18.5 s (27×).
  - 16K: 64 rows, 0.88 s vs 68.4 s (78×).
- Cost per (row × visible key) over 36 layers: ~15 µs at 2K, ~18 µs at 8K, ~65 µs at 16K. It grows faster than linearly past 8K.
- Single submits of 30–68 s did not trigger a TDR reset (`TdrDelay` 10 s). A 64-row ATTN_QPOS forward at 16K already takes 68 s, so
  long contexts need a split inside the forward or a faster kernel.

**Likely cause (from the shader, not instrumented).** `attention_f32.glsl` with `ATTN_QPOS` dispatches one 256-thread workgroup per
(query row, head) and streams the whole K and V of its KV head for every query row, with no reuse across the query rows (or the 4 query
heads of a GQA group) that share it. Bytes read ≈ rows × 32 heads × seqKv × 2 × 128 × 4 B × 36 layers ≈ 1 TB for 409 rows at 2K, i.e.
~150 GB/s over the ~6.7 s attention time, which looks bandwidth-bound on re-streaming (a hypothesis; the 32 MB MALL could serve some of it).

**Ask.** A tiled per-query-position attention: a block of query rows (and the GQA heads of one KV head) per workgroup sharing K/V tiles
in shared memory, flash-style online softmax, masking each row by its own position. Break-even targets from G2: the per-row cost would
have to fall by about (recompute time) / (full prefill − assembly) for the recompute to break even, ≈ 1x at 5 %, ≈ 2x at 10 %, ≈ 4.3x at
20 % of a 2K context, and more at 8K (README). A flash-class kernel (~0.8 ms per row at 2K) would make 20 % recompute ~0.4 s against a
1.66 s prefill.

**Repro.** Any filled F32 `VulkanKvCache` of L rows; time `Forward(ids[L-k-1 .. L-2], positions L-k-1 .. L-2, cache)` against
`Forward(ids[L-k .. L-1], positions L-k .. L-1, cache)` (same k); `AttentionQueryPositionsCount` confirms the routing.

## 6. `DescriptorSetCache` overflows with many live caches (1024 tuples per kernel)

**Observed.** `ChunkEncoder.EncodeResident` of the 58 symbol chunks of one 8K context (each chunk a forward into its own live
`VulkanKvCache`) throws `InvalidOperationException: DescriptorSetCache overflow: more than Capacity=1024 distinct buffer tuples
(buffersPerSet=6)` in `RopeKvWriteF32Kernel.Record` (58 caches × 36 layers > 1024). The lab now makes resident entries by uploading host
entries (`WriteRows`), which avoids the forward. A chunk store that keeps many resident chunks on the device hits this.

**Ask.** Evict (LRU) or reset the descriptor-set cache when it fills, or key it per forward, instead of throwing.
