# DroidSpeak: KV Cache Sharing for Cross-LLM Communication (arXiv 2411.02820)

- URL: https://arxiv.org/abs/2411.02820
- Authors: Yuhan Liu, ..., Junchen Jiang, Shan Lu, Madan Musuvathi, Esha Choukse. v1 5 Nov 2024, v4 14 Jul 2025, arXiv (cs.MA). No code link.
- Status: **VERIFIED-ABSTRACT**

## Claims
- Shares KV across different LLMs of the same architecture. It recomputes "a few layers" and reuses the rest, with layer-wise recompute pipelined against loading.
- Up to 4x throughput and about 3.1x faster prefill; negligible quality loss (F1, Rouge-L, code similarity).
- Layer selection is not described in the abstract. The "layer band" description (reuse up to Ls, recompute to Le, reuse above) comes from 2603.20218.

## For our plan
- A layer-band precedent, but for cross-model reuse, not cross-chunk. 2603.20218's adaptation of it to chunk caching performed poorly ("Dynamic recomputation needs cached cross-attention").
- That is a caution for E5: a contiguous recompute band may lack the cached cross-attention it needs.
