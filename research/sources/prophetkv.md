# ProphetKV: User-Query-Driven Selective Recomputation (arXiv 2602.02579)

- URL: https://arxiv.org/abs/2602.02579 (HTML read: https://arxiv.org/html/2602.02579)
- Authors: Shihao Wang et al. v1 31 Jan 2026, v3 5 Feb 2026. arXiv preprint (cs.OS); no venue listed. No code link.
- Status: **VERIFIED-FULLTEXT** (abstract + method + eval read 2026-10-31)

## Method
- Scores each context token by the mean attention the user-query tokens pay to it, computed on the reused (position-independent) KV.
- Stage I: a light pass over all layers that computes only query-to-context attention (column sums per layer).
- Stage II: averages per-layer scores uniformly, takes top-k, and recomputes those tokens in every layer (one fixed set for all layers).
- Names a "crowding-out effect": globally salient but query-irrelevant tokens use up the CacheBlend budget.

## Key numbers
- 20% recompute retains "96%-101%" of full-prefill accuracy; "+8.8%-24.9%" on RULER and "+18.6%-50.9%" on LongBench over CacheBlend/EPIC/KVShare.
- TTFT on H100: Llama-3-8B at 16K, 5.23 s full vs 1.13 s; Qwen2.5-14B at 16K, 9.94 s vs 2.12 s. EPIC is slightly faster; CacheBlend is slower.
- Models: Llama-3.1-8B-Instruct, Qwen2.5-14B-Instruct, Qwen3-14B. Benchmarks: RULER 4-16K, LongBench, which includes the code sets LCC and RepoBench-P (code is not the focus).
- Appendix D: lower layers attend locally; higher layers attend to distant tokens.

## For our plan
- This is the concrete "query-relevance selector" for Phase P. Its rule is simple to reimplement in dotLLM: one cheap attention pass, then a fixed token set.
- It is query-dependent, so the selection cannot be precomputed per chunk. Our static graph selector costs ~0 at runtime; ProphetKV is the strongest dynamic rival to beat at equal budget.
- LinearKV uses it as a selector on hybrids (OLMo-Hybrid + ProphetKV reaches ~92% of full on RULER-8K), so it carries over to the Phase T target.
