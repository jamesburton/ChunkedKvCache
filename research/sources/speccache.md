# SpecCache: Speculative KV Cache Reuse for Efficient RAG Serving (ACL 2026 long 859)

- URL: https://aclanthology.org/2026.acl-long.859/ (PDF: https://aclanthology.org/2026.acl-long.859.pdf). DOI 10.18653/v1/2026.acl-long.859, pp. 18861-18871.
- Authors: Zijian Wen, Tao Zhang, Shuangwu Chen, et al.
- Status: **VERIFIED-ABSTRACT** (I read the Anthology abstract page; the PDF body was not read). No code link on the page.

## Claims (abstract)
- KV deviations are larger in deep layers, but extracting deep-layer features from the target model is too expensive.
- The deep-layer features of a small speculative (draft) model agree closely with the target model on which tokens need recompute.
- SpecCache selects critical tokens by the **deep-layer hidden-state norms** of the speculative model.
- Versus full recompute: TTFT is 2.17-3.95x lower and throughput 2.7-5.2x higher, with "negligible" quality loss.
- I did not confirm models, benchmarks or the head-to-head numbers against CacheBlend/ProphetKV.

## For our plan
- A second source, independent of CacheClip, that deep layers carry the deviation signal. This is relevant to E3/E5 framing.
- The plan targets a model with MTP, and Flash-Next ships a draft/MTP head, so a "speculative-model" selector could reuse that head. That is worth noting for Phase T, but it is speculative. Stretch baseline only.
