# CacheClip: Accelerating RAG with Effective KV Cache Reuse (arXiv 2510.10129)

- URL: https://arxiv.org/abs/2510.10129 (HTML v2 read: https://arxiv.org/html/2510.10129v2)
- Authors: Bin Yang, Qiuyu Leng, Jun Zeng, Zhenhua Wu. v1 11 Oct 2025, v2 21 May 2026. arXiv (cs.LG); no venue, no code link.
- Status: **VERIFIED-FULLTEXT**

## Method
- A small auxiliary LLM (SmolLM2-135M or Qwen2.5-0.5B) runs over the context. CacheClip takes query-to-chunk attention from the aux model's **final layer**, averages it over the query, and recomputes the top-k tokens in the primary model.
- A shared prefix removes repeated attention sinks. Sliding-window grouping (w=8, tau=5) makes the selected tokens contiguous. The aux model runs on idle CPU.

## Key numbers
- 20% recompute: "up to 85.2% and 91.1% of full-attention performance on NIAH and LongBench"; +16.1/+12.8 points over CacheBlend/APE on NIAH and +4.5/+4.2 on LongBench.
- Prefill up to 3.33x at 16K (5.641 s full vs 1.695 s). Primary model: Qwen2.5-14B-Instruct.
- Jaccard overlap between the primary model's first-layer and last-layer selections is 0.11-0.23; between the aux last layer and the primary last layer it is 0.28-0.41.

## Correction to earlier sweep / spec section 9
- CacheClip does **not** claim that CacheBlend's picks cluster at chunk starts. Its critique is that early-layer selection misses deep-layer dependencies ("shallow layers primarily capture local syntactic relationships, while deeper layers handle long-range semantic dependencies"). The chunk-start clustering finding comes from 2603.20218.

## For our plan
- Evidence that the selection signal should come from deep layers. This bears on E3/E5 and on how CacheBlend's first-layer probe is configured.
- It needs a same-tokenizer auxiliary model. That is a stretch baseline for dotLLM, not a first one.
- Its contiguity grouping matches the "Contiguity, Not Importance" finding (2609.17983): selected tokens should form runs, not scattered points.
