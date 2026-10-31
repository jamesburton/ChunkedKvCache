# KV Packet: Recomputation-Free Context-Independent KV Caching (arXiv 2604.13226)

- URL: https://arxiv.org/abs/2604.13226 (HTML v3 read: https://arxiv.org/html/2604.13226v3)
- Authors: Chuangtao Chen, ..., Ulf Schlichtmann (TUM). v1 14 Apr 2026, v3 25 Oct 2026 (camera-ready). **NeurIPS 2026** per the comments field.
- Code: https://github.com/ChuangtaoChen-TUM/KVPacket
- Status: **VERIFIED-FULLTEXT**

## Method
- Each cached document's KV is frozen and wrapped in 8 header + 8 trailer trainable soft tokens (fp32), trained by self-distillation against the model's own full-attention output.
- Training: 256-512 samples, 30 epochs, batch 64; F1 stabilises in 3-5 epochs; no labels needed. Adapters are probably model-specific (my inference, not stated).

## Key numbers
- Models: Llama-3.1-8B-Instruct, **Qwen3-4B-Instruct**; Llama-3.2-3B in the appendix. Benchmarks: NIAH, Biography, HotpotQA, MuSiQue. No code tasks.
- F1 (Llama-8B), KV Packet vs no recompute: Biography 0.94 vs 0.06, HotpotQA 0.44 vs 0.24, MuSiQue 0.38 vs 0.01, NIAH 0.80 vs 0.39. HotpotQA (2K examples) is 0.423 vs 0.460 for full recompute.
- TTFT speedups of 1.36x-19.45x; the baseline for these is not named.
- **Inconsistent:** the FLOPs claim is "5-6 orders of magnitude" lower than full recompute in one place and "~4 orders" vs CacheBlend/EPIC in another. No numeric CacheBlend/EPIC F1 appears in the text.

## For our plan
- It is evaluated on Qwen3-4B-Instruct (our Phase P model class) and the code exists, so it is a concrete path for the E9 stretch (trained link tokens).
- It stays a non-goal as the primary path (spec section 3: training-free first).
