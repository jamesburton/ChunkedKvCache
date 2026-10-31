# E1 — baselines: full prefill vs naive chunk-KV concatenation vs exact prefix reuse

**Result in one line:** naive concatenation of isolated chunk KV (RoPE-shifted, no recompute) loses clearly measurable quality versus full
prefill. Mean KL is 0.13 / 0.17 / 0.55 / 0.67 nats at 2K / 4K / 8K / 16K, and top-1 agreement is 0.88 / 0.91 / 0.76 / 0.73. TTFT drops
from minutes to under a second on CPU. Exact prefix reuse is lossless but still prefills 25–50 % of the context (CPU TTFT is 33–77 % of
full). The gap that selective recompute (E2+) has to close is real.

## Setup

- **Engine:** dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse`, branch `feature/chunk-kv-reuse`, commit
  `48909bba` (harness `benchmarks/ChunkKvLab`, library `src/DotLLM.ChunkReuse` from Task 4). **CPU backend**
  (`TransformerModel`, `SimpleKvCache` F32), `ThreadingConfig(0)` = auto threads, Release build. Windows 11, Strix Halo (Zen 5, 16C/32T).
- **Model:** `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF`, `Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf` (rev `ae44f08e…`), read in place
  from the HF hub cache. 36 layers, 8 KV heads × 128, plain NeoX RoPE θ = 5e6. F32 KV = 294,912 B/token (144 MiB per 512-token chunk).
- **Corpus:** every `*.cs` under `C:\Development\dotLLM\src` (bin/obj excluded), in ordinal path order, CRLF→LF. Each file is tokenised
  **once** (no BOS) and cut into 512-token chunks. The tail of each file is dropped. That gives 1086 documents and about 7.26k chunks.
  Contexts are concatenations of chunk token ids, so the reference and the chunk methods see identical ids (pinned by
  `ContextBuilder_TokenizesChunksOnce_ConcatenatedIdsEqualPerChunkIds`).
- **Contexts (per seed):** one seeded permutation of all chunks. The **base** ordering (the earlier, "cached" request) is the first k
  chunks. The **request** ordering keeps the base's first k/2 chunks and re-shuffles the rest. Sizes are nested within a seed, so each
  chunk is encoded once. Seeds 0, 1, 2 for 2K/4K/8K. 16K uses **seed 0 only** (see Time).
- **Held-out continuation:** the 64 document tokens right after the request's last chunk. If they are missing or belong to a context
  chunk, the harness uses the start of an unused chunk instead. Every run here got the document successor.
- **Methods:**
  - `full` (reference) — prefill of the request ids in 512-token blocks.
  - `naive_concat` — each chunk is encoded in isolation at positions 0..511 (`ChunkEncoder`). `ChunkAssembler` places the chunks back to
    back with RoPE re-rotation of K. No recompute.
  - `prefix_reuse` — exact prefix caching. The longest identical leading chunk run of base and request is reused, and the rest is
    prefilled. The stored prefix KV is reproduced by truncating the request's own full cache to that run. This is exactly equal, because KV
    at positions < m depends only on tokens < m, and the prefill blocks fall on the same 512 boundaries. Then the suffix is prefilled.
- **Metrics (per method, same protocol):**
  - **Top1Agreement / MeanKl:** teacher-force the 64 continuation tokens at positions L..L+63 (all-row logits). Compare each position
    with the reference: argmax agreement and KL(P_ref ‖ P_method) in nats.
  - **ExactMatch:** feed the first continuation token, greedy-decode N = 16, and compare with the reference's 16 greedy tokens. The value
    is the common leading run divided by 16 (1.0 = identical).
  - **TtftMs:** cache build (prefill / assembly / truncate + suffix prefill) plus the first-token forward. Wall clock on CPU, indicative
    only.
  - **PrefillTokensComputed:** context tokens run through the model for this request. The encode cost of naive chunks is amortised and
    reported separately below.
  - **CacheBytes:** F32 bytes of precomputed KV read from earlier work. 0 for full, all chunk entries for naive, the matched prefix for
    prefix reuse.

Run: `./run.ps1` (2K/4K/8K × 3 seeds), `./run.ps1 -Sizes 16384 -Seeds 1 -Out results-16k.csv -Log e1-16k.log`,
`./run.ps1 -Command rope-precision`. Raw data: `results.csv`, `results-16k.csv` (the `RunRow` columns), `*-details.csv` (per-position KL
max/median/first-16/last-16, build vs first-token ms, matched chunks, encode ms/chunk, greedy text), `*.log`.

## Results

Mean over seeds (2K/4K/8K: 3 seeds; 16K: 1 seed). KL range is min–max over seeds.

| Method | Ctx | Top-1 | Mean KL (range) | Exact match | TTFT (s) | Prefill tokens | Reused KV (MiB) |
|---|---:|---:|---|---:|---:|---:|---:|
| full | 2048 | 1.000 | 0 | 1.000 | 20.0 | 2048 | 0 |
| naive_concat | 2048 | 0.875 | 0.131 (0.104–0.148) | 0.438 | 0.2 | 0 | 576 |
| prefix_reuse | 2048 | 1.000 | 0 | 1.000 | 12.0 | 1024 | 288 |
| full | 4096 | 1.000 | 0 | 1.000 | 49.8 | 4096 | 0 |
| naive_concat | 4096 | 0.906 | 0.174 (0.062–0.249) | 1.000 | 0.4 | 0 | 1152 |
| prefix_reuse | 4096 | 1.000 | 0 | 1.000 | 25.3 | 1707 | 672 |
| full | 8192 | 1.000 | 0 | 1.000 | 196.2 | 8192 | 0 |
| naive_concat | 8192 | 0.760 | 0.549 (0.355–0.695) | 0.417 | 0.6 | 0 | 2304 |
| prefix_reuse | 8192 | 1.000 | 0 | 1.000 | 145.5 | 3925 | 1200 |
| full | 16384 | 1.000 | 0 | 1.000 | 946.5 | 16384 | 0 |
| naive_concat | 16384 | 0.734 | 0.668 | 0.125 | 1.2 | 0 | 4608 |
| prefix_reuse | 16384 | 1.000 | 0 | 1.000 | 714.0 | 8192 | 2304 |

Chunk encode (amortised, not in TTFT): about 3.4–3.9 s per 512-token chunk on CPU (about 140 tok/s).

### Reading

- **The expectation holds: naive concatenation loses measurable quality.** Every naive row has KL > 0.06 nats and top-1 < 0.99.
  Per-position KL maxima reach 1.2–5.9 nats. The loss grows with the number of chunks: about 0.13 nats at 4 chunks, 0.55 at 16 and 0.67
  at 32. Greedy exact match is 1.0 in 4 of 10 cases but falls to 2/16 tokens in the worst 8K/16K cases.
- **What breaks is cross-chunk content, as expected.** Example (seed 1, 8K): the reference continues `!lw.HasV) { v = device.AllocateDeviceLocal(`.
  Naive writes `!lw.VWeightIsShared) { v = UploadMatrix(device,` — plausible code, but the identifiers come from a different chunk's
  context. Seed 0 at 2K swaps an argument order.
- **Variance across seeds is large** (4K: 0.06 to 0.25 nats). Whether the continuation depends on other chunks varies from context to
  context, so E2+ needs more seeds or more continuations per seed to separate methods.
- **Prefix reuse** is bitwise identical to full here (KL exactly 0 by construction: same tokens, same blocks). It is not a noise-floor
  measurement of the metric. The cost of exact prefix reuse is that only the leading run is reusable. With half of the request reordered it
  still prefills 25–50 % of the tokens (depending on how far the shuffle happens to match). On CPU this costs 33–77 % of full TTFT, because the suffix tokens are also the ones with the
  longest attention span.
- **TTFT on CPU** (indicative): full prefill grows faster than linearly (2K 20 s → 4K 50 s → 8K 196 s → 16K 946 s), so attention
  dominates at 8K+. Naive assembly is 0.1–1.0 s (a host F32 copy plus RoPE rotation of 144 MiB per chunk).

## RoPE-shift precision at large offsets (Task 4 open item)

`rope-precision`: layer-0 K depends only on token and position, and it is written to the cache before layer-0 attention. So a forward of
a 512-token chunk at positions Δ..Δ+511 gives the model's own layer-0 keys there. These are compared with `RopeShift.Apply(isolated keys, Δ)`.
Three random chunks (`rope-precision.csv`):

| Δ | max \|err\| | mean \|err\| | max \|K\| | max err / ‖head‖ | unshifted max diff (guard) |
|---:|---:|---:|---:|---:|---:|
| 1024 | 3.5e-4 – 4.2e-4 | 1.8e-6 – 2.2e-6 | ~290 | 2.7e-6 – 3.6e-6 | 16.5 – 18.6 |
| 4096 | 7.4e-4 – 8.6e-4 | 5.5e-6 – 6.9e-6 | ~290 | 5.8e-6 – 8.2e-6 | 51 – 59 |
| 8192 | 1.3e-3 – 1.6e-3 | 1.1e-5 – 1.3e-5 | ~290 | 1.0e-5 – 1.3e-5 | 18 – 20 |
| 16384 | 2.7e-3 – 3.2e-3 | 2.0e-5 – 2.5e-5 | ~290 | 2.1e-5 – 3.0e-5 | 36 – 43 |

The error is not bitwise and grows roughly linearly with Δ, as expected from float rounding of the angle Δ·freq for the
high-frequency pairs. It stays at ≤ 3e-5 of the head norm through 16K, about 4–5 orders of magnitude below the unshifted guard. At 8K that
is roughly 1e-3 absolute on keys of magnitude up to 290. It is negligible next to the naive-concat loss above, so E1's naive loss is due to
missing cross-chunk attention, not to the shift. Tolerances for large-Δ tests should be about 1e-5 relative, not 1e-5 absolute.

## Time (CPU)

- 2K + 4K + 8K × 3 seeds: **27.5 min** wall (about 9 min per seed: full 8K prefill 193–199 s, prefix 8K 138–151 s, 16 chunk encodes about 56 s).
- 16K × 1 seed: **30.2 min** wall (full prefill 946 s, prefix reuse 714 s, 32 chunk encodes 110 s). Three seeds at 16K would take about
  90 min, so 16K was run with one seed only and is indicative.
- rope-precision: 5.8 min.

## Caveats / decisions

- **CPU only.** Vulkan was not run. A public path exists (`VulkanTransformerModel.LoadFromGguf` + `CreateKvCache` +
  `IHostStagedKvCache.UploadLayer`, F32), but CPU-encoded chunks with a Vulkan reference would mix backends. Shared-GPU runs are also
  coordinated through the user. This is the next step for honest TTFT numbers.
- **Live corpus.** `C:\Development\dotLLM\src` is a live checkout. It advanced between the 2K–8K run and the 16K run (7257 → 7259
  chunks; now at dev `fc8fa0b0`), so chunk ids in the two runs are not the same chunks. Each run tokenises once, so it is self-consistent.
  For E2+, pin the corpus (e.g. `git archive <sha> src` into a scratch folder).
- **Fingerprint** includes the engine's MinVer informational version (commit SHA). The harness keeps chunks in memory only, so this is
  fine now. **Persisted-format decision for Phase S:** pin a format version instead.
- KL and top-1 are measured on teacher-forced continuation positions. The first context-dependent prediction (the continuation's first
  token, predicted from the last context token) is not in the KL set. It is covered by greedy exact match.
