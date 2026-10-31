# LinearKV: One Cached State Suffices for PIC in Hybrid LLMs (arXiv 2608.11231)

- URL: https://arxiv.org/abs/2608.11231 (HTML read: https://arxiv.org/html/2608.11231)
- Authors: Yirui Liu, Ruoling Qi, ... Xuelong Li. 31 Jul 2026, arXiv (cs.AI). No code link (uses the flash-linear-attention kernels).
- Status: **VERIFIED-FULLTEXT**

## Method
- Training-free hybrid PIC. Each linear layer is initialised from a **single cached chunk state**, by default the last matched chunk; the choice of chunk "barely matters". Full-attention KV is concatenated as usual.
- Any PIC selector works: the paper tests CacheBlend, EPIC and ProphetKV. Selected positions are replayed in order.
- It is compared with exact composition of all chunk states (the HYPIC approach).

## Key numbers
- Models: **Granite-4.0-H-Tiny** (Mamba-2, MoE; 4 FA + 36 Mamba-2 layers), **OLMo-Hybrid-7B-Instruct** (8 FA + 24 GDN), **Qwen3.6-27B** (16 FA + 48 GDN). Benchmarks: LongBench QA and summarisation; RULER 8K and 32K.
- On the GDN models, last-block init and exact composition are within 0.013 Avg-F1 of each other. OLMo + ProphetKV reaches about 92% of full on RULER-8K.
- On Mamba-2 (Granite), exact composition collapses: under EPIC it reaches 46.6% of full, vs 86.8% for last-block. Across budgets r = 0.03-0.4 it is 41-52% vs 76-89%. The paper attributes this to Mamba-2's scalar decay summing transported mismatch.
- TTFT at r=0.2, 32K: last-block is 0.46-0.62x **full prefill** and 5-17% faster than exact composition (e.g. Qwen3.6-27B, 3843 ms full vs 1810 ms with CacheBlend).

## For our plan
- This decides a Phase T design question for a GDN target: composition and a single cached state perform about the same, and the single state is cheaper with no per-head operator storage. Start Phase T from LinearKV last-block + a selector; add HYPIC composition as the comparison.
- The CacheBlend/EPIC/ProphetKV selectors from Phase P carry over to hybrids unchanged, as long as the recurrent layers are handled this way. So Phase P baselines stay valid.
- Qwen3.6-27B is 3:1 GDN:FA. Sweep C reported the same ratio for Qwen3.8-27B. The Flash-Next split is still unverified.
