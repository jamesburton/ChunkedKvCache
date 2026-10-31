# VLCache: Computing 2% Vision Tokens and Reusing 98% (arXiv 2512.12977)

- URL: https://arxiv.org/abs/2512.12977
- Authors: Shengling Qin, ..., Shuai Bai, Junyang Lin (Qwen team). v1 15 Dec 2025, v2 18 Dec 2025, arXiv (cs.CV). No code link; built on SGLang.
- Status: **VERIFIED-ABSTRACT**

## Claims
- Reuses KV and encoder caches for repeated multimodal inputs and names a "cumulative reuse error effect".
- A "dynamic, layer-aware recomputation strategy" gives accuracy on par with full recompute at 2-5% recomputed tokens and 1.2-16x TTFT.
- **UNVERIFIED:** a secondary summary says it gives *earlier* layers a higher recompute ratio. The abstract does not say which layers get more.

## For our plan
- The closest found prior to non-uniform per-layer recompute budgets (E5), but for vision tokens. If the snippet holds, it points the opposite way to "freeze early, recompute deep". Read the full text before writing E5's novelty statement.
