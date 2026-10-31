# CodeComp: Structural KV Cache Compression for Agentic Coding (arXiv 2604.10235)

- URL: https://arxiv.org/abs/2604.10235 (HTML read: https://arxiv.org/html/2604.10235)
- Authors: Qiujiang Chen, Jing Xiong, Chenyang Zhao, Sidi Yang, Ngai Wong. 11 Apr 2026, arXiv (cs.CL). No code link.
- Status: **VERIFIED-FULLTEXT**

## Method
- Training-free KV **compression** (eviction) guided by Joern Code Property Graph priors.
- Spans are anchored on calls, control predicates, returns, assignments and signatures, then scored with weighted features. Spans that overlap query symbols are always protected. The span budget is 0.5 of the chunk budget, and the rest is filled by proximity and then attention.
- Chunk budget multiplier is in [0.5, 1.5], set from log-normalised CPG counts.
- Chunks are scored independently and keep their scoring-stage positions. There is no cross-request reuse or recompute.

## Key numbers (mixed results, not a clean win)
- Bug localisation average: Llama3-8B, cap 0.4: 0.36 vs SnapKV 0.33. Qwen3-8B, cap 0.6: 0.53 vs 0.50. **Qwen3-8B, cap 0.4: 0.51 vs SnapKV 0.52 (loses).**
- SWE-bench Lite GF F1: DS-Coder, cap 0.4: 0.250 vs 0.200. **Qwen-Coder, cap 0.6: SnapKV 0.700 vs CodeComp 0.613 (loses).**
- LCA API F1 (DS-Coder, cap 0.6): 0.234 vs SnapKV 0.088.
- Model reporting is inconsistent across sections (Llama3-8B/Qwen3-8B vs DS-Coder/Qwen-Coder/Qwen2.5-Coder-32B).

## For our plan
- The only verified work using a static program graph inside KV management. It shows graph priors help some code tasks over attention-only scoring, but not uniformly.
- It is the competing-claim risk and the precedent to cite for E4. Our claim must be specific: graph-guided **recompute selection when stitching independently encoded chunks**, not compression.
- Its feature set (calls, predicates, assignments, signatures, query-symbol overlap) is a ready starting list for the E4 graph-role features. It uses Joern; we plan tree-sitter (C#).
