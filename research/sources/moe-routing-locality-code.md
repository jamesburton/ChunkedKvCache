# Layer-wise MoE Routing Locality under Shared-Prefix Code Generation (arXiv 2604.17182)

- URL: https://arxiv.org/abs/2604.17182
- Authors: Shun-ichiro Hayashi, Daichi Mukunoki, Tetsuya Hoshino, Takahiro Katagiri. 19 Apr 2026, arXiv (cs.SE). No code link.
- Status: **VERIFIED-ABSTRACT**

## Claims
- Qwen3.5-35B-A3B-FP8 (256 experts, top-8), tree-search branches from a shared prefix, 851 compiled codes.
- Routing Jaccard at same-token positions is 0.649 (40x random); at different-token positions it is 0.175 (11x random).
- Same-token similarity dips in middle layers L14-20, where context enters routing. Different-token similarity peaks there.
- The authors say this refines earlier "context-independent routing" claims.

## For our plan
- Routing depends on token identity but is noticeably context-dependent in middle layers, on a Qwen3.5 MoE hybrid relative of the target.
- This predicts where E6 drift should show (middle layers). It does not measure isolated-vs-full chunk encoding, so it is a decode-branch setting, not chunk reuse.
- Its Jaccard-over-top-k metric is a ready E6 metric.
