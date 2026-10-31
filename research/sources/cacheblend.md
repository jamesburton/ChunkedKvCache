# CacheBlend: Fast LLM Serving for RAG with Cached Knowledge Fusion (arXiv 2405.16444)

- URL: https://arxiv.org/abs/2405.16444 (HTML read: https://arxiv.org/html/2405.16444). EuroSys '25 (venue not on the arXiv page; widely cited as EuroSys '25, UNVERIFIED here).
- Authors: Jiayi Yao, ..., Junchen Jiang. v1 26 May 2024, v3 3 Apr 2025.
- Code: https://github.com/LMCache/LMCache
- Status: **VERIFIED-FULLTEXT**

## Method
- Recomputes HKVD (high-KV-deviation) tokens. The ideal rule needs full-prefill KV, so it uses a proxy: "Tokens with the highest KV deviations on one layer are likely to have the highest KV deviations on the next layer."
- Gradual filtering: the first layer selects by token-wise attention/KV deviation, and each later layer recomputes only the previous layer's set and keeps a slightly smaller top share.
- Default recompute is about 15% (10-20% cited). The final ratio is max(15%, the ratio that hides loading delay). Recompute is pipelined with KV loading.

## Key numbers
- "about 10-15%" of tokens have much higher deviation (one layer, MuSiQue).
- TTFT is 2.2-3.3x lower and throughput 2.8-5x higher vs full recompute. Quality loss is "within 0.02" F1/Rouge-L (at most 0.002 in the Yi-34B sensitivity study at 5-18%).
- Models: Mistral-7B, Yi-34B, Llama-70B (8-bit). Data: 2WikiMQA, MuSiQue, SAMSum, MultiNews.

## Caveats from later work
- 2603.20218: at r=15% it trails full prefill by 7-18% under adjusted F1, and its early-layer picks cluster at chunk starts.
- 2609.31415: its gains shrink a lot under meaningful-subset evaluation.
- EPIC: its dynamic selection overhead is 16-64% of TTFT.

## For our plan
- Keep it as the reference baseline (gradual filtering, r in {5,10,15,20}%), but it is no longer the bar to beat on quality. ProphetKV, CacheClip and PSR all report beating it.
