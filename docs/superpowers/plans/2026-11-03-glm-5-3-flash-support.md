# GLM-5.3-Flash support plan for dotLLM (docs/plan only, nothing implemented)

Date 2026-11-03. Status: **planned / unsupported**. Research only: no weights downloaded, no GPU used. Target repo `C:\Development\dotLLM`, fork `jamesburton/dotLLM`, branch `dev` (never `main`). Items marked STUB are unverified.

## 1. What the model is (sources: HF hub metadata, 2026-11-03)

Not a GLM-4.7-Flash sibling. `GLM-5.3-Flash` is a 320B-total / 18B-active multimodal MoE ("Flash" is Z.ai's tier name, not a small model).

| Fact | Value | Source |
|---|---|---|
| Repo | `zai-org/GLM-5.3-Flash` (MIT, FP8 safetensors, `Glm5NextForConditionalGeneration`, model_type `glm5_next`, transformers 5.16) | hf.co/zai-org/GLM-5.3-Flash config.json |
| GGUF repos | `unsloth/GLM-5.3-Flash-GGUF` (UD-IQ1_S ... UD-Q6_K_XL, Q8_0, BF16, `mmproj-F16/BF16.gguf`); also huihui-ai, orcarouter, peasantsmith, ukisai finetunes | hub search |
| GGUF arch string | `glm5next` (Unsloth GGUFs); upstream llama.cpp registered `glm5-next` (PR #27773, merged); Unsloth PR #27754 closed unmerged ("works only once Unsloth GGUFs are updated") | llama.cpp PR #27754 page |
| Layers | 45: 34 `linear_attention` (KDA, Kimi-Delta-style per-channel gated delta rule, 64 heads x 128, short conv k=4) + 11 `deepseek_sparse_attention` (layers 3,7,...,43) | config.json |
| DSA/MLA layers | 64 heads, q_lora 1536, kv_lora 512, qk_head_dim 256 **all nope (`qk_rope_head_dim` 0, `mla_use_nope`)**, v_head 256; lightning indexer 32 heads x 128, top-k 2048, k-pool 4 with learned compress (`index_kpool_compress_ape/gate`), indexer RoPE interleaved | config.json |
| Residual | mHC hyper-connections: `hc_mult` 4, 20 Sinkhorn iters, per-layer `hc_attn_*`/`hc_ffn_*` tensors (reuses DeepSeek-V4 helpers in llama.cpp; no `hc_head`) | config.json, PR page |
| MoE | hidden 4096; layers 0-2 dense (inter 12288), 3-44 sparse: 288 routed experts top-8 + 1 shared, expert inter 2048, sigmoid + `noaux_tc` bias, `routed_scaling_factor` 2.5, `norm_topk_prob`, FP32 router; **clamped SwiGLU (`swiglu_limit` 10)** on dense and MoE | config.json |
| MTP | `num_nextn_predict_layers` 1, `index_share_for_mtp_iteration`; embedded in the GGUF (no separate file). llama.cpp `--spec-type draft-mtp`; PR notes NextN graph does not yet consume `h` | config.json, unsloth docs |
| Context | 1,048,576 | config.json |
| Vocab / tokenizer | 154,880; glm4 BPE; llama.cpp PR sets `ignore_merges` (token-count fix for mixed zh/en) | config.json, PR page |
| Chat template | `[gMASK]<sop>`, `<|system|>Reasoning Effort: Low/High/Max` (default Max, kwarg `reasoning_effort`), `<|user|>`, `<|assistant|><think>`, tools as `<tool_call>name<arg_key>..</arg_key><arg_value>..</arg_value></tool_call>` (same XML as GLM-4.5-4.7, so `GlmToolCallParser` applies), results in `<|observation|><tool_response>..`; `clear_thinking` kwarg (default false), `<think>` always opened by the generation prompt; template uses numeric dotted access `m.content.0.type` (llama.cpp issue #28786: minja failure) | chat_template.jinja |
| Vision | 24-layer ViT in separate `mmproj`; text-only use needs none | HF tree |
| Sampling | temp 1.0, top_p 0.95 | unsloth docs |
| Known llama.cpp caveats | needs `-fa off` (MLA F32 latent), `NVIDIA_TF32_OVERRIDE=0` on CUDA; indexer key cache stays F16 under `-ctk`; Vulkan text works, image+MTP bug | PR page |

**GGUF sizes (unsloth, GB):** IQ1_S 93.1, IQ1_M 97.6, IQ2_XXS 101.8, Q2_K_XL 108.7, IQ3_XXS 120.4, Q3_K_XL 147.5, IQ4_XS 156.8, Q4_K_XL 199.7, Q5_K_XL 240.3, Q6_K_XL 291.8, BF16 641.6. IQ1_S is 3 shards (49.6 + 43.5 GB).

**vs GLM-4.7-Flash (deepseek2 path, ~30B-A3B, Q4_K_M 18 GB):** about 10x total / 6x active params, 288 vs 64 experts; hybrid KDA recurrent + DSA instead of pure MLA; no RoPE inside MLA; mHC residual; clamped SwiGLU; 1M ctx; embedded MTP; vision tower.

## 2. GLM-5.3-FlashX

**API-only SKU, no downloadable weights** (hub search returns only `*-Flash-XSFP4` NVFP4 quant derivatives of nvidia's Flash FP4, not a FlashX). Third-party gateways (OpenRouter, Vercel AI Gateway, CometAPI, Eden AI) list it as the "high-speed serving" tier of the same 320B/18B/1M model, announced about 2026-09-18, ~200 tok/s peak, $0.37/$1.25 per M tokens; no FlashX-specific benchmarks (assume = Flash). No Z.ai primary page was fetched (STUB: confirm on docs.z.ai). **Nothing to implement; do not re-research.** Any support for Flash covers it as a cloud fallback only.

## 3. dotLLM today: lists and gaps

Lists that exist: `docs/SUPPORTED_MODELS.md` (the authoritative matrix, 18/24 enum variants rowed), `docs/ROADMAP.md` (numbered phases), `README.md` news list, `docs/SPECULATIVE.md` (MTP), `docs/MOE_OFFLOAD.md`, `docs/EXPERT_TIERING.md`, user-level `LLMs.md`. GLM-5.3-Flash was in none before this change (only a ds4/kyuz0 benchmark line in LLMs.md and the `glm-5.2` Ollama Cloud tag).

Reusable (verified present in repo): deepseek2/MLA absorbed Vulkan path (`MlaVulkanKvCache`, `attention_mla_absorbed_f32`), sigmoid+bias router (CPU and Vulkan `moe_topk_sigmoid_bias`), `GlmToolCallParser`, Gated-DeltaNet scan + recurrent snapshots and MTP attach (`Qwen3HybridDense*`, `IMtpHeadAttachable`, `MtpSpeculativeDecoder`), **Qwen4-Exp (Qwen3.8-Flash-Next) hyper-connection gated residual and QSA block-pooled indexer** (`VulkanQwen4ExpGrWeights`, `Qwen4ExpTransformerModel`), MoE offload / cpu-moe (`--n-cpu-moe`, `docs/MOE_OFFLOAD.md`), IQ1/IQ2/IQ3 packed expert banks (MiMo path), UMA admission (`DeviceMemoryBudget`).

Missing:
1. GGUF `glm5next` / `glm5-next` arch dispatch, `Architecture` variant, `ModelConfig` fields (layer_types, KDA config, indexer config, mHC, swiglu limit, nope-MLA).
2. KDA layer kernel (per-channel gate, short convs q/k/v, `A_log`/`dt_bias`, output norm+gate); differs from GDN's scalar gate, so `GatedDeltaNetScan` needs a per-channel-decay variant, plus Replay/snapshot for MTP.
3. DSA layer: MLA with 256-d nope-only Q/K (no rope split, so the 576-float latent+rope row becomes 512), absorbed split `attn_k_b/attn_v_b` shapes at head_dim 256, plus lightning indexer (k-pool compress, top-2048 selection, F16 indexer key cache) and sparse attention over the selected set.
4. mHC residual (4 streams, 20-iter Sinkhorn per sublayer) - adapt the Qwen4-Exp HC code (formulation differs: confirm against llama.cpp `build_hc_pre/post/sinkhorn`).
5. Clamped SwiGLU in dense and 288-expert MoE; top-8 of 288 router (`noaux_tc`, scale 2.5) - extend existing router kernels.
6. MTP head (NextN layer) load and attach; `index_share_for_mtp_iteration`.
7. Template: renderer must handle numeric dotted access (`.0.`) and `reasoning_effort` / `clear_thinking` kwargs; tokenizer `ignore_merges` flag; reasoning parser = existing `<think>` path.
8. Memory: no path for a 93+ GB file on 82 GiB usable per process (see section 5).
9. CUDA: no path at all for any of the above (and the box cannot hold the weights).

## 4. Phased plan (size: S <= 1 day, M 2-4 days, L 1-2 weeks, XL > 2 weeks; one agent-session each)

**Phase 0 - reference and oracle (M, no GPU).** Pull hub metadata only; read llama.cpp `glm5-next` source (PR #27773) and HF `modeling_glm5_next.py` for exact KDA/indexer/mHC math. Build `tools/glm5next-tiny-oracle` (pattern of `tools/mimo2-tiny-oracle`: tiny random HF model -> llama.cpp converter -> compare HF / llama.cpp CPU / dotLLM CPU). Deliverable: tiny GGUF + reference logits. Risk: converter version drift (Unsloth GGUFs declare `glm5next`, upstream `glm5-next`): accept both strings.

**Phase 1 - config, loader, template/tokenizer (M).** Architecture enum + `GgufModelConfigExtractor` fields; tensor name map; loader accepts file but refuses forward with an actionable message (like pre-#734 Gemma-4). Jinja numeric dotted access; `reasoning_effort`/`clear_thinking` plumbing (`ThinkingBudget` exists); `ignore_merges`. Tests: template golden vs HF `apply_chat_template`; tokenizer vs HF on mixed zh/en.

**Phase 2 - CPU reference forward on the tiny oracle (L).** KDA scan, nope-MLA + indexer + sparse attention (dense F32 reference first), mHC, clamped SwiGLU, 288/top-8 router, dense layers 0-2. Pass: max |dlogit| < 1e-4, KL < 1e-8 vs HF on tiny model, decode through caches identical to prefill. Then real-model smoke is gated by Phase 4 memory.

**Phase 3 - MTP (M).** NextN head load, `IMtpHeadAttachable`, snapshot/replay for KDA state (reuse GDN replay design from `docs/SPECULATIVE.md`), indexer sharing. Pass: speculative output == plain greedy bit-for-bit; acceptance rate measured. Reference other-runtime figure: Q2 14.15 -> 15.30 tok/s with MTP (+8%, ds4 fork; weak lever).

**Phase 4 - Vulkan + memory strategy (XL, GPU: coordinate with James).** (a) Experts stay host-resident (mmap, packed IQ1/IQ2 banks), GPU holds attention/KDA/indexer/shared/dense/router/MTP plus an expert cache, reusing MoE-offload cost-model ideas (`docs/MOE_OFFLOAD.md` is CUDA-only today; the Vulkan/UMA variant is new work, and on UMA a host expert is the same DRAM so "offload" is mostly about the 82 GiB per-process residency cap, not bandwidth). (b) Kernels: KDA scan/decode, indexer top-k, sparse MLA absorbed (extend `attention_mla_absorbed_f32` with a selected-key list), Sinkhorn, grouped IQ MoE GEMM at 288 experts. (c) Perplexity vs CPU on tiny oracle first (no big weights), then real model.

**Phase 5 - real-model validation and benchmarks (M, GPU, James).** UD-IQ1_S then UD-Q2_K_XL (HF hub cache, `hf download`, hardlink only). PPL CPU vs Vulkan, greedy identity on short prompts, decode/prefill vs llama.cpp Vulkan (build with `-fa off`). Record in `LLMs.md` and `STRIX_HALO.md`.

**Phase 6 - CUDA (L, T5500; likely build-verify only).** Tiny-oracle correctness on CUDA; the real model is out of scope on 12 GB VRAM (see below).

**Phase 7 - docs/tracking.** SUPPORTED_MODELS row promoted planned -> verified per phase, ROADMAP step, README news, LLMs.md numbers.

Critical path: 0 -> 1 -> 2 -> (3 and 4 in parallel) -> 5. Realistic total about 6-9 agent-weeks; phases 0-2 give a CPU-only correct tiny model and are the sensible first PR series.

## 5. Memory budget

**Strix Halo 8060S (127 GiB RAM, dynamic GPU heap, usable GPU memory about 82 GiB per process, verified 2026-10-10 in STRIX_HALO.md):**
- UD-IQ1_S 93.1 GB = 86.7 GiB: **does not fit GPU-resident** (over 82 GiB) and leaves little for OS/KV. IQ1_M/IQ2_XXS (91-95 GiB) and larger are worse. So every real-weights run needs the host-experts split.
- Parameter split (from config, approximate): routed experts = 42 x 288 x 3 x 4096 x 2048 = about 304B params; non-expert about 16B (shared experts, attention, dense layers, embeddings/lm_head 0.63B each). At about 1.6-2.7 bpw the non-expert block is roughly 5-10 GiB (STUB, measure from GGUF headers), which fits the GPU easily; experts (about 75-100 GiB) live in pageable host memory: fits 127 GiB RAM only for IQ1/IQ2 class with tight headroom (OS + pagefile risk, see Windows commit ceiling notes in PLATFORM_QUIRKS.md). Q3+ (120-148 GB) does not fit RAM at all. Practical ceiling on this box: UD-IQ1_S to UD-Q2_K_XL (108.7 GB = 101 GiB).
- Decode bandwidth: 18B active at about 2 bpw is about 4.5 GB/token; the box's ~256 GB/s gives a ceiling in the tens of tok/s; the other runtime's 14 tok/s at Q2 is the realistic reference (dotLLM Vulkan typically 0.5-0.7x of llama.cpp for MoE, so expect 5-10 tok/s, STUB).
- KV: DSA layers cache 512-float latent (no rope) per token per layer: 11 layers x 512 x 2 B = about 11 KiB/token F16 (22 KiB F32), so 128K ctx = 1.4 GiB F16; 1M ctx = 11 GiB; plus F16 indexer keys (k-pool 4 compressed, small) and KDA state 34 layers x 64 x 128 x 128 x 4 B = about 142 MiB per sequence, constant. Context is cheap; weights are the problem. Default `--ctx` must be capped (the 1M default would reserve 11+ GiB and trip admission).

**T5500 (RTX 3060, 12 GB VRAM, PCIe Gen 2, HDD `E:`; host RAM not recorded in OTHER_MACHINES.md, STUB):** the real model cannot be run: even IQ1_S has about 92 GB of experts, 7x VRAM, and loading from a 0.15-0.2 GB/s disk would take 10+ minutes cold; host RAM would have to exceed 100 GB. Use tiny-oracle CUDA parity only (negligible VRAM). Non-expert weights alone (5-10 GiB) would fit in 12 GB, so an experts-from-host run is conceivable if the box has >= 128 GB RAM: verify `wmic memorychip` before ever planning it.

## 6. Optimisation opportunities (after correctness)

1. **MTP speculative decode** (Phase 3): embedded head, existing engine; but +8% in the one data point.
2. **MoE decode**: 8 of 288 experts per token per layer = poor expert-cache locality; grouped IQ MMVQ at low row counts, expert prefetch from the router of the next layer (UMA: free), `--n-cpu-moe`-style split. Known dotLLM weakness: scalar MoE decode on GLM-4.7-Flash (0.12-0.14x llama.cpp tg), expert-grouped prefill GEMM.
3. **Absorbed MLA with nope-only 256-d heads**: latent row shrinks 576 -> 512, the absorbed Vulkan kernel needs head_dim 256 variant; sparse top-2048 selection makes decode attention O(2048) not O(ctx), which is the 1M-context win (llama.cpp: 20.7 -> 49 tok/s at 64K depth after optimisation).
4. **KDA decode**: constant-state; fuse conv+gate+scan per layer to cut launches (ticketed concept #1331 launch fusion).
5. **Prefix/state caching**: constant 142 MiB KDA state snapshot + 11 KiB/token latent makes whole-prefix reuse extremely cheap per token.

## 7. Interaction with chunk-KV reuse (this repo's research) - hypothesis, not tested

- Chunk-KV reuse (concatenating independently encoded chunks) is built on the assumption that each layer's K/V for a chunk is approximately prefix-independent. **34 of 45 layers are KDA recurrent layers whose state is a function of the whole prefix: they have no per-chunk KV to reuse.** A chunk encoded alone yields a recurrent state that cannot be composed with another without re-running the scan. Only exact-prefix reuse (state snapshot at a chunk boundary, as in dotLLM's GDN replay) is sound for them; non-prefix chunk reuse would require recomputing every KDA layer over the spliced text, which is the bulk of the model.
- The 11 DSA layers are the only place chunk reuse could apply, and there MLA is **nope-only**, so the RoPE-shift step of chunk assembly disappears (all Qwen3-4B costs in E1-G2 for the shift were small anyway). But staleness in earlier layers (our E3 profile shows 0.17-0.48 relative KV deviation) would still enter through the hidden states feeding every DSA layer, and the lightning indexer's top-k selection over stale latents adds a second error source.
- Expected verdict: chunk-KV reuse (non-prefix) is **not a good fit** for GLM-5.3-Flash; prefix reuse is cheap and exact. Record as a negative-by-design result; do not spend GPU time unless Phase 5 is done and James asks. The existing exact-prefix server path (Phase I) is the one that carries over, needing only a KDA-state snapshot hook (the Qwen3-hybrid models are the nearer test bed for that question, being Gated-DeltaNet hybrids too).

## 8. Validation matrix

| Check | Where | Pass bar |
|---|---|---|
| Template + tokenizer goldens vs HF | CPU | exact string / ids |
| Tiny-oracle forward (HF vs llama.cpp vs dotLLM) | CPU, Vulkan (James), CUDA (T5500, James) | dlogit < 1e-4 (CPU), top-1 100% |
| Decode via cache == prefill | CPU/Vulkan | bit/1e-4 |
| MTP == plain greedy | CPU/Vulkan | identical tokens |
| Real UD-IQ1_S: PPL CPU vs Vulkan, greedy first 24 tokens | Vulkan | within 1-2% PPL; identity |
| Perf vs llama.cpp Vulkan (`-fa off`) | Vulkan | recorded, no bar |

## 9. GPU coordination (James approves before each)

Needs James: any Vulkan run (8060S) in phases 4-5 (take the `gpu` ResourceLock; a leftover model-resident process starves the box), any CUDA run on T5500 (phase 6), any `hf download` of the 93-110 GB GGUF (disk space, shared bandwidth). Phases 0-3 are CPU-only plus hub metadata; the CPU run also competes with other sessions (`cpu-bench` lock).

## 10. Risks

- Spec drift: arch string split (`glm5next` vs `glm5-next`), GGUF tensor layouts may be re-converted (Unsloth: "update GGUFs"); pin one GGUF revision and the llama.cpp commit.
- 93+ GB minimum: only extreme quants (IQ1/IQ2) are usable here; their quality is poor (KLD 0.45-0.67, top-1 71-76%): perf, not quality, is what this box will demonstrate.
- Large unknowns in KDA/indexer/mHC math until the reference is read (Phase 0 may re-size Phase 2 to XL).
- Windows per-process residency cap and pagefile pressure with 90+ GB mmap.
- Value question: a 320B model at 5-10 tok/s on IQ1 may not beat existing local models (Qwen3.8 Flash Next at 22-30 tok/s on this box); James should decide if the effort beats e.g. finishing Qwen3.8-Flash-Next MTP.

## 11. Open questions for James

1. Is the goal real-weights inference on the 8060S (needs the Phase 4 host-experts work, XL), or tiny-oracle-level "supported" (Phases 0-3, about 3-4 weeks)?
2. Acceptable quality floor: is IQ1_S/IQ2 enough, or should the target be a REAP-pruned GGUF (e.g. `patrickbdevaney/GLM-5.3-Flash-REAP50-GGUF`, STUB, would roughly halve experts and fit the 82 GiB cap)?
3. T5500 host RAM (not recorded): needed before deciding whether any real-model CUDA run is conceivable.
4. OK to download about 93-110 GB into the HF cache for Phase 5, and to take the GPU lock?
5. Priority vs the chunk-KV Phase I5 work and Qwen3.8-Flash-Next.

## Decisions (James, 2026-11-03)
1. Real-weights inference on the 8060S is wanted, but **start with the smaller variants** (tiny/low-quant first), then scale up.
2. A low-bit quant (IQ1/IQ2) is acceptable as a *measure* (a quality floor, not a target). Higher quality may need **cloud or expert offloading**.
3. T5500 host RAM = **32 GB** (the 12 GB card cannot hold the model; host-expert offload only).
4. ~100 GB download and GPU time approved. **GPU work goes through the ResourceLock tool** (`gpu` lock; never hold it during long submits), per the usual coordination rule.
5. Priority is **lower** than the chunk-KV Phase I5 work: schedule after Part A/B milestones; do not preempt them.
6. (James, later 2026-11-03) SSD paging/expert tiering is an acceptable fallback, but on this 128 GB UMA box it should not be needed: treat the recorded ~82 GiB per-process GPU cap as something to re-verify and lift (see `2026-11-03-strix-gpu-memory-cap-remeasure.md`), not as a design constraint. Plan for fully resident models first, tiering only if the re-measure confirms the cap.
