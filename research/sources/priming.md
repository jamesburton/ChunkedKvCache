# Priming: Hybrid State Space Models From Pre-trained Transformers (arXiv 2605.08301)

- URL: https://arxiv.org/abs/2605.08301 (HTML read for section 7 only: https://arxiv.org/html/2605.08301v1)
- Authors: Aditya Chattopadhyay, ..., Stefano Soatto. 8 May 2026, arXiv (cs.LG). The abstract says code, a model zoo and a vLLM plugin are released (Apache-2.0), but the page gives no repo URL.
- Status: **VERIFIED-FULLTEXT (partial)**: I read the abstract and sections 7.1-7.2. The Appendix E body was not read.

## Section 7.1 Hybrid States Composition (training-free context extension)
- The input is split into K chunks of native length, each with a shared prefix. Each chunk is prefilled independently with position IDs from 0, batchable.
- The per-chunk KV is concatenated, keeping one copy of the prefix.
- Recurrent states are merged by **souping (averaging; the default)** or by **fusion** with PICASO coefficients. The authors default to souping because the two are comparable at 256K+ and souping is cheaper. (Sweep C implied PICASO is the main method; corrected here.)
- The query is then prefilled normally from the merged cache and state.
- Appendix E has the headings "GDN: PICASO with dense transition matrices", but I did not read the body (UNVERIFIED).

## Key numbers (section 7.2, RULER NIAH 256K / 512K)
- GDN-8B: standard prefill 30.1 / 0.0; YaRN 61.7 / 32.2; State Comp 66.3 / 43.0.
- GKA-8B: 32.9 / 0.0; 64.5 / 32.8; 70.7 / 46.3. Mamba2-8B: 22.9 / 0.0; 50.5 / 31.5; 62.0 / 36.7.

## For our plan
- A third hybrid state-composition precedent (with HYPIC and LinearKV). It is framed as context extension, not caching: no persistence and no cross-request reuse. Its results are relative to failing baselines past native context, not to full-prefill quality within the native window.
- The averaging (souping) merge is a cheap Phase T baseline alongside LinearKV last-block and HYPIC composition.
