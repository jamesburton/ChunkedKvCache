# Evaluating the accuracy of KV cache reuse techniques (Boxoffice) (arXiv 2609.31415)

- URL: https://arxiv.org/abs/2609.31415 (HTML read up to 100K of 140K characters: https://arxiv.org/html/2609.31415)
- Authors: Samuel Cestola, ..., Diego Didona (same group as 2603.20218). 25 Sep 2026, arXiv (cs.LG).
- Code: https://github.com/boxoffice1280/boxoffice1280 ; dataset: https://huggingface.co/datasets/Boxoffice1280/boxoffice1280
- Status: **VERIFIED-FULLTEXT (partial, ~70% read)**

## Methodology
- Evaluate only the "meaningful subset". Drop **B0** (full prefill F1 = 0), **NC** (answerable without context, F1 > 0.2 with no context), and **LI** (low-information yes/no or disjunctive questions).
- Report norm-F1 = method F1 / full-prefill F1, and the ratio rho of filtered to unfiltered norm-F1.
- Flaws found in existing evaluations: accidental regularisation, parametric leakage, chance correctness; LongBench chunks within a query are semantically clustered; only 0.7-12.6% of unique chunks recur across queries.

## Key numbers
- CacheBlend + Qwen on 2WikiMQA falls from 0.87 (B0 filter) to 0.52 (after the LI filter).
- "Flipping" queries (full prefill fails, the method succeeds) make up as much as 42% of aggregate F1 on MuSiQue.
- On the meaningful subset, the no-infusion baseline's norm-F1 is 0.10-0.38. LMCache scores about 0.97-0.98 on aligned queries and **0.00 on flipped (stale-role) queries**.
- Methods evaluated: CacheBlend, FusionRAG, LMCache, CacheCraft. EPIC and APE are not re-evaluated in the part I read.

## For our plan
- Adopt the B0/NC/LI filtering and norm-F1 for all multi-document QA in E1-E5. This puts the anti-goal in spec section 4 into practice.
- Boxoffice can generate hard reuse patterns, so use it for the "hard cases" requirement.
- Code tasks already need exact-match/execution checks; apply the same B0/NC idea to them (drop items full prefill fails, and items answerable with no context).
