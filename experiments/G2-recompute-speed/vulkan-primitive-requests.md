# Requests for the dotLLM Vulkan owner (from Phase G Task 4; not filed, needs the user's approval)

No Vulkan code or shader was changed by this task. G1's requests (`../G1-e1-vulkan/vulkan-primitive-requests.md`: slow `ReadRows`
staging, per-call fenced `WriteRows`/`CopyRowsFrom`, no device identity on `VulkanKvCache`, `SubmitContext.Begin()` clearing the
hazard tracker) still stand. Two more:

## 5. The per-query-position attention (`ATTN_QPOS`, #1534) is ~20x slower per row than the prefill attention

**Why it matters.** Selective recompute over an assembled chunk cache must run every recomputed row through `ATTN_QPOS`: the rows sit
inside a filled cache and are usually non-contiguous. With the current kernel, reuse with recompute at best ties full prefill (2K, 5 %:
1.07×) and loses at every larger budget or context (2K 20 %: 0.28×; 8K 5 %: 0.96×; 16K 5 %: an estimated 0.7–0.85×; G2 README,
verdict).

**Observed** (Qwen3-4B Q4_K_M, F32 KV, Radeon 8060S, driver 26.10.1; `ChunkKvLab recompute`, dotLLM `feature/chunk-reuse-vulkan`; timing
groups, medians over contexts of the median of 3 repeats):
- **Control arm:** the same k contiguous rows, same forward shape and matmul regime; only the attention kernel differs. The k rows run as
  the tail `[L-k, L)` (ordinary kernel) vs one row earlier `[L-k-1, L-1)` (`ATTN_QPOS`):
  - 2K: 410 rows, 0.51 s vs 11.4 s (22×, 8 contexts).
  - 8K: 128 rows, 0.68 s vs 18.5 s (27×, 2 contexts).
  - 16K: 64 rows, 0.69–0.71 s vs 19.6–19.7 s (28×, 1 context, two runs). An earlier 16K run measured 68.4 s (78×); it was ~3.5× slow on
    ATTN_QPOS only, and the cause is unknown.
- **Single-pass recompute at 2K** (one forward, 8 contexts): 1.60 / 3.21 / 6.61 s for 102 / 205 / 410 rows (~16 ms per row). The full
  prefill of the same 2K context takes 1.66 s.
- **Cost per (row × visible key)**, whole forward over 36 layers: 13–19 µs at 2K, 8K and 16K alike (~14.4 µs at 2K net of the
  ordinary-tail forward).
- **GPU timestamps** (`DOTLLM_VULKAN_PREFILL_PROFILE=gpu`, one control forward each):
  - 2K, 128 rows: ATTN_QPOS 3,187 of 3,273 ms (97.4 %) vs flash `attn_flash_cm` 122 of 178 ms (26×).
  - 16K, 64 rows: 19,640 of 19,720 ms (99.6 %) vs 639 of 707 ms (31×).
- **TDR / stability:** single submits of 30–68 s did not trigger a reset (`TdrDelay` 10 s), and a 64-row ATTN_QPOS forward at 16K takes
  ~20 s. The box also froze twice, with unclean reboots, while G2 ATTN_QPOS workloads were running (11:35 and ~17:20 UTC). There was no
  TDR or bugcheck event, the cause is unknown, and other jobs may have been running.

**Likely cause** (from the shader, not instrumented beyond the profile above):
- `attention_f32.glsl` with `ATTN_QPOS` dispatches one 256-thread workgroup per (query row, head), with a serial loop over the keys.
- Each workgroup reads the whole K and V of its KV head; nothing is reused across the query rows (or across the 4 query heads of a GQA
  group) that share it.
- At 2K one KV head's K+V per layer is 2 MB (16 MB for all heads), which fits L2/MALL. The cost per (row × key) is flat from 2K to 16K
  (8 MB per head), so it is probably latency or occupancy (serial per-row key loop, little parallelism per workgroup) rather than DRAM
  bandwidth. That is a hypothesis.

**Ask.** A tiled per-query-position attention:
- A block of query rows, and the GQA heads of one KV head, per workgroup, sharing K/V tiles in shared memory.
- Flash-style online softmax, masking each row by its own position.

**Targets from G2** (needed speedup of the **kernel**, single pass; range from "non-attention work ≈ 0" to "= the ordinary-tail control's
forward time"):

| point | to break even | for a 2× TTFT gain |
|---|---|---|
| 2K, 5 % | ~1.0× | 2.1–2.4× |
| 2K, 10 % | 2.0–2.2× | 4.3–5.9× |
| 2K, 20 % | 4.2–5.7× | 8.8–25× |
| 8K, 5 % | 1.4× | 2.8–3.4× |
| 8K, 20 % | 5.5–9.5× | ≥ 11× |
| 16K, 5 % (estimated recompute 100–125 s) | 1.5–2.0× | 3.1–5.1× |

A kernel as fast as the ordinary one (the control: 1.24 ms per row for these rows at 2K) would make 20 % recompute at 2K ≤ 0.51 s, i.e.
≤ 0.58 s TTFT against a 1.66 s prefill (~2.8×).

**Repro.** Any filled F32 `VulkanKvCache` of L rows: time `Forward(ids[L-k-1 .. L-2], positions L-k-1 .. L-2, cache)` against
`Forward(ids[L-k .. L-1], positions L-k .. L-1, cache)` (same k). `AttentionQueryPositionsCount` confirms the routing, and
`DOTLLM_VULKAN_PREFILL_PROFILE=gpu` gives the per-bucket GPU time.

**Also asked: a public way to know the kernel is loaded.**
- The model creates `_attentionQPos` only when `attention_f32_qpos.spv` exists, and the field is private.
- A caller therefore cannot refuse a model without it before writing. ChunkReuse can only detect the fallback after the forward (through
  `AttentionQueryPositionsCount`) and report the cache as corrupt.
- A public `bool SupportsQueryPositionAttention` (or similar) on `VulkanTransformerModel` would let the recomputer refuse up front, as it
  already does for F16 KV and attention sinks.

## 6. `DescriptorSetCache` overflows with many live caches (1024 tuples per kernel)

**Observed.** `ChunkEncoder.EncodeResident` of the 58 symbol chunks of one 8K context (each chunk a forward into its own live
`VulkanKvCache`) throws `InvalidOperationException: DescriptorSetCache overflow: more than Capacity=1024 distinct buffer tuples
(buffersPerSet=6)` in `RopeKvWriteF32Kernel.Record` (58 caches × 36 layers > 1024). The lab now makes resident entries by uploading host
entries (`WriteRows`), which avoids the forward. A chunk store that keeps many resident chunks on the device hits this.

**Ask.** Evict (LRU) or reset the descriptor-set cache when it fills, or key it per forward, instead of throwing.
