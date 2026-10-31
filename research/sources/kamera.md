# Kamera: Unified Position-Invariant Multimodal KV Cache for Training-Free Reuse (arXiv 2606.23581)

- URL: https://arxiv.org/abs/2606.23581
- Authors: Bole Ma, Jan Eitzinger, Harald Koestler, Gerhard Wellein (Bole Ma is also first author of Irminsul). 22 Jun 2026, arXiv (cs.DC). No code link.
- Status: **VERIFIED-ABSTRACT**

## Claims
- "Blind reuse therefore leaves single-hop recall intact while halving multi-hop accuracy."
- The lost cross-chunk information is "a diffuse, low-rank residue concentrated in deep layers, invisible to single-hop retrieval."
- A training-free per-chunk rank-m conditioning patch plus exact RoPE re-rotation "recovers full task accuracy on cross-chunk-binding benchmarks." It reconstructs re-prefill KV to within bf16 rounding in an SGLang kernel across six backbones.

## For our plan
- A third source (with CacheClip and SpecCache) that the deviation concentrates in deep layers. Supports E3/E5 framing.
- The low-rank patch is a recompute-free alternative to watch. It is multimodal-framed, and the supporting analysis was not read.
