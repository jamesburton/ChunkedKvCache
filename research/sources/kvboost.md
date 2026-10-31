# KVBoost: Chunk-Level KV Reuse with Deviation-Guided Recomputation (arXiv 2608.21362)

- URL: https://arxiv.org/abs/2608.21362
- Author: Srihari Unnikrishnan (sole author). The page says submitted 21 May 2026, which does not fit an 2608 ID; treat the date with caution. No code link.
- Status: **VERIFIED-ABSTRACT**

## Claims
- Qwen2.5-3B, 1,000 bug-localisation samples: TTFT 142.4 ms vs 639.1 ms (4.49x); accuracy 99.2% vs 99.1%; 16% better than prefix caching.
- Dual-hash keys (prefix and content); SelectiveRecompute (boundary) and CacheBlendRecompute repairs; int8/int4 KV; importance-weighted eviction.
- "Adaptive chunk boundary splitting" is not explained in the abstract. No AST or function boundaries are stated, and no incremental re-encode.

## For our plan
- The only verified chunk-reuse paper evaluated on a code task, but on a near-ceiling task (99% accuracy) with a 3B model and one author. It does not test cross-chunk dependence hard enough to count against our E4 claim.
- Cite it as related work. Its dual hash scheme is relevant to the Phase S store key.
