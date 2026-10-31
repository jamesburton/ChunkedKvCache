# RelaxKV: Recomputation Guided by the Query with Sparse Context Attention (arXiv 2609.33503)

- URL: https://arxiv.org/abs/2609.33503
- Authors: Ruoling Qi, Yirui Liu, ... Jiawei Shao (overlapping author group with LinearKV and Tail-Replay). 27 Sep 2026, arXiv (cs.AI). No code yet; a search snippet says it will be released on acceptance.
- Status: **VERIFIED-ABSTRACT**

## Claims
- Treats selective repair as joint allocation over repair targets and the recomputation context. Picks "layer-specific repair targets" guided by the query.
- At a 15% anchor ratio it beats ProphetKV on aggregate LongBench across four decoder models. On Qwen3-14B it has a better quality-TTFT trade-off than ProphetKV over 5-30%. Best selective results on RULER-MV and LV-Eval at 16K/32K.
- Whether it tests freezing early layers is not stated in the abstract.

## For our plan
- The current state-of-the-art claim among query-guided selectors, and the closest to layer-specific selection (E5). Read the full text before claiming novelty for layer tiering.
- Reimplement only if code appears. Otherwise ProphetKV stands in for this family.
