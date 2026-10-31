# An experimental study of KV cache reuse strategies in chunk-level caching systems (arXiv 2603.20218)

- URL: https://arxiv.org/abs/2603.20218 (HTML read: https://arxiv.org/html/2603.20218)
- Authors: Samuel Cestola, Tianxiang Xia, Zheng Weiyan, Zheng Pengfei, Diego Didona. 3 Mar 2026, arXiv (cs.CL). No code link.
- Status: **VERIFIED-FULLTEXT**

## Content
- Techniques evaluated: CacheBlend, EPIC, Link0, CacheClip, a Droidspeak adaptation (recompute-based); APE and fine-tuned Block-Attention/TurboRAG-style models (attention-reshaping).
- Models: Llama3.1-8B, Qwen3-8B, Mistral-7B-v0.3. Data: 2WikiMQA, MuSiQue, RULER. F1 is adjusted to exclude queries where full prefill scores 0.

## Key numbers
- CacheBlend (r=15%) trails full prefill by about 7-18%. APE is 2-9% below CacheBlend. Fine-tuned Block-Attention is 4-7% below CacheBlend. CacheClip is within 3% of CacheBlend or 4-15% better.
- Proposed **PSR** (prefix + scale + recompute: Link0-style prefix tokens, CacheBlend selection, APE scaling) is consistently best, with up to +5% absolute.

## Per-layer findings (quoted)
- "The clusters of chosen tokens at early layers correspond to beginning-of-chunk tokens."
- "only 8% to 20% of the tokens selected for recomputation are constant across all layers"
- "Optimal token selection is dynamic"; "Last-layer token selection is not a silver bullet."
- Droidspeak re-selects at layer 5 and does poorly, because "Dynamic recomputation needs cached cross-attention."

## For our plan
- This partly covers E3 (dense per-layer deviation). E3 must cite and extend it: add token type, graph role, and a per-layer top-k capture curve.
- PSR is the strongest training-free combined baseline here. Add it to the Phase P selector list.
- It also supports the anti-goal in spec section 4: CacheBlend is noticeably below full prefill once evaluation is cleaned.
