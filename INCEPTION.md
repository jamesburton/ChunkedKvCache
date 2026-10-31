# Research Brief: Chunk-Level KV Caching with Light Cross-Chunk Attention

> **Audience:** an autonomous research/engineering agent starting this work cold.
> **Status:** premise + prior-art summary written from model knowledge (cutoff ~mid-2026, brief dated 2026-10-30). **Step 0 (fresh web research) is mandatory before any implementation** — newer work may change the plan.

---

## 1. Premise

Prefill dominates time-to-first-token (TTFT) and compute for long-context workloads (RAG, codebases, document sets). Much of that context is **stable and reused** — the same files, docs and chunks appear across many requests, just in different combinations and positions.

Exact prefix caching (vLLM APC, SGLang RadixAttention, provider prompt caching) only helps when the identical prefix appears at the identical position. That rarely holds when chunks are retrieved and mixed per query.

**Hypothesis:** we can precompute and persist per-chunk representations (KV caches or hidden states) offline, then at query time assemble them with only a *light* cross-chunk mechanism. That mechanism could be:

- selective recompute of a few high-impact tokens,
- learned link/bridge tokens,
- or recompute targeted by the **known structure of the content**: for code, the reference graph (imports, symbol definitions and uses, call sites); for documents, cross-references and headings.

**Secondary idea (from the originating discussion):** capture early-layer representations, which are mostly local and syntactic, and skip or limit recompute in early layers. Caveat to test: in decoder-only models every layer's KV depends on upstream context, so caching only early layers still forces the expensive deep layers to run. The stronger form is to cache **all-layer** KV per chunk and focus recompute where cross-chunk dependence concentrates (likely deeper layers and a few "hub" tokens). For MoE models, **expert routing drift** between isolated and full-context encoding is another possible error source; it is unmeasured as far as is known.

### Hypothesised gap (verify in Step 0)

- **Structure-aware recompute selection.** Choose which tokens to recompute, or where to place link tokens, from a *static* reference graph rather than CacheBlend-style runtime KV deviation. This appears under-explored.
- **Content-aware chunk boundaries** (function, class or section) that keep cached chunks self-contained and allow incremental re-encoding when a file changes, like a build cache.
- **Per-layer deviation profiling**, including MoE routing drift, to see whether "freeze early layers, recompute deep layers on k% of tokens" beats uniform selection.

---

## 2. Prior Art (starting reading list — verify, extend, and correct)

### 2.1 Exact prefix caching (baseline)
- **vLLM Automatic Prefix Caching**, **SGLang RadixAttention**: hash- or radix-tree reuse of identical prefixes.
- Provider prompt caching (Anthropic, OpenAI, Gemini context caching): exact-prefix only.

### 2.2 Modular / position-independent KV reuse (training-free)
- **Prompt Cache** (Gim et al., 2023, "Modular Attention Reuse"): schema-defined reusable prompt modules.
- **CacheBlend** (Yao et al., 2024; EuroSys '25): reuse per-chunk KV, re-rotate RoPE, recompute ~10–20% of tokens with the highest KV deviation. Reported 2–3× TTFT reduction at near full-prefill quality. **Primary baseline.**
- **EPIC** (2024): position-independent context caching ("LegoLink").
- **APE: Adaptive Parallel Encoding** (ICLR 2025): training-free parallel chunk encoding with attention adjustments.
- **Cache-Craft** (2025, SIGMOD): chunk-cache management for RAG.
- **RAGCache** (2024): knowledge-tree KV caching for RAG.
- **CacheGen** (2024): KV compression and streaming.
- **LMCache** (open source, integrates with vLLM, implements CacheBlend). **Primary tooling.**

### 2.3 Train the model for independent chunks
- **Block-Attention** (Sun et al., 2024): block-diagonal attention fine-tune; last block attends globally.
- **TurboRAG** (2024): precompute chunk KV offline; fine-tune with independent masks and reset positions.
- **KVLink** (2025): learned link tokens bridge independently encoded chunks. Closest to a "light between-chunk mechanism".
- **Parallel Context Windows** (Ratner et al., 2023).

### 2.4 Encoder–decoder split / compressed chunk representations
- **Fusion-in-Decoder (FiD)** (Izacard & Grave, 2020): the original per-passage encode plus decoder fusion.
- **CEPE** (Yen et al., 2024): small parallel context encoder plus cross-attention into the decoder.
- **REFRAG** (Meta, 2025): compressed chunk embeddings with a policy for selective expansion. Reported ~30× TTFT gains.
- **xRAG** (2024): a single-token embedding per document.
- **Gist tokens**, **ICAE**, **AutoCompressors**, **500xCompressor**: context compression.

### 2.5 Persistent trained memory per corpus
- **Memory³** (2024): explicit sparse KV memory for a knowledge base.
- **KBLaM** (Microsoft, 2025): knowledge tokens with rectangular attention.
- **Cartridges** (Stanford, 2025): train a compact KV cache per corpus via "self-study". Reported ~38× memory reduction. Highly relevant for codebases.

### 2.6 Layer-level prefill reduction (relevant to the layer-skip idea)
- **SwiftKV** (Snowflake, 2024): compute later layers' KV from an earlier layer's output; ~50% prefill compute cut.
- **YOCO** (Microsoft, 2024): decoder–decoder; global KV comes from the first half, so prefill can exit early.
- **HCache** (2024/EuroSys '25): store hidden states, rebuild KV by projection.
- **KV Prediction** (Apple, 2024): an auxiliary model predicts the base model's KV to cut TTFT.
- **Cross-Layer Attention (CLA)**, **KVSharer**, **LayerSkip**.

### 2.7 Block-sparse / landmark attention (architectural relatives)
- **Landmark Attention** (2023): per-block landmark tokens for block retrieval.
- **NSA: Native Sparse Attention** (DeepSeek, 2025), **MoBA** (Moonshot, 2025), **DeepSeek Sparse Attention** (V3.2 "lightning indexer").
- **Quest**, **RetrievalAttention**, **MagicPIG**, **InfiniGen**: query-aware KV selection and offload (mostly a decode-time benefit).

---

## 3. Step 0 — Mandatory Fresh Web Research (do this first)

The list above may be stale. Before designing or coding:

1. **Search broadly** (arXiv, Semantic Scholar, Papers with Code, Hugging Face papers and daily papers, GitHub, the vLLM/SGLang/LMCache repos, release notes and issues, and MLSys/OSDI/EuroSys/NeurIPS/ICLR/ICML/ACL 2025–2026 proceedings) for:
   - "position-independent KV cache", "modular KV cache", "chunk KV reuse RAG", "CacheBlend follow-up"
   - "parallel context encoding", "block attention RAG", "KV link tokens"
   - "structure-aware" / "graph-guided" / "code-aware" KV cache or attention
   - "repository-level KV cache", "codebase prefill caching", "incremental KV cache on edit"
   - "hidden-state caching prefill", "layer skipping prefill", "MoE routing context dependence"
   - newer work citing CacheBlend, TurboRAG, KVLink, REFRAG, Cartridges, SwiftKV, HCache
2. **Check the current state of the tooling**: does LMCache, vLLM or SGLang now ship blending, position-independent caching or link tokens natively? Which model families and versions are supported?
3. **Produce `research/landscape.md`** containing:
   - an updated reference table (paper, year, venue, link, method class, reported speedup and quality, code available yes/no),
   - an explicit verdict on whether the **hypothesised gaps in §1** are still open, partly covered, or already done (with citations),
   - a recommended pivot if a gap is closed (for example: build on the newer method instead of CacheBlend).
4. **Gate:** if the research materially changes the plan, update §4–§5 of this brief (or write `plan-v2.md`) and stop to report to the user before running experiments.

---

## 4. Initial Test Plan

### 4.1 Environment
- Read `~/.claude/LLMs.md` (local hardware, models, measured performance) and `~/.claude/OTHER_MACHINES.md` (Strix, T5500) before choosing where to run.
- **Ask the user before launching any GPU work on remote machines.** State the machine, device and expected duration. CPU-only remote work: announce, then proceed.
- Stack: **vLLM + LMCache** (CacheBlend path). Fallback: a HuggingFace Transformers prototype with manual KV assembly, which is easier for per-layer instrumentation.
- Models: one dense model (~7–8B, e.g. Llama-3.x-8B or Qwen-class) and, for the MoE routing experiment, one small MoE (e.g. Qwen MoE or OLMoE class; check what current options fit the hardware).

### 4.2 Datasets
- **Code:** 2–3 mid-size open-source repos. Tasks: repo-level QA / completion (e.g. RepoBench, CrossCodeEval, LongCodeArena, or newer equivalents found in Step 0).
- **Docs/RAG:** standard multi-document QA (e.g. 2WikiMQA, MuSiQue, HotpotQA) as used in the CacheBlend and TurboRAG papers, for comparable numbers.

### 4.3 Chunking
- **Code:** split by symbol (function, class, module) using tree-sitter. Extract the **reference graph**: definitions, uses, imports, calls.
- **Docs:** split by section or heading; extract cross-references, entity mentions or headings.
- Baseline: fixed 512-token chunks.

### 4.4 Experiments

| # | Experiment | Compare | Metrics |
|---|---|---|---|
| E1 | **Baselines** | full prefill vs naive chunk-KV concatenation (no recompute) vs prefix caching | task quality, TTFT, prefill FLOPs, KV storage size |
| E2 | **Reproduce CacheBlend** via LMCache | E1 vs CacheBlend at recompute ratios of 5/10/15/20% | quality-vs-TTFT curve |
| E3 | **Per-layer deviation profile** | for each layer: KV deviation (isolated vs full-context) per token; where it concentrates (layer, token type, graph role) | heatmaps; % of deviation captured by the top-k tokens |
| E4 | **Structure-aware selection** (core novelty) | CacheBlend selection vs reference-graph selection (definition sites, used symbols, import lines) vs a hybrid, at equal recompute budget | quality at equal budget; selection overhead (static selection should cost ~0 at runtime) |
| E5 | **Layer-tiered recompute** | uniform recompute vs "early layers reused as-is, deep layers recompute k%" | quality, FLOPs |
| E6 | **MoE routing drift** (MoE model only) | expert assignment agreement, isolated vs full context, per layer | routing agreement %, correlation with quality loss |
| E7 | **Chunk boundary effect** | fixed-size vs symbol/section chunks | quality, cache hit rate, re-encode cost after a simulated file edit |
| E8 *(stretch)* | **Hidden-state vs KV storage** (HCache-style) | store KV vs hidden states + projection | storage bytes, restore latency |
| E9 *(stretch)* | **Learned link tokens** at definition sites (KVLink-style, light fine-tune) | E4 vs link tokens | quality, training cost |

### 4.5 Success criteria
- E4 matches or beats CacheBlend quality at the same recompute budget, **or** matches its quality at a lower budget, with negligible selection overhead.
- E3/E5 give a clear answer on whether layer-tiering is worth pursuing.
- Every result reports the variance over ≥3 seeds or query sets; no single-run claims.

---

## 5. Deliverables & Working Conventions

- `research/landscape.md`: Step 0 output (see §3).
- `experiments/`: one folder per experiment containing a config, a runnable script, raw results (CSV/JSON) and a short `README.md` with findings.
- `REPORT.md`: rolling summary of results, the quality-vs-TTFT plots, and a recommendation on next steps.
- Commit small and often. Record the exact model revisions, library versions and hardware for every run.
- If a finding is confirmed and general (hardware performance, tool behaviour), update `~/.claude/LLMs.md` per the user's knowledgebase conventions.
- Stop and report at these gates: after Step 0, after E2 (baseline reproduced), and after E4 (core hypothesis result).
