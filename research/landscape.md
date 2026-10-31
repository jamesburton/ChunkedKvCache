# Landscape: chunk-level KV reuse (Step 0 output)

Date: 2026-10-31. Inputs: three sweeps (`sources/sweep-a-code-aware.md`, `sweep-b-layer-moe.md`, `sweep-c-recurrent-runtimes.md`), the starting list in `INCEPTION.md` section 2, and a primary-source verification pass. Each verified paper has a note in `sources/<slug>.md`.

**Status labels**
- **FULLTEXT**: abstract and method/results read this session (note in `sources/`).
- **FULLTEXT-partial**: most of the HTML read; the unread part is noted.
- **ABSTRACT**: abstract or landing page read this session.
- **SWEEP-ABS**: a sweep agent read the abstract page today; not re-read here.
- **ID-ONLY**: arXiv ID and title confirmed through the arXiv API (export.arxiv.org) today. Numbers are not re-checked; any number shown is taken from INCEPTION or a sweep and is marked "(unchk)".
- **UNVERIFIED**: snippet or secondary source only.

Code column: a URL where one is confirmed, "no" when the read page gives none, "n/c" when not checked.

## Corrections to earlier notes (sweeps, spec section 9)

1. **CacheClip does not say CacheBlend's picks cluster at chunk starts.** Its critique is that early-layer selection misses deep-layer dependencies. The chunk-start clustering finding is from 2603.20218. Spec section 9 and sweep B should be read accordingly.
2. **Priming section 7.1 merges recurrent states by averaging ("souping") by default.** PICASO-weighted fusion is the alternative. The GDN "dense transition matrices" detail is a heading only; I did not read the Appendix E body.
3. **Code links the sweeps missed:**
   - MiniPIC: https://github.com/IBM/vllm (commit 6631ff3)
   - EPIC: https://github.com/DerekHJH/epic
   - Boxoffice: https://github.com/boxoffice1280/boxoffice1280
4. **HYPIC's repo** (https://github.com/redai-infra/HYPIC) exists per sweep C, but the paper does not link it.
5. **CodeComp is not a uniform win.** SnapKV beats it on Qwen3-8B at cap 0.4 and on Qwen-Coder SWE-bench.
6. **KV Packet's FLOPs claim is internally inconsistent** (about 4 vs 5-6 orders of magnitude), and the text gives no numeric CacheBlend/EPIC comparison.
7. **The headline speedups use different baselines and are not comparable:**
   - LinearKV: 0.46x of **full prefill**.
   - HYPIC: 3.25x vs **prefix cache**.
   - KV Packet: the baseline for its TTFT speedups is not named.
8. **LinearKV names its models:**
   - Granite-4.0-H-Tiny (Mamba-2)
   - OLMo-Hybrid-7B (GDN)
   - Qwen3.6-27B (GDN; 16 full-attention + 48 GDN layers, a 3:1 ratio)

## 1. Reference table

### 1a. Training-free chunk reuse / selective recompute (dense transformers)

| Paper | Year | Venue | Link | Method class | Reported speedup / quality | Code | Status |
|---|---|---|---|---|---|---|---|
| CacheBlend | 2024 | EuroSys '25 (venue not on arXiv page) | https://arxiv.org/abs/2405.16444 | Selective recompute of high-deviation tokens with layer-wise gradual filtering, ~15% | TTFT 2.2-3.3x, throughput 2.8-5x; loss "within 0.02" F1. 2603.20218 finds it 7-18% below full prefill | https://github.com/LMCache/LMCache | FULLTEXT |
| EPIC (LegoLink) | 2024 | arXiv | https://arxiv.org/abs/2410.15332 | Static recompute of the first k tokens per chunk (k=16); LegoLink-0 uses a dummy prefix | Up to 8x TTFT / 7x throughput; LegoLink-2 accuracy drop 0-7% | https://github.com/DerekHJH/epic | FULLTEXT |
| ProphetKV | 2026 | arXiv | https://arxiv.org/abs/2602.02579 | Query-attention relevance averaged over layers; fixed token set | 20% recompute keeps 96-101% of full; +8.8-24.9% RULER, +18.6-50.9% LongBench vs CacheBlend/EPIC; TTFT 5.23 s full vs 1.13 s at 16K (Llama-3-8B, H100; ratio derived from Table 2) | no | FULLTEXT |
| CacheClip | 2025 | arXiv | https://arxiv.org/abs/2510.10129 | Aux small LLM, last-layer attention selects; shared prefix; contiguous grouping | 20%: 85.2% NIAH / 91.1% LongBench of full; up to 3.33x prefill | no | FULLTEXT |
| SpecCache | 2026 | ACL 2026 (long) | https://aclanthology.org/2026.acl-long.859/ | Draft-model deep-layer hidden-state norms select | TTFT 2.17-3.95x, throughput 2.7-5.2x vs full recompute; "negligible" loss | no | ABSTRACT |
| RelaxKV | 2026 | arXiv | https://arxiv.org/abs/2609.33503 | Query-guided, layer-specific repair targets + restricted recompute context | Beats ProphetKV at 15% on LongBench across 4 models | no | ABSTRACT |
| A^3 attention-aware fusion | 2025 | arXiv | https://arxiv.org/abs/2511.17560 | Question-relevance-aware chunk fusion | ~2x TTFT | no | SWEEP-ABS |
| KVBoost | 2026 | arXiv (single author) | https://arxiv.org/abs/2608.21362 | CacheBlend-style + boundary recompute; dual hash; adaptive boundaries | Qwen2.5-3B bug localisation: 4.49x TTFT, 99.2 vs 99.1 acc | no | ABSTRACT |
| Kamera | 2026 | arXiv | https://arxiv.org/abs/2606.23581 | Training-free low-rank per-chunk patch + RoPE re-rotation (multimodal) | Residual is "low-rank ... concentrated in deep layers"; recovers full accuracy on cross-chunk binding | no | ABSTRACT |
| VLCache | 2025 | arXiv | https://arxiv.org/abs/2512.12977 | Layer-aware recompute for reused vision KV | 2-5% tokens recomputed, 1.2-16x TTFT, parity with full | no | ABSTRACT |
| Contiguity, Not Importance | 2026 | arXiv | https://arxiv.org/abs/2609.17983 | Budgeted repair after document edits; contiguous edit-local window | EditLocal K=32 recovers >=0.94 margin; 13-21x faster than re-prefill; fails when dependent text is >=250 tokens away | no | FULLTEXT |
| Cache-Craft | 2025 | SIGMOD (per INCEPTION, unchk) | https://arxiv.org/abs/2502.15734 | Chunk-cache management for RAG | (unchk) | n/c | ID-ONLY |
| SamKV (sparse attention across multi-context KV) | 2025 | arXiv | https://arxiv.org/abs/2508.11661 | Sparse attention over multiple cached contexts | (unchk) | n/c | ID-ONLY |
| CacheRepair | 2026 | arXiv | https://arxiv.org/abs/2609.35139 | Learned repair of cross-chunk context | (unchk) | n/c | ID-ONLY |
| CacheSmith | 2026 | arXiv | https://arxiv.org/abs/2610.18925 | Adaptive KV reuse configuration under SLOs | (unchk) | n/c | ID-ONLY |
| ATTUNER | 2026 | arXiv | https://arxiv.org/abs/2609.36722 | Recompute-free agentic context reuse (query-side) | (unchk) | n/c | ID-ONLY |
| RedKnot | 2026 | arXiv | https://arxiv.org/abs/2606.06256 | Head-aware KV reuse + SegPagedAttention | (unchk) | n/c | ID-ONLY |
| CacheWeaver | 2026 | arXiv | https://arxiv.org/abs/2606.19667 | Cache-aware evidence ordering for RAG | (unchk) | n/c | ID-ONLY |
| Models Take Notes at Prefill | 2026 | arXiv | https://arxiv.org/abs/2606.17107 | Editable/composable KV (append-only edits) | (unchk; snippet: up to 14.9x latency) | n/c | ID-ONLY |
| HijackKV | 2026 | arXiv | https://arxiv.org/abs/2607.19957 | Attack on PIC (security) | n/a | n/c | ID-ONLY |
| CachePrune | 2026 | arXiv | https://arxiv.org/abs/2605.23640 | Privacy-aware KV sharing | n/a | n/c | ID-ONLY |
| Prompt Cache | 2023 | arXiv | https://arxiv.org/abs/2311.04934 | Schema-defined reusable prompt modules | (unchk) | n/c | ID-ONLY |
| APE | 2025 | ICLR 2025 (unchk) | https://arxiv.org/abs/2502.05431 | Training-free parallel encoding with attention scaling | (unchk; sweep snippet ~98% RAG) | https://github.com/Infini-AI-Lab/APE (snippet) | ID-ONLY |
| RAGCache | 2024 | arXiv | https://arxiv.org/abs/2404.12457 | Knowledge-tree KV cache for RAG (prefix-tree) | (unchk) | n/c | ID-ONLY |
| CacheGen | 2023 | arXiv | https://arxiv.org/abs/2310.07240 | KV compression/streaming (out of scope, spec section 3) | (unchk) | n/c | ID-ONLY |

### 1b. Trained / fine-tuned chunk independence

| Paper | Year | Venue | Link | Method class | Reported speedup / quality | Code | Status |
|---|---|---|---|---|---|---|---|
| KV Packet | 2026 | NeurIPS 2026 | https://arxiv.org/abs/2604.13226 | 8+8 soft-token adapters by self-distillation; zero recompute | HotpotQA F1 0.423 vs 0.460 full; TTFT 1.36-19.45x; Llama-3.1-8B, Qwen3-4B | https://github.com/ChuangtaoChen-TUM/KVPacket | FULLTEXT |
| SemPIC | 2026 | arXiv | https://arxiv.org/abs/2607.28069 | LoRA "writer" compiles document KV | micro-F1 0.60 vs 0.53 (KV Packet), 0.62 full | https://github.com/jn12-29/SemPIC | SWEEP-ABS |
| Fine-tune concat-aware model or recompute? Both | 2026 | arXiv | https://arxiv.org/abs/2609.09768 | Concatenation-aware fine-tune + selective recompute | (unchk) | n/c | ID-ONLY |
| Block-Attention | 2024 | arXiv | https://arxiv.org/abs/2409.15355 | Block-diagonal fine-tune | (unchk) | n/c | ID-ONLY |
| Block-attention generalisation (auto segmentation + distillation) | 2026 | arXiv | https://arxiv.org/abs/2605.15913 | Learned segmenter + block distillation | Near full-attention quality | no | SWEEP-ABS |
| TurboRAG | 2024 | arXiv | https://arxiv.org/abs/2410.07590 | Offline chunk KV + fine-tune with reset positions | (unchk) | n/c | ID-ONLY |
| KVLink | 2025 | arXiv | https://arxiv.org/abs/2502.16002 | Learned link tokens | (unchk) | n/c | ID-ONLY |
| Parallel Context Windows | 2022 | arXiv | https://arxiv.org/abs/2212.10947 | Parallel windows with shared positions | (unchk) | n/c | ID-ONLY |
| Cartridges | 2025 | ICLR 2026 (sweep, unchk) | https://arxiv.org/abs/2506.06266 | Per-corpus trained KV via self-study | (sweep snippet: 38.6x memory, unchk) | https://github.com/HazyResearch/cartridges (sweep) | ID-ONLY |

### 1c. Compression / encoder-split / memory (INCEPTION 2.4-2.5; mostly out of scope per spec section 3)

| Paper | Year | Venue | Link | Method class | Reported speedup / quality | Code | Status |
|---|---|---|---|---|---|---|---|
| FiD | 2020 | arXiv | https://arxiv.org/abs/2007.01282 | Per-passage encode + decoder fusion | (unchk) | n/c | ID-ONLY |
| CEPE | 2024 | arXiv | https://arxiv.org/abs/2402.16617 | Small parallel encoder + cross-attention | (unchk) | n/c | ID-ONLY |
| REFRAG | 2025 | arXiv | https://arxiv.org/abs/2509.01092 | Compressed chunk embeddings, selective expansion | (INCEPTION: ~30x TTFT, unchk) | n/c | ID-ONLY |
| xRAG | 2024 | arXiv | https://arxiv.org/abs/2405.13792 | One-token document embedding | (unchk) | n/c | ID-ONLY |
| Gist tokens | 2023 | arXiv | https://arxiv.org/abs/2304.08467 | Prompt compression | (unchk) | n/c | ID-ONLY |
| ICAE | 2023 | arXiv | https://arxiv.org/abs/2307.06945 | In-context autoencoder | (unchk) | n/c | ID-ONLY |
| AutoCompressors | 2023 | arXiv | https://arxiv.org/abs/2305.14788 | Summary vectors | (unchk) | n/c | ID-ONLY |
| 500xCompressor | 2024 | arXiv | https://arxiv.org/abs/2408.03094 | Prompt compression | (unchk) | n/c | ID-ONLY |
| Memory^3 | 2024 | arXiv | https://arxiv.org/abs/2407.01178 | Explicit sparse KV memory | (unchk) | n/c | ID-ONLY |
| KBLaM | 2024 | arXiv | https://arxiv.org/abs/2410.10450 | Knowledge tokens, rectangular attention | (unchk) | n/c | ID-ONLY |
| CodeComp | 2026 | arXiv | https://arxiv.org/abs/2604.10235 | Code-Property-Graph-guided KV eviction (single context) | Mixed: e.g. Llama3-8B cap 0.4 0.36 vs SnapKV 0.33; loses on Qwen3-8B cap 0.4 and Qwen-Coder SWE-bench | no | FULLTEXT |
| GraphKV | 2025 | EMNLP 2025 | https://aclanthology.org/2025.emnlp-main.1112/ | Token-graph KV eviction (not a program graph) | (unchk) | n/c | UNVERIFIED |
| MoEZip | 2026 | NeurIPS 2026 | https://arxiv.org/abs/2610.30206 | Routing-aware KV eviction for MoE | +24 LongBench / +20 RULER at 10% retention | no | ABSTRACT |

### 1d. Layer-level prefill reduction, routing, cross-model reuse

| Paper | Year | Venue | Link | Method class | Reported speedup / quality | Code | Status |
|---|---|---|---|---|---|---|---|
| Experimental study of CLC reuse strategies | 2026 | arXiv | https://arxiv.org/abs/2603.20218 | Empirical study + PSR combination; per-layer dK analysis | CacheBlend r=15% is 7-18% below full; PSR up to +5% abs; selection is layer-dynamic (8-20% of tokens constant across layers) | no | FULLTEXT |
| Evaluating accuracy of KV reuse (Boxoffice) | 2026 | arXiv | https://arxiv.org/abs/2609.31415 | Evaluation methodology + dataset generator | CacheBlend 2WikiMQA 0.87 to 0.52 after filtering; LMCache 0.00 on flipped queries | https://github.com/boxoffice1280/boxoffice1280 | FULLTEXT-partial |
| KV-Repurpose testbed | 2026 | arXiv | https://arxiv.org/abs/2610.13060 | vLLM non-prefix reuse testbed | 63.9% token hit vs 3.3% prefix | https://github.com/taiga333/eval-kv-repurpose | SWEEP-ABS |
| DroidSpeak | 2024 | arXiv | https://arxiv.org/abs/2411.02820 | Cross-LLM KV reuse; recompute a few layers | ~3.1x prefill, 4x throughput | no | ABSTRACT |
| Layer-wise MoE routing locality (code gen) | 2026 | arXiv | https://arxiv.org/abs/2604.17182 | Routing overlap across decode branches, Qwen3.5-35B-A3B | Jaccard 0.649 same-token vs 0.175; context dips at L14-20 | no | ABSTRACT |
| ELDR | 2026 | arXiv | https://arxiv.org/abs/2607.00466 | Expert-routing signatures per KV block (serving) | (unchk) | n/c | ID-ONLY |
| Elastic-Cache (diffusion LLMs) | 2025 | arXiv | https://arxiv.org/abs/2510.14973 | Refresh only deep layers past a boundary (dLLM decode) | (unchk) | n/c | ID-ONLY |
| SwiftKV | 2024 | arXiv | https://arxiv.org/abs/2410.03960 | Later-layer KV from earlier layer + distillation | 25-50% prefill compute cut | https://github.com/snowflakedb/arctictraining (sweep) | SWEEP-ABS |
| HCache | 2024 | EuroSys '25 (sweep, unchk) | https://arxiv.org/abs/2410.05004 | Hidden-state store, KV by projection | (sweep: up to 5.7x restore, unchk) | n/c | ID-ONLY |
| YOCO | 2024 | arXiv | https://arxiv.org/abs/2405.05254 | Decoder-decoder, single global KV | (unchk) | n/c | ID-ONLY |
| KV Prediction | 2024 | arXiv | https://arxiv.org/abs/2410.08391 | Aux model predicts base KV | (unchk) | n/c | ID-ONLY |
| Cross-Layer Attention | 2024 | arXiv | https://arxiv.org/abs/2405.12981 | Share KV across layers | (unchk) | n/c | ID-ONLY |
| KVSharer | 2024 | arXiv | https://arxiv.org/abs/2410.18517 | Layer-wise dissimilar KV sharing | (unchk) | n/c | ID-ONLY |
| LayerSkip | 2024 | arXiv | https://arxiv.org/abs/2404.16710 | Early exit + self-speculation | (unchk) | n/c | ID-ONLY |

### 1e. Recurrent / hybrid (GDN, Mamba) state reuse

| Paper | Year | Venue | Link | Method class | Reported speedup / quality | Code | Status |
|---|---|---|---|---|---|---|---|
| HYPIC | 2026 | arXiv | https://arxiv.org/abs/2607.01299 | Hybrid PIC: cached transition operator + zero-start state per segment; 8-token seam for full-attention layers | TTFT 3.25x vs prefix cache; 1.71 pts below full recompute; Qwen3.5-35B/122B MoE, Ring-linear-2.0 | https://github.com/redai-infra/HYPIC (per sweep C; not linked in paper) | FULLTEXT-partial |
| LinearKV | 2026 | arXiv | https://arxiv.org/abs/2608.11231 | Hybrid PIC: one cached state per linear layer + any selector | GDN up to 92% of full; Mamba-2 86.8% vs 46.6% for exact composition; TTFT 0.46-0.62x full | no | FULLTEXT |
| Priming (section 7.1 state composition) | 2026 | arXiv | https://arxiv.org/abs/2605.08301 | Independent chunk prefill; KV concat + averaged (souped) recurrent states | GDN-8B NIAH 256K/512K: 66.3/43.0 vs 30.1/0.0 standard | no URL on page | FULLTEXT-partial |
| Tail-Replay | 2026 | arXiv | https://arxiv.org/abs/2608.30310 | Prefix caching for GDN hybrids; replay a short suffix instead of checkpoints | 5-10% replay keeps 92.8-99.9% quality; TTFT 9.1-14.3x at 32K | no | SWEEP-ABS |
| Sparse Prefix Caching for hybrids | 2026 | arXiv | https://arxiv.org/abs/2605.05219 | Recurrent checkpoints at DP-optimal positions (prefix only) | (sweep) | no | SWEEP-ABS |
| PICASO | 2025 | ICLR 2025 (sweep) | https://arxiv.org/abs/2502.17605 | Permutation-invariant SSM state composition | ~5.4x speedup | n/c | SWEEP-ABS |
| Document souping (SSMs) | 2025 | arXiv | https://arxiv.org/abs/2505.24033 | Average independently encoded Mamba2 states | Competitive on multi-hop QA | n/c | SWEEP-ABS |
| PRECOG / SSM state injection | 2026 | arXiv | https://arxiv.org/abs/2608.02560 | Offline per-chunk SSM states, weighted average | top-3 trails top-1 by ~1.6 F1 | n/c | SWEEP-ABS |
| EmbeddingRWKV | 2026 | arXiv | https://arxiv.org/abs/2601.07861 | Reusable RWKV states for retrieval | (unchk) | n/c | ID-ONLY |
| StateFlow | 2026 | arXiv | https://arxiv.org/abs/2608.06838 | Pipeline parallelism for linear recurrence (training) | (unchk) | n/c | ID-ONLY |
| Gated DeltaNet | 2024 | arXiv | https://arxiv.org/abs/2412.06464 | GDN architecture | n/a | n/c | ID-ONLY |
| DeltaNet chunkwise parallel | 2024 | arXiv | https://arxiv.org/abs/2406.06484 | WY chunkwise-parallel delta rule | n/a | n/c | ID-ONLY |

### 1f. Systems / position-independent caching engines

| Paper | Year | Venue | Link | Method class | Reported speedup / quality | Code | Status |
|---|---|---|---|---|---|---|---|
| MiniPIC (IBM) | 2026 | arXiv | https://arxiv.org/abs/2606.13126 | vLLM; unrotated K, RoPE in attention; SSep/PDep primitives | +49% prefill throughput; no accuracy reported | https://github.com/IBM/vllm | FULLTEXT |
| Irminsul | 2026 | arXiv | https://arxiv.org/abs/2605.05696 | SGLang radix + content-defined chunking + MLA delta-rotation | Recovers up to ~83% of tokens above exact prefix | no | SWEEP-ABS |

### 1g. Architectural relatives (INCEPTION 2.7; decode-time / sparse attention, out of scope)

| Paper | Year | Venue | Link | Method class | Reported speedup / quality | Code | Status |
|---|---|---|---|---|---|---|---|
| Landmark Attention | 2023 | arXiv | https://arxiv.org/abs/2305.16300 | Per-block landmark tokens | (unchk) | n/c | ID-ONLY |
| NSA | 2025 | arXiv | https://arxiv.org/abs/2502.11089 | Native sparse attention | (unchk) | n/c | ID-ONLY |
| MoBA | 2025 | arXiv | https://arxiv.org/abs/2502.13189 | Mixture of block attention | (unchk) | n/c | ID-ONLY |
| Quest | 2024 | arXiv | https://arxiv.org/abs/2406.10774 | Query-aware KV page selection (decode) | (unchk) | n/c | ID-ONLY |
| RetrievalAttention | 2024 | arXiv | https://arxiv.org/abs/2409.10516 | Vector-retrieval attention (decode) | (unchk) | n/c | ID-ONLY |
| MagicPIG | 2024 | arXiv | https://arxiv.org/abs/2410.16179 | LSH sampling (decode) | (unchk) | n/c | ID-ONLY |
| InfiniGen | 2024 | arXiv | https://arxiv.org/abs/2406.19707 | Dynamic KV offload (decode) | (unchk) | n/c | ID-ONLY |

Not found or not given an ID this session: DeepSeek Sparse Attention (V3.2). Exact-prefix systems (vLLM APC, SGLang RadixAttention) are in the tooling table (section 4).

## 2. Verdicts on the hypothesised gaps

| Gap | Verdict | Evidence (citations) | Queries if the result is a negative |
|---|---|---|---|
| **G1. Structure-aware recompute selection** (choose recompute tokens or link sites from a static reference graph) | **open** | Nearest work does something different. **CodeComp** (https://arxiv.org/abs/2604.10235) uses a program graph for *compression* in a single context, with mixed wins. **Mesh-LLM #1653** (https://github.com/Mesh-LLM/mesh-llm/issues/1653) is an unimplemented proposal. **Contiguity** (https://arxiv.org/abs/2609.17983) tested a naive "Structural" selector (delimiter tokens), which scored 0.008-0.126 margin; this warns that a structural selector must use graph *roles*, not syntax delimiters. **LinearKV** (https://arxiv.org/abs/2608.11231) accepts any selector but tested only CacheBlend/EPIC/ProphetKV. All verified selectors (CacheBlend, EPIC, ProphetKV, CacheClip, SpecCache, RelaxKV) are deviation-, position- or query/attention-based. | Sweep A queries 1, 2, 5, 9, 11, 13 (see sweep-a file); plus today: "reference graph guided selective recomputation KV cache code repository position-independent caching symbol definitions call sites". Searched, none found doing graph-guided recompute selection. |
| **G2. Content-aware chunk boundaries + incremental re-encode on edit** | **partly covered** (generic boundaries and edit repair exist; code/AST boundaries with dependency-aware invalidation are open) | Boundaries: KVBoost "adaptive boundary splitting" (https://arxiv.org/abs/2608.21362, method unstated); Irminsul byte-level CDC (https://arxiv.org/abs/2605.05696); learned segmentation (https://arxiv.org/abs/2605.15913). Edit repair: **Contiguity** (https://arxiv.org/abs/2609.17983) shows that recomputing a contiguous window after the edit recovers >=0.94 margin, but recovers only 0.01-0.09 when the dependent text is >=250 tokens downstream. In code, callers are usually non-adjacent, so dependency-targeted repair is the open part. Models Take Notes (https://arxiv.org/abs/2606.17107, ID-ONLY) covers append-only structured edits. HYPIC's per-segment operators would allow cheap segment replacement in linear layers, but the paper does not test edits. | Sweep A queries 3, 7, 12; plus today: "incremental KV cache update after source file edit coding agent stale KV cache repair chunk invalidation 2026". No AST/function-boundary chunk cache with edit invalidation found. |
| **G3a. Per-layer deviation profiling (dense)** | **partly covered** | **2603.20218** (https://arxiv.org/abs/2603.20218, FULLTEXT): early-layer picks are at chunk starts, selection is layer-dynamic, and 8-20% of tokens are constant across layers. **CacheClip** (https://arxiv.org/abs/2510.10129): first-vs-last-layer Jaccard 0.11-0.23. **SpecCache** (https://aclanthology.org/2026.acl-long.859/): "deviations larger in deep layers". **Kamera** (https://arxiv.org/abs/2606.23581): residue is low-rank and in deep layers. **ProphetKV** App. D. Missing: deviation broken down by token type or graph role, and a per-layer top-k capture curve. | n/a (covered) |
| **G3b. Layer-tiered recompute (freeze early, recompute deep on k%) at equal FLOPs** | **partly covered**; the exact equal-FLOPs comparison was not found | Adjacent: RelaxKV layer-specific targets (https://arxiv.org/abs/2609.33503, ABSTRACT); VLCache layer-aware budgets (https://arxiv.org/abs/2512.12977; which layers get more is UNVERIFIED, one snippet says earlier); DroidSpeak layer band (https://arxiv.org/abs/2411.02820; the chunk adaptation in 2603.20218 did poorly); Elastic-Cache refreshes deep layers only, in diffusion LLMs (https://arxiv.org/abs/2510.14973, ID-ONLY); CacheBlend already narrows the set with depth. Structural caveat: recomputing a token at a deep layer needs its early-layer states, so savings must come from fewer tokens per layer. | Sweep B queries 1, 3, 4, 7; plus today: "layer-tiered selective recomputation reuse early layers KV recompute only deep layers chunk cache equal FLOPs 2026 arXiv". Searched, none found with an equal-FLOPs comparison. |
| **G3c. MoE routing drift, isolated vs full-context encoding** | **open** | Adjacent only. **MoEZip** (https://arxiv.org/abs/2610.30206): eviction changes routing. **2604.17182** (https://arxiv.org/abs/2604.17182): routing is context-dependent in middle layers of Qwen3.5-35B-A3B, but for decode branches. **HYPIC** ran Qwen3.5 MoE hybrids and did not measure routing. ELDR (https://arxiv.org/abs/2607.00466) is serving-side. | Sweep B queries 2, 6; plus today: "MoE expert routing agreement chunk KV cache reuse position-independent caching isolated encoding mixture-of-experts drift". Searched, none found. |
| **G4. Recurrent (GDN/SSM) state reuse across chunks** | **partly covered**; the basic form is **done** | **HYPIC** (https://arxiv.org/abs/2607.01299): operator composition + seam, within 1.71 pts of full. **LinearKV** (https://arxiv.org/abs/2608.11231): a single cached state is as good as composition on GDN, and composition collapses on Mamba-2. **Priming 7.1** (https://arxiv.org/abs/2605.08301): averaged states. **PICASO** (https://arxiv.org/abs/2502.17605), **souping** (https://arxiv.org/abs/2505.24033), **PRECOG** (https://arxiv.org/abs/2608.02560) for pure SSMs. Prefix-only: **Tail-Replay** (https://arxiv.org/abs/2608.30310), **Sparse Prefix Caching** (https://arxiv.org/abs/2605.05219). Still open: graph-guided repair positions on hybrids, edit/incremental for recurrent state, MoE drift on hybrid MoE, a HYPIC vs LinearKV head-to-head on one model, error growth with many chunks, and the Flash-Next layer split. | n/a (covered); sweep C queries 1-10 |

## 3. Recommended pivots

The core novelty (G1, structure-aware selection) and E6 (MoE drift) remain open, so no wholesale pivot is needed. G4 is no longer an open research question in its basic form, so **Phase T changes from "invent recurrent reuse" to "reproduce and compare HYPIC/LinearKV on the target, and add the open pieces"**. The baselines need upgrading.

### 3.1 Phase P (dense proof model) baselines: change
Keep:
- Full prefill, naive concatenation, prefix cache (E1).
- **CacheBlend** with gradual filtering, r in {5,10,15,20}% (the community reference, LMCache-compatible numbers).
- **EPIC/LegoLink first-k** (k=16; also LegoLink-0 dummy prefix). This is the static, ~0-cost comparator, and the direct rival to a static graph selector.

Make concrete, or add:
- The "query-relevance selector" becomes **ProphetKV** (query-to-context attention column sums averaged over layers, one token set). It is simple and the strongest verified training-free selector with a full method description.
- **PSR** (2603.20218: Link0 prefix + CacheBlend selection + APE scaling) as the strongest combined training-free bar.
- **Contiguous-run variant** of any selector (CacheClip-style grouping, w=8). Both Contiguity and CacheClip show scattered positions underperform.

Stretch only (need an auxiliary or draft model, or no code):
- CacheClip, SpecCache, RelaxKV.

Trained (E9 stretch):
- KV Packet has code and was evaluated on Qwen3-4B-Instruct.

### 3.2 Phase T (recurrent hybrid target) baselines: change
CacheBlend alone is not applicable to the GDN layers. Use:
- **LinearKV last-block init + {EPIC, CacheBlend, ProphetKV}** as the primary baseline. It is cheapest, it matches composition on GDN, and the Phase P selectors carry over unchanged.
- **HYPIC operator composition + 8-token seam** as the comparison, and as the enabler for cheap segment replacement on edit.
- **Averaged ("souped") states** (Priming 7.1) as a cheap lower bar.
- **Add E6 on the hybrid MoE.** No hybrid-PIC paper measured routing agreement; 2604.17182 points at the middle layers.

### 3.3 Evaluation: change
- Adopt the **Boxoffice/2609.31415 filtering** for all QA. Drop B0, NC and LI queries; report norm-F1 and the filtered/unfiltered ratio. Include Boxoffice-generated hard reuse patterns.
- For code tasks, drop items full prefill fails and items answerable with no context.
- E7 gains the **EditLocal(K=32) baseline** and an **edit-to-dependent distance axis**: 0, under 250, at least 250 tokens, and cross-file.
- E6 metric: per-layer top-k expert Jaccard, isolated vs full context (as in 2604.17182), correlated with quality loss.

### 3.4 Proposed edits to the design spec (listed, NOT applied)

**Section 7, Phase R:** mark it done; point to `research/landscape.md`.

**Section 7, Phase P:**
- Replace "CacheBlend-style deviation selection, EPIC-style first-k, a query-relevance selector" with "CacheBlend (gradual filtering), EPIC/LegoLink first-k (k=16) and LegoLink-0, ProphetKV (query-relevance), and PSR (2603.20218), each also run as contiguous runs; CacheClip/SpecCache/RelaxKV as stretch".
- Add: "E3 extends 2603.20218: add token-type and graph-role breakdown and per-layer top-k capture; do not claim per-layer profiling itself as novel."
- Add: "E5 compares layer-tiered against uniform selection at equal FLOPs (no prior equal-FLOPs comparison found)."
- Add: "E7 uses EditLocal(K=32) from 2609.17983 as a baseline and varies the edit-to-dependent distance."

**Section 7, Phase T:**
- Reframe as "Reproduce LinearKV (last-block init) and HYPIC (operator composition + seam) on the target, with the Phase P selectors. Then test the open pieces: graph-guided repair positions on hybrids, segment replacement on edit using cached operators, MoE routing drift (E6), and error growth with chunk count."
- Note: "LinearKV shows composition is not needed on GDN, but collapses on Mamba-2; confirm on the target's GDN layers."

**Section 7, Phase S:**
- Note MiniPIC's unrotated-K storage, which removes the position parameters from the cache key.
- Note the HYPIC per-segment operator size (32 KB per head per layer, fp16, dk=128) as the storage cost of composition, if adopted.

**Section 7, evaluation data:** add "Boxoffice generator for hard reuse cases; meaningful-subset filtering per 2609.31415".

**Section 8:**
- E4: "...matches or beats the best baseline selector (ProphetKV or PSR at equal budget, not only CacheBlend)...", and add "...and beats EPIC first-k at equal static cost".
- Recurrent criterion: change "a written answer on what is reusable for recurrent layers" to "measured LinearKV vs HYPIC on the target, plus at least one open piece (graph-guided repair or edit-replacement) measured".
- Quality metric: "norm-F1 on the meaningful subset (2609.31415) for QA; exact-match/execution for code".
- Add: "E6 reports per-layer routing agreement on at least one MoE hybrid (e.g. Qwen3.5-35B-A3B class) if hardware allows."

**Section 9:** replace with a pointer to `research/landscape.md`, and correct the CacheClip attribution (correction 1 above).

**Section 5:** note that Qwen3.6-27B (LinearKV) and Qwen3.8-27B (sweep C) are both 3:1 GDN:full attention. The Flash-Next split is still unverified.

## 4. Tooling support (as of 2026-10-31)

| Runtime / tool | Link | Hybrid prefix cache (GDN/Mamba) | Non-prefix / PIC reuse | Hybrid PIC | Status |
|---|---|---|---|---|---|
| vLLM (mainline) | https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/ | Yes, block-aligned; finer Mamba checkpoints optional and off by default; GDN sub-block RFC open (https://github.com/vllm-project/vllm/issues/64267) | None native (APC is prefix-only) | No | VERIFIED by sweep C |
| MiniPIC (IBM vLLM fork) | https://github.com/IBM/vllm | Not addressed | Yes: Block-Attention/EPIC/Prompt-Cache primitives; RoPE models only | No | FULLTEXT (paper) |
| SGLang (mainline) | https://www.lmsys.org/blog/2026-08-11-unified-radix-cache/ | Yes, Unified Radix Cache MAMBA component (Qwen3-Next/3.5/3.8, Kimi KDA) | None in mainline | Only via the HYPIC fork | VERIFIED by sweep C |
| HYPIC (SGLang v0.5.14 fork) | https://github.com/redai-infra/HYPIC | Inherited | Yes, segment PIC with `<<PIC_SEP>>` | Yes (Qwen3.5 MoE, Ring-linear-2.0); needs page-size 1 and no chunked prefill | VERIFIED by sweep C (README); research-grade |
| LMCache | https://docs.lmcache.ai/kv_cache_optimizations/blending.html | Not mentioned | CacheBlend (vLLM); V1 connector non-prefix bug open (https://github.com/LMCache/LMCache/issues/3238) | No | VERIFIED by sweep C |
| EPIC reference code | https://github.com/DerekHJH/epic | No | LegoLink (research code) | No | Link FULLTEXT; repo not inspected |
| KV Packet code | https://github.com/ChuangtaoChen-TUM/KVPacket | No | Trained adapters | No | Link verified; repo not inspected |
| Boxoffice evaluator | https://github.com/boxoffice1280/boxoffice1280 | n/a | Evaluation datasets for reuse | n/a | Link FULLTEXT; repo not inspected |
| TensorRT-LLM | https://nvidia.github.io/TensorRT-LLM/latest/features/kvcache.html | Documented hybrid Mamba block reuse (Qwen3-Next) | None found; semantic-reuse RFC only | No | UNVERIFIED (sweep C search summary) |
| llama.cpp | https://github.com/ggml-org/llama.cpp/issues/21831 | Checkpoints (`--ctx-checkpoints`); frequent full reprocess reported | None found | No | PARTLY VERIFIED (user reports) |
| dotLLM (user fork, `dev`) | https://github.com/jamesburton/dotLLM | Prefix cache and snapshots (per spec section 5, docs only) | None today (spec section 5) | No | Per spec; not code-verified |

Bottom line on tooling: no mainstream runtime ships training-free non-prefix blending that works for both dense and hybrid models. LMCache CacheBlend is the only mainstream implementation, and its vLLM V1 path has an open bug. Hybrid PIC exists only in the HYPIC research fork. Building in dotLLM (spec section 3) remains justified; the reference implementations to read are EPIC, MiniPIC, HYPIC and LMCache's blender.

## 5. Not verified / open items
- SpecCache body: models, benchmarks and head-to-head numbers (abstract only).
- Priming Appendix E (GDN "dense transition matrices") body.
- The last 12% of HYPIC's HTML and the last 30% of Boxoffice's HTML.
- RelaxKV full text, including whether it tests early-layer freezing.
- VLCache's layer allocation direction.
- KVBoost's boundary method.
- All ID-ONLY rows: numbers are not re-checked, including Cartridges, REFRAG, HCache and APE.
- GraphKV (EMNLP 2025): Anthology page not fetched.
- TensorRT-LLM docs not fetched.
- DeepSeek Sparse Attention: no ID pinned.
- Flash-Next (`qwen4exp`) layer split.
