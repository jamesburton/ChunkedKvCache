# HYPIC: Hybrid-Attention LLM Serving with Position-Independent Caching (arXiv 2607.01299)

- URL: https://arxiv.org/abs/2607.01299 (HTML read up to 100K of 114K characters: https://arxiv.org/html/2607.01299)
- Authors: Yifei Liu, Juntong Wu, Yang Liu, Junhao Hu (an EPIC author), et al. v1 1 Jul 2026, v2 12 Jul 2026. arXiv (cs.DC).
- Code: neither the abs page nor the HTML I read links one. Sweep C fetched https://github.com/redai-infra/HYPIC (an SGLang v0.5.14 fork), so the repo exists, but the paper does not link it.
- Status: **VERIFIED-FULLTEXT (partial, ~88% read)**

## Method
- Linear-attention (GDN) layers: each segment caches a cumulative transition operator and a zero-start end state, and segments compose in constant time. For GDN the operator is a dense dk x dk matrix, 32 KB per segment per head per layer (dk=128, fp16).
- Composition is exact for the given inputs: at layer 0 it matches full recompute to 6e-5 relative norm. Deeper layers drift because each segment was prefilled in isolation (deepest linear layer: 8.92% relative L2 on Qwen3.5-35B-A3B).
- Full-attention layers get a seam window of 8 tokens at the start of each interior segment, recomputed with hidden-state propagation. Segment parallelism handles cache misses.

## Key numbers
- Models: Ring-mini-linear-2.0, Ring-flash-linear-2.0, Qwen3.5-35B-A3B, Qwen3.5-122B-A10B. Workloads: HotpotQA, TriviaQA, MultiNews, GovReport, Prod-RAG.
- TTFT is 3.25x lower on average **vs Prefix Cache** (not vs full prefill), and QPS is 1.66x higher. The average gap to full recompute is 1.71 points (Qwen3.5-35B +0.47, 122B -0.56, Ring models about -3.3 to -3.4). Naive addition loses 66.9%.
- No discussion of edits/incremental update, and no MoE routing analysis, even though the Qwen3.5 models are A3B/A10B MoE.

## For our plan
- This is a primary Phase T baseline (operator composition + seam). Of the hybrid-PIC methods, its storage cost per segment is the highest (operator per head per layer).
- Its Qwen3.5 MoE hybrids are the nearest published relatives of the Flash-Next target. Measuring routing agreement on them (E6) is a cheap add that nobody has done.
- Edits: a cached operator per segment makes "replace one segment, recompose" cheap for the linear layers. That supports our incremental re-encode idea but is untested in the paper.
