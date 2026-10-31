# EPIC: Efficient Position-Independent Caching (arXiv 2410.15332)

- URL: https://arxiv.org/abs/2410.15332 (HTML read: https://arxiv.org/html/2410.15332)
- Authors: Junhao Hu, ..., Tao Xie. v1 20 Oct 2024, v3 27 May 2025. No venue on the arXiv page.
- Code: https://github.com/DerekHJH/epic (in the paper body; the sweep missed it)
- Status: **VERIFIED-FULLTEXT**

## Method (LegoLink)
- Recomputes the **first k tokens of each chunk** except the first chunk (k <= 32; main runs use k=16), plus the query.
- Reason: "the initial tokens of each immutable chunk disproportionately absorb attention" (an attention sink from position-0 compilation).
- Selection is static, at O(kN) cost vs CacheBlend's O(N^2). LegoLink-0 prepends dummy tokens at compile time and discards their KV, so there is no link-time recompute.

## Key numbers
- Models: Mistral-7B-Instruct, Llama-3.1-8B-Instruct, **Yi-Coder-9B-Chat**. Data: 2WikiMQA, MuSiQue, HotpotQA, SAMSum, MultiNews, NIAH.
- "LegoLink-2 is sufficient to limit accuracy drops within 0 - 7%". Up to 3x TTFT vs CacheBlend for a single request; up to 8x TTFT and 7x throughput under load.
- CacheBlend's dynamic selection takes 16.3-63.6% of its TTFT. CacheBlend-15 OOMs at about 35K tokens; LegoLink-16 runs to about 50K.

## For our plan
- Keep it as the static, near-zero-cost baseline (first-k, k in {2,16,32}) and as the LegoLink-0 dummy-prefix variant. It is the most direct comparator for our "static selection costs ~0 at runtime" success criterion: graph selection must beat first-k at equal budget.
- LinearKV shows it also works as a selector on hybrids.
