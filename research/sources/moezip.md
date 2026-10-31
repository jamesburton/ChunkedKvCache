# MoEZip: Routing-Aware KV Cache Compression for Sparse MoE LLMs (arXiv 2610.30206)

- URL: https://arxiv.org/abs/2610.30206
- Authors: Minsang Kim, Seungjun Baek. 21 Oct 2026; NeurIPS 2026 per the page. No code link.
- Status: **VERIFIED-ABSTRACT**

## Claims
- "KV eviction can change which experts are selected during answer generation, degrading the generation quality."
- Scores context by routing sensitivity (Fisher information of routing distributions) plus attention.
- At 10% KV retention: "+24 and +20 points on average on LongBench and RULER" (2.3x and 4.9x).
- The abstract says nothing about isolated-chunk vs full-context encoding. The claim that routing flips across many layers came from a snippet only (UNVERIFIED).

## For our plan
- Adjacent evidence that perturbing the context KV changes MoE routing. That makes E6 plausible but does not answer it. The E6 gap stays open.
- The routing-sensitivity score could serve as an E6 analysis tool: correlate per-token sensitivity with deviation.
