# Sweep (c)+(d): recurrent-state chunk reuse and runtime support

Date: 2026-10-31. Tools: WebSearch (extended unless noted) + WebFetch on primary pages.
Status key: VERIFIED = I fetched the primary page (arXiv abs/repo/docs/issue) and the stated fact appears there. UNVERIFIED = seen only in search snippets/secondary pages, or the fetch did not cover it.

## Queries run (exact)
1. hybrid model prefix caching Mamba Gated DeltaNet state checkpoint vLLM SGLang
2. llama.cpp hybrid recurrent model prefix cache checkpoint Qwen3-Next state
3. composing independently encoded chunks recurrent state linear attention SSM RAG state reuse arXiv
4. LMCache CacheBlend non-prefix KV reuse vLLM SGLang TensorRT-LLM position-independent caching support 2026
5. PICASO permutation-invariant context composition with state space models
6. hybrid linear attention full attention model position-independent KV cache chunk reuse CacheBlend GDN layers
7. HYPIC position-independent caching hybrid LLM exact composition recurrent states
8. SGLang OR vLLM OR "TensorRT-LLM" OR llama.cpp native position-independent caching non-prefix KV blending release notes
9. chunk-parallel Gated DeltaNet associative scan state composition WY representation chunkwise parallel delta rule (standard mode)
10. TensorRT-LLM KV cache reuse hybrid Mamba Gated DeltaNet Qwen3-Next prefix reuse support

## A. Papers / systems: recurrent-state composition across independently encoded chunks

| Item | Year | URL | What it does | Status |
|---|---|---|---|---|
| HYPIC (Liu et al.) | 2026 (v1 1 Jul, v2 12 Jul) | https://arxiv.org/abs/2607.01299 ; code https://github.com/redai-infra/HYPIC | Position-independent caching for hybrid linear+full-attention LLMs. Caches each segment's cumulative transition operator plus zero-start end state; composes segments in constant time ("near-exact", not claimed exact). Seam window (default 8 tokens) recompute repairs full-attention layers. Reported TTFT 3.25x avg, QPS 1.66x vs Prefix Cache, within 1.71 pts of full recompute (abstract only; models/metric not named in abstract). | VERIFIED (abstract + repo README); full-paper numbers UNVERIFIED |
| LinearKV (Liu et al.) | 2026 (31 Jul) | https://arxiv.org/abs/2608.11231 | Training-free PIC for hybrids: each linear layer initialises from ONE cached chunk state; full-attention KV concatenated; repair positions replayed in order with any selector (e.g. EPIC). Claims exact K-state composition (as in HYPIC) is unnecessary and hurts on Mamba-2. Up to 92% of full-prefill quality on two "GDN" models; TTFT 0.46x full prefill; LongBench QA/RULER 8K-32K. No code link on abs page. | VERIFIED (abs page); "GDN" = Gated DeltaNet UNVERIFIED (page does not expand it) |
| Tail-Replay (Liu et al.) | 2026 (31 Aug; v2 15 Oct) | https://arxiv.org/abs/2608.30310 | Prefix caching (not position-independent) for GDN hybrids: store exact full-attn KV, skip recurrent checkpoints, rebuild linear state by replaying a short recent suffix (exploits GDN decay). 5-10% replay keeps 92.8-99.9% quality; TTFT 9.1-14.3x at 32K. No code link. | VERIFIED (abs page) |
| PICASO (Liu, Achille, ..., Soatto) | 2025 (ICLR) | https://arxiv.org/abs/2502.17605 | Merges per-context SSM states into one that approximates concatenation; permutation-averaged for order invariance (PICASO-S / -R). WikiText, MSMARCO; ~5.4x speedup matching strongest baseline. SSMs (Mamba-class) only; models not named on abs page. | VERIFIED (abs page) |
| Document souping (Jafari et al.) | 2025 (v3 2 Oct 2026) | https://arxiv.org/abs/2505.24033 | Encode docs independently with finetuned Mamba2, pool (average) hidden states into one context state; competitive with monolithic on multi-hop QA, beats concatenation on RACE/QuALITY, up to 256 segments. | VERIFIED (abs page) |
| Priming: Hybrid SSMs from Pre-trained Transformers | 2026 | https://arxiv.org/html/2605.08301v1 | Section 7.1 "Hybrid States Composition": chunk, prefill chunks independently, merge states (concat KV + compose recurrent states), then query prefill; training-free context extension 128K->256K. Appendix E: Mamba-2 uses CASO/PICASO, GDN uses "PICASO with dense transition matrices". Models primed from Qwen3 8B/32B. Only first 100K of 365K chars read. | PARTLY VERIFIED (text partially read; numbers and GDN details UNVERIFIED) |
| PRECOG / SMC (BrainChip) | 2026 (3 Aug) | https://arxiv.org/html/2608.02560 | Offline per-chunk SSM states injected as initial state; top-k composed by softmax-weighted average (heuristic, no error bound; top-3 trails top-1 by ~1.6 F1). 1.2B TENNs-LLM, pure SSM. | VERIFIED (page, first 100K chars) |
| KVBoost | 2026 (May) | https://arxiv.org/html/2608.21362v1 | CacheBlend-style chunk KV reuse for RoPE transformers; no recurrent/hybrid support. | VERIFIED (negative: no hybrid) |
| EmbeddingRWKV | 2026 | https://arxiv.org/pdf/2601.07861 | Reusable cached RWKV states for reranking. | UNVERIFIED (snippet only) |
| Sparse Prefix Caching for Hybrid/Recurrent LLMs (Shirokikh, Nikolenko) | 2026 (17 Apr) | https://arxiv.org/abs/2605.05219 | Exact recurrent-state checkpoints at DP-optimised sparse positions; resume from deepest checkpoint. Prefix only. | VERIFIED (abs page) |
| Gated DeltaNet / Parallelizing Linear Transformers with the Delta Rule | 2024-25 | https://arxiv.org/abs/2412.06464 ; https://arxiv.org/abs/2406.06484 | WY-representation chunkwise-parallel training algorithm; state propagates chunk to chunk. | Identity of papers VERIFIED via search listing only; the claim that an explicit chunk-level associative scan is described is UNVERIFIED (one snippet says step count is O(L/C) "without chunk-level parallel scan"). Note GDN transition is affine in the state, so (A,B) operators compose associatively (my inference; HYPIC's "transition operator" is exactly this idea). |
| StateFlow | 2026 | https://arxiv.org/html/2608.06838v1 | Sequence pipeline parallelism, boundary-state propagation for linear recurrence; training-style parallelism, not independent-chunk reuse. | UNVERIFIED (snippet only) |

## B. Hybrid prefix caching in runtimes

| Item | Year | URL | What it does | Status |
|---|---|---|---|---|
| vLLM APC docs (hybrid Mamba) | 2026 | https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/ | Mamba state stored only on block grid; hit resumes at block boundary only. `--enable-mamba-shared-prefix-checkpoint` + `--prefix-match-unit` (e.g. 64) for finer checkpoints; off by default. Docs do not mention GDN by name or non-prefix reuse. | VERIFIED |
| vLLM RFC #64267 | 2026-10-28 | https://github.com/vllm-project/vllm/issues/64267 | Open RFC: GDN-state checkpoint within blocks (16 tokens Triton/FLA, 64 FlashInfer), CPU offload, for Qwen3.5 PrefixLM workload. Self-reported gains. | VERIFIED (open, unmerged) |
| vLLM issue #40696 | 2026 | https://github.com/vllm-project/vllm/issues/40696 | Qwen3.5-4B attention block set to 528 tokens to match mamba page; short prompts 0% hit. | UNVERIFIED (search snippet only) |
| SGLang Unified Radix Cache | 2026-08-11 | https://www.lmsys.org/blog/2026-08-11-unified-radix-cache/ | One token-keyed radix tree with FULL / SWA / MAMBA components; MAMBA = recurrent checkpoint at reusable frontier; page size 64 in benchmarks; Qwen3-Next-80B-A3B, Qwen3.5-397B, Kimi-K3 (KDA) covered. Prefix-only; blog mentions no non-prefix reuse. | VERIFIED |
| SGLang Qwen3.8-27B cookbook | 2026 | https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B | Qwen3.8-27B = 48 GDN + 16 full-attn layers (3:1). `--mamba-radix-cache-strategy` {extra_buffer, extra_buffer_lazy, no_buffer}; GDN state slot ~154 MB fp32 / ~78 MB bf16. NOTE: this is 27B; the page for "Qwen3.8-Flash-Next" was not found, its architecture is UNVERIFIED. | VERIFIED for 27B only |
| llama.cpp (upstream) context checkpoints | 2026 | https://github.com/ggml-org/llama.cpp/issues/21831 | Hybrid/recurrent models can only resume from saved checkpoints (`--ctx-checkpoints`, `--checkpoint-every-n-tokens` renamed/changed to `--checkpoint-min-step` per user reports; ~70-110 MB each). Frequent "forcing full prompt re-processing". Issue closed not-planned/stale; no maintainer reply in the read portion. Final 17K chars unread. | PARTLY VERIFIED (user reports, not docs) |
| llama.cpp fork PRs (Piggidragon) | 2026 | https://github.com/Piggidragon/llama.cpp/pull/34 | `--checkpoint-root`, `--checkpoint-spread` conversation cache for hybrids. Personal fork, unmerged. | UNVERIFIED (snippet only) |
| TensorRT-LLM KV cache docs | 2026 | https://nvidia.github.io/TensorRT-LLM/latest/features/kvcache.html | Hybrid Mamba cache manager lists Qwen3-Next; block reuse retains Mamba state with attention prefix; per_conversation policy disables periodic Mamba snapshots. | UNVERIFIED (search summary only; page not fetched) |
| vllm-metal PR #584 | 2026 | https://github.com/vllm-project/vllm-metal/pull/584 | Prefix caching for hybrid GDN (Qwen3.5) on Metal. | UNVERIFIED (snippet only) |

## C. Position-independent / non-prefix KV reuse in runtimes (part d)

| Item | Year | URL | What it does | Status |
|---|---|---|---|---|
| LMCache CacheBlend non-prefix reuse | 2025-26 | https://docs.lmcache.ai/kv_cache_optimizations/blending.html ; https://github.com/LMCache/LMCache | Non-prefix reuse via CacheBlend recompute (check layer, ratio e.g. 0.15), layerwise mode, special separator string, individually tokenised chunks; examples use vLLM. Docs page says in-process mode is deprecated in favour of MP mode. No model list; no hybrid/Mamba mention. | VERIFIED |
| LMCache issue #3238 | 2026-05-09, active to 2026-10-15 | https://github.com/LMCache/LMCache/issues/3238 | Open: CacheBlend non-prefix reuse not working through the vLLM V1 connector (lookup matches contiguous prefix only); tested Qwen2.5-1.5B, vLLM 0.18-0.20; vLLM 0.31.0 fails earlier. No maintainer reply. | VERIFIED |
| HYPIC on SGLang v0.5.14 | 2026 | https://github.com/redai-infra/HYPIC | Only runtime found with native PIC for hybrids: fork of SGLang; Qwen3.5-35B-A3B, Qwen3.5-122B-A10B, Ring-mini/flash-linear-2.0. Requires `--page-size 1`, `--chunked-prefill-size -1`, `--disable-piecewise-cuda-graph`, `<<PIC_SEP>>` separators. Research fork, 20 stars, no releases. | VERIFIED |
| EPIC | 2024 | https://arxiv.org/html/2410.15332v1 | Position-independent context caching (dense transformers). | UNVERIFIED (snippet) |
| TensorRT-LLM semantic KV reuse RFC #14918 | 2026 | https://github.com/NVIDIA/TensorRT-LLM/issues/14918 | Proposal only; semantic not CacheBlend. | UNVERIFIED (snippet) |
| SemBlend | 2026 | https://pypi.org/project/semblend/ | Third-party semantic donor reuse claiming vLLM/LMCache/SGLang. | UNVERIFIED |
| CacheClip, "Models Take Notes at Prefill", chunk-level reuse study | 2025-26 | https://arxiv.org/pdf/2510.10129 ; https://arxiv.org/pdf/2606.17107 ; https://arxiv.org/html/2603.20218 | Dense-transformer chunk-KV reuse/composition work, not read. | UNVERIFIED (snippets) |

## Verdict: chunk-level reuse for recurrent (GDN) layers

PARTLY COVERED, no longer open in the basic sense, and mostly in research code, not mainstream runtimes.

- Basic problem (compose independently encoded chunks' recurrent state for hybrids) has at least three 2026 answers: HYPIC (operator composition, near-exact, code on SGLang), LinearKV (single cached state + repair, 92% quality on GDN models), and Priming's training-free state composition (PICASO-style, Qwen3-derived hybrids). Pure-SSM precedents: PICASO (2025), souping (2025), PRECOG (2026).
- Prefix caching with state checkpoints for hybrids is shipped (vLLM block-grid, SGLang MAMBA component, TRT-LLM per docs, llama.cpp checkpoints) and has a better research variant (Tail-Replay, sparse checkpointing).
- Still open (my assessment; I found no paper claiming them, but this is an absence-of-evidence judgement): (1) structure/graph-guided choice of repair positions for hybrids (LinearKV accepts any selector, evaluated only with generic ones); (2) content-aware boundaries and incremental re-encode on edit for recurrent state (the chain dependence means edit invalidates all later composed state unless operators are cached, as in HYPIC; edit-case not verified in HYPIC); (3) MoE routing drift under isolated encoding; (4) validation on Qwen3.8-Flash-Next specifically (architecture not confirmed; Qwen3.8-27B is 3:1 GDN:full); (5) HYPIC vs LinearKV head-to-head, and exactness/error growth with many chunks (LinearKV reports exact composition collapsing on Mamba-2; PRECOG averaging has no bound). Caveat: the three hybrid-PIC papers are all weeks to months old; independent replication UNVERIFIED.
- Implication for INCEPTION section 3 gate: this changes the plan (CacheBlend baseline is insufficient for a GDN hybrid; HYPIC and LinearKV become the primary baselines).

## Runtime-support table (as of 2026-10-31)

| Runtime | Hybrid prefix cache (GDN/Mamba) | Non-prefix / position-independent reuse | Hybrid PIC | Status |
|---|---|---|---|---|
| vLLM | Yes, block-aligned; finer checkpoints optional/off by default; GDN sub-block RFC open | None native (APC prefix only per docs) | No | VERIFIED (docs, RFC) |
| SGLang | Yes, Unified Radix Cache MAMBA component; Qwen3-Next/3.5/3.8 flags | None native in mainline (blog mentions none) | Only via HYPIC fork | VERIFIED |
| llama.cpp | Checkpoint-based (`--ctx-checkpoints`), frequent full reprocess reports | Nothing found (no search hit for CacheBlend/PIC in upstream) | No | PARTLY VERIFIED; absence UNVERIFIED |
| LMCache | Not mentioned in docs | Yes, CacheBlend (vLLM); V1 connector bug open (#3238); in-process mode deprecated, MP mode | No | VERIFIED docs + issue |
| TensorRT-LLM | Documented hybrid Mamba block reuse (Qwen3-Next) | None found; semantic-reuse RFC only | No | UNVERIFIED (search summary) |
| HYPIC (SGLang fork) | inherits | Yes, segment PIC with `<<PIC_SEP>>` | Yes (Qwen3.5 MoE, Ring-linear-2.0) | VERIFIED; research-grade |
