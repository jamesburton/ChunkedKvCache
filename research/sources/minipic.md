# MiniPIC: Flexible Position-Independent Caching in <100 LOC (arXiv 2606.13126)

- URL: https://arxiv.org/abs/2606.13126 (HTML read: https://arxiv.org/html/2606.13126)
- Authors: Nathan Ordonez, Thomas Parnell (IBM Research). 11 Jun 2026, arXiv. 13 pp.
- Code: https://github.com/IBM/vllm (MiniPIC from commit 6631ff3). The sweep missed this link; it is in the paper body.
- Status: **VERIFIED-FULLTEXT**

## Method
- Stores **unrotated K** in the KV cache and applies RoPE inside attention with per-request logical positions.
- Three token-level primitives: block-aligned padding, span separator (SSep), prompt depend (PDep). These reproduce Block-Attention, EPIC and Prompt Cache within one vLLM instance and work with CPU offload.

## Key numbers
- 2WikiMQA: 48.01 vs 32.21 samples/s (+49%). Cached-span TTFT is up to two orders of magnitude lower. Worst-case overhead with PIC disabled is 5.7%. 78 LOC of core change.
- Only one model (Tulu3-block-ft, Llama-3-8B-shaped). **No accuracy metrics.** No code-file workload, though code files are named as a span type. RoPE-only: ALiBi/NoPE would need different handling; hybrids are not addressed.

## For our plan
- An engine-design reference for dotLLM. Caching unrotated K lets a chunk sit at any position with no re-rotation pass, and RoPE is applied at attention time. This bears on the content-addressed key: position parameters drop out of the key if K is stored unrotated.
- It says nothing about quality, so it is not a selector baseline.
