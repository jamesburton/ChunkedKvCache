# Chunk-level KV reuse for long-context code models, built in dotLLM — design

Status: draft for review. 2026-10-31. Companion to `INCEPTION.md` (the research brief). Where this document and the brief disagree, this document wins; the brief's Step 0 gate and experiment list (E1-E9) still apply unless changed below.

Items marked **[my call]** were decided by the author, not by the user. Everything else was stated by the user.

## 1. Intent and why

Long-context prefill dominates time-to-first-token for coding work. On the user's Strix Halo box, Qwen3.8-Flash-Next prefill is roughly 270-630 tok/s, so a 262K-token context costs about 16 minutes (measured, `~/.claude/LLMs.md`). Much of that context is stable: the same repository files recur across requests, in different combinations and positions. Exact prefix caching only helps when the identical prefix sits at the identical position.

The user wants: research first, leading into implementation; fast local code models that reuse chunked context so heavy prefill is avoided; the result built **directly in dotLLM** (the user's fork, `C:\Development\dotLLM`, `dev` branch) and published for use beyond what dotLLM currently offers. The research and experiment record lives in this repo (`C:\Development\ChunkedkvCache`).

## 2. Goals

1. Persist per-chunk representations (KV, and for non-attention layers whatever state is needed) so a request can assemble a long context from cached chunks without re-prefilling them.
2. Keep cross-chunk quality close to full prefill with only light extra work, using selective recompute and (for code) selection driven by static structure (reference graph) rather than runtime deviation.
3. Scale from short contexts to repositories beyond 1M tokens: the cache is persistent on disk, content-addressed, memory-mappable, and chunk-granular so a file edit invalidates only its chunks.
4. Ship as a dotLLM feature on the `dev` branch of the user's fork, coordinated with the dotLLM session (`dotllm-b7`) for anything touching shared interfaces.
5. Produce evidence: every claim reported with variance over at least 3 seeds or query sets, exact model revisions, library versions and hardware.

## 3. Non-goals

- Reproducing the vLLM + LMCache stack on CUDA. CacheBlend and newer selectors are reimplemented in dotLLM as baselines instead **[my call]**.
- Fine-tuned methods (TurboRAG, KVLink, KV Packet, SemPIC, COMB) as the primary path. They are stretch goals, because a general engine can ship training-free methods without per-model training **[my call]**.
- Decode-time KV selection (Quest-style), KV compression/streaming (CacheGen-style), and multi-GPU.

## 4. Anti-goals (a failure even if it "works")

- Speedups reported on benchmarks that overstate position-independent reuse accuracy. Two 2026 papers argue current evaluations do; results must include hard cases (cross-chunk dependencies that matter), not just needle-style tasks.
- Quality loss that is invisible to aggregate metrics but breaks code (wrong symbol resolution). Code tasks need an execution- or exact-match-style check, not only a fuzzy score.
- A cache that is correct only for one model/quant/RoPE configuration with no key to detect mismatch (stale or wrong-model cache silently used).
- Silent behavioural change to existing dotLLM paths (prefix cache, snapshots, speculative decoding, MTP).

## 5. Constraints

- Hardware: AMD Strix Halo (Vulkan is the GPU path; ROCm kernel-load broken; ~64 GiB shared GPU cap). CUDA runs only on the remote T5500 (RTX 3060, 12 GB) and **GPU work there needs the user's approval each time** (see `~/.claude/OTHER_MACHINES.md`). Read `STRIX_HALO.md`, `LLMs.md` before choosing where to run.
- Models come from the default HF/Ollama caches via links, never ad-hoc copies; weights stay out of git.
- dotLLM facts learned in recon (docs, not yet code-verified): C#/.NET 10; backends CPU, CUDA, Vulkan; `IKvCache` (`Update`, `GetKeys/GetValues`, `Rollback`, `CurrentLength`) in `src/DotLLM.Core/Attention/IKvCache.cs`; paged KV, prefix caching, prefix snapshots with restore/growth on CPU and Vulkan; Q8_0/Q4_0 KV; diagnostic hooks (`IInferenceHook`) for activation capture; no position-independent / non-prefix reuse today.
- Target model Qwen3.8-Flash-Next (`qwen4exp`, 176B total / 6B active MoE, MTP) mixes Gated DeltaNet recurrent layers with a minority of full-attention layers. Recurrent layers carry state that depends on the whole prefix, so attention-only blending methods do not apply to them directly. The actual layer split and the state shapes are **unverified** and are a first research task.

## 6. Decided by the user

- Build and prove directly in dotLLM (no separate Python prototype as the main route).
- The proof may start on a smaller, simpler model (ordinary attention throughout); Flash-Next is the later target once the recurrent-layer question is answered.
- Ideal target model: Qwen3.8-Flash-Next. Scale of interest: up to and beyond 1M tokens; any active repo under `C:\Development` is a candidate corpus.
- Research first, then implementation. Step 0 (fresh literature/tooling research) still gates the experiments; stop and report after Step 0, after the baseline is reproduced, and after the structure-aware selection result (E4).
- Coordination with the dotLLM project goes through its active Claude session when needed.

## 7. Plan shape (my calls)

**Phase R - research (Step 0).** Finish `research/landscape.md`. A first literature sweep on chunk KV reuse is done (see section 9). Still to do: (a) code-aware/structure-aware KV reuse and repo-level incremental caching; (b) per-layer deviation and MoE routing drift; (c) reuse of recurrent/linear-attention (GDN, Mamba) state across chunks, which the first sweep did not cover; (d) llama.cpp/other local-runtime support. Output includes a verdict on each hypothesised gap in the brief and a pivot if one is closed.

**Phase P - proof model.** Use a pure-attention GQA model that dotLLM already runs and verifies on Vulkan: Qwen3-4B-Instruct-2507 first (same family as the target, long native context), Llama-3.1-8B as a second model **[my call]**. Run the brief's E1 (naive concatenation vs full prefill), then reimplemented baselines (CacheBlend-style deviation selection, EPIC-style first-k with k=16, a ProphetKV-style query-relevance selector, the combined method from arXiv 2603.20218, each also run on contiguous token runs; CacheClip, SpecCache, RelaxKV are stretch), E3 (per-layer deviation profile through the diagnostic hooks), E4 (reference-graph selection, the core novelty), E5-E7 as scoped by the results.

**Phase T - target model.** Characterise `qwen4exp`: which layers are recurrent vs attention, what a chunk's reusable state is, whether chunk states can be composed or corrected. Decide per layer type: reuse as-is, recompute, or approximate. Revised after Step 0: recurrent-state reuse already exists (HYPIC, LinearKV, Priming), so this phase reproduces LinearKV (one cached state per GDN layer plus our selectors) as the primary baseline, compares HYPIC-style composition, and adds the MoE routing-drift experiment (E6); the open contributions are graph-guided repair positions and routing drift. The Flash-Next layer split is still unverified (Qwen3.8-27B is reported as 48 GDN + 16 full-attention).

**Phase S - ship.** Persistent content-addressed chunk store (key includes model identity/quant, tokenizer, chunk text hash, RoPE/position parameters, engine version), mmap read path, incremental invalidation on file change, a dotLLM API/CLI/server surface, tests, docs. Work on a dotLLM feature branch; touch `IKvCache`/engine interfaces only after agreeing with the dotLLM session.

**Evaluation data (my call):** code QA/completion on two or three repos from `C:\Development` (chosen for language mix and size, one deliberately larger than a single context window) plus a public repo-level benchmark found in Step 0; multi-document QA (HotpotQA/MuSiQue/2Wiki) only for comparability with published numbers. Revised after Step 0: apply the Boxoffice-style filtering (arXiv 2609.31415) and report normalised F1, since unfiltered numbers overstate reuse accuracy (CacheBlend on 2WikiMQA 0.87 -> 0.52); the file-edit experiment (E7) adds an edit-local repair baseline (K=32) and an axis for the distance between the edit and its dependent text.

## 8. Success criteria

- E4: reference-graph (or hybrid) selection matches or beats the best baseline selector's quality at the same recompute budget, or matches it at a lower budget, with near-zero runtime selection cost.
- A clear answer on layer-tiered recompute (E3/E5).
- A written answer on what is reusable for recurrent layers in `qwen4exp`, with measured quality.
- On the target model and hardware, a measured TTFT improvement at long context (at least 32K, with 262K reported) against full prefill and against existing dotLLM prefix reuse, with the quality delta reported alongside.
- Everything reproducible from `experiments/<name>/` with config, script, raw results and README.

## 9. Research state so far (unverified claims from a first sweep; do not cite without checking)

Reported by a research agent from abstracts and snippets on 2026-10-30:

- Newer selectors report beating CacheBlend at equal recompute budget: ProphetKV (query relevance), CacheClip (auxiliary model; argues early-layer selection misses deep-layer dependencies — the chunk-start clustering finding is from arXiv 2603.20218, corrected after verification), SpecCache (ACL 2026).
- "Contiguity, Not Importance" (Sep 2026): after a document edit, recomputing a contiguous window around the edit beats scattered important tokens; relevant to incremental update on file changes.
- Trained alternatives: KV Packet (NeurIPS 2026), SemPIC, COMB; plus a concatenation-aware fine-tune + selective recompute paper.
- Evaluation caveats: an experimental study of chunk-level caching and a paper arguing PIC accuracy is overstated (Boxoffice dataset generator).
- Tooling: vLLM non-prefix reuse RFC reportedly closed as not planned; SGLang RFC auto-closed; MiniPIC (IBM, vLLM fork) is a practical reference.
- No code-aware or reference-graph-guided KV reuse found, but only a few searches ran. Per-layer deviation / MoE drift and recurrent-state reuse were not searched.

## 10b. Model ladder and ship scope

User answers: an attention-only first release is acceptable; start with a smaller model and work upwards; prefer a Qwen3.8 model (or "Flint", read here as dotLLM's Recursive Flint) if suitable, otherwise whatever proves the idea best.

Assessment from `LLMs.md` and dotLLM `SUPPORTED_MODELS.md` (docs only, to be re-verified) **[my call]**:
1. **Qwen3-4B-Instruct-2507** first: pure attention, passes on dotLLM Vulkan, fast iteration, same family as the target. Optional second pass on `Ma7ee7/Qwen3.8_4B_Distilled` (a third-party distil that is `qwen3` underneath), to see whether it behaves the same.
2. **Llama-3.1-8B** next: different RoPE/GQA shape, so results do not depend on one family.
3. **Recursive Flint** later, as a research probe rather than a first model: 25 GB MoE, 35 sliding-window layers (window 513) plus 14 full-attention layers with no positional encoding (NoPE). NoPE layers need no RoPE re-rotation, and window layers only see nearby tokens, so Flint may suit chunk reuse unusually well. But Vulkan refuses it today and there is no compact sliding-window KV yet, so it runs on CPU or the T5500.
4. **Qwen3.8-27B / OmniCoder-9B** (hybrid dense) and **Qwen3.8-Flash-Next** (`qwen4exp`) are recurrent hybrids: Phase T.

Ship scope: an attention-only first release is acceptable; Flash-Next is a stretch goal. The cache format starts attention-only, but the cache key carries a layer-type field so recurrent-layer entries can be added later.

User answers on release and Flint: "published" means a push to dotLLM `dev` (every passing push builds a `0.3.0-dev.<n>` prerelease with packages) plus confirming the release reaches NuGet (tool package `dotllm`, trusted publishing per `dotLLM/docs/PACKAGING.md`; the `DotLLM.*` libraries are not published). The user will ask the dotLLM session to fix Flint's Vulkan loading (tracked in dotLLM #1157 / #1171) so Flint can be paired with this work; this project does not take that fix on itself.

## 10a. Calls added after the builder review (all **[my call]**, change freely)

- **Quality bar:** at most 20% recompute and at least 95% of full-prefill score on code exact-match/execution tasks counts as "light and good enough". E4 is judged against the best baseline selector at equal budget, and also against this floor.
- **If E4 fails:** report at the gate, then continue. The baseline selectors, the persistent chunk store and the Phase T work still have value; the structure-aware selector simply is not claimed as a contribution.
- **dotLLM changes:** prototype on a dotLLM feature branch; nothing touching `IKvCache` or engine interfaces is proposed upstream until agreed with `dotllm-b7`, which is reachable by message from this session.
- **Reference graph:** a hypothesis, not a fixed claim. Start with tree-sitter and one language (C#, since dotLLM and most of the user's repos are C#), with cross-file symbol resolution by name matching; language servers and more languages only if E4 shows promise.
- **Model availability:** `LLMs.md` records Qwen3-4B-Instruct-2507 and Llama-3.1-8B as passing on dotLLM Vulkan; the first task is to re-verify that on current `dev`.
- **Compute budget:** multi-seed comparisons run at 4K-32K context; 128K and 262K are single-configuration confirmation runs, scheduled so the shared box is not tied up for days.

## 10c. Solution-level cache-building tooling (user request, 2026-10-31)

The user wants tools that run over a .NET solution to pre-generate cache blocks per method and/or per file, so methods and files can be compared, plus tools to select which files go into a context. Roslyn can give deeper information for .NET solutions than syntax alone. Planned shape **[my call]**:

- A `dotllm`-style CLI verb group (working name `chunkcache`): `build` (open a solution or project with Roslyn's MSBuildWorkspace, chunk by method / type / file, encode and store the chunks), `select` (choose files or symbols for a context: explicit paths and globs, a symbol and its dependency neighbourhood from the reference graph, or recently changed files from git), `compare` (run the same task over different chunkings / selectors / budgets and emit a quality-versus-prefill table), `status` (which chunks are stale after edits), and `evict`.
- Roslyn supplies: semantic symbol resolution across projects (definitions, references, call and inheritance edges, using/import edges), symbol-level boundaries including partial classes and generated-code detection, and a project dependency graph. The chunk key hashes the chunk's token ids plus the model fingerprint, so an edit invalidates only the chunks it touches.
- Order of work: Tasks 8 and 9 of the phase R/P plan already build the Roslyn chunker and reference graph as library code (the foundation); the CLI, the persistent store and the selection tools belong to the Phase S plan, written after the E4 gate. The experiment harness (`ChunkKvLab`) gets a `--select` option early if it helps Task 8 pick corpora.
- Non-goals for now: languages other than C# (tree-sitter later), IDE integration.

## 10. Left to the builder

Chunking granularity and tree-sitter integration from C#; the on-disk format and eviction policy; exact experiment ordering inside each phase after Phase R; selector implementations; which public benchmark to adopt; naming and the public API shape (agreed with the dotLLM session).
