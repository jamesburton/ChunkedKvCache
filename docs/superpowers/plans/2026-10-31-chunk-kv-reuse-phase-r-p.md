# Chunk KV Reuse — Phase R and Phase P Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Step 0 research, then build and measure chunk-level KV reuse with selective recompute inside dotLLM on a pure-attention model, up to and including the structure-aware selection result (E4).

**Architecture:** Research artefacts and results live in this repo (`C:\Development\ChunkedkvCache`). Code lives in the dotLLM fork (`C:\Development\dotLLM`, branch `feature/chunk-kv-reuse` off `dev`) in a new library `src/DotLLM.ChunkReuse`, a lab console `benchmarks/ChunkKvLab`, and unit tests under `tests/DotLLM.Tests.Unit/ChunkReuse`. No existing dotLLM interface (`IKvCache`, `IModel`) changes in this plan; where the recompute step needs layer-level control it is added as a new opt-in interface on the CPU model only, and any change to shared interfaces waits for agreement with the dotLLM session (`dotllm-b7`).

**Tech Stack:** C# / .NET 10 (dotLLM), xUnit (dotLLM's existing test projects), Roslyn (`Microsoft.CodeAnalysis`) for the C# reference graph, PowerShell for experiment drivers, CSV/JSON results.

**Spec:** `docs/superpowers/specs/2026-10-31-chunk-kv-reuse-design.md` (read with `INCEPTION.md`).

**Later plans (not in this one):** Phase T (recurrent-layer state in `qwen4exp`) and Phase S (persistent content-addressed store, NuGet-visible release) get their own plans after the E4 gate, because their shape depends on its result.

## Global Constraints

- Hardware: AMD Strix Halo; Vulkan is the GPU path; ROCm kernel-load broken; ~64 GiB shared GPU cap. The T5500 (CUDA, 12 GB) is used only after the user approves each GPU run.
- Models come from the default HF cache via `hf download`/`from_pretrained` or existing links; never copy weights into project folders; weights stay out of git.
- Proof models, in order: Qwen3-4B-Instruct-2507, then Llama-3.1-8B. Quality bar: at most 20% recompute and at least 95% of full-prefill score on code exact-match tasks.
- Multi-seed results use at least 3 seeds or query sets and report variance; 128K/262K are single confirmation runs.
- Record exact model revision, dotLLM commit, .NET SDK version and hardware for every run.
- Stop and report at: end of Task 1 (Step 0), end of Task 7 (baseline gate), end of Task 11 (E4).
- Nothing in dotLLM changes behaviour of the existing prefix cache, snapshots, speculative decoding or MTP.
- Pushes to dotLLM `dev` build prerelease packages; this plan pushes only the feature branch.

## Review Focus

- Chunk tokenised alone differs from the same text tokenised in context (BPE merges across the boundary): expectation is that assembly always works on token ids fixed up front, never re-tokenised text.
- Cache entry from a different model/quant/tokenizer/RoPE setting: expectation is a hard rejection, never silent reuse.
- Empty chunk, one-token chunk, chunk longer than the context limit, and the same chunk used twice in one request: expectation is a clear result or a clear exception, not corrupted positions.
- Chunks assembled in a different order than they were encoded: expectation is correct position shifts (K re-rotated by the position delta) and different outputs only through attention, not through position bugs.
- Quantised KV (Q8_0/Q4_0) as destination: expectation is that re-rotation either works on dequantised values or the experiment refuses the combination explicitly.

---

### Task 1: Finish Step 0 research and write `research/landscape.md`

**Files:**
- Create: `research/landscape.md`, `research/sources/` (one note per verified paper)
- Modify: `INCEPTION.md` (only if a gap closes; otherwise add `plan-v2.md`)

**Interfaces:**
- Produces: a verdict table that Tasks 5-11 read: for each hypothesised gap (structure-aware selection, content-aware chunking with incremental re-encode, per-layer/MoE-drift profiling, recurrent-state reuse) one of `open | partly covered | done`, with citations.

- [ ] **Step 1: Run three parallel research agents** (extended web search), one per remaining scope: (a) code-aware / graph-guided / repo-level / incremental-edit KV reuse; (b) per-layer KV deviation, layer-tiered recompute, MoE routing drift; (c) reuse of recurrent / linear-attention state (Gated DeltaNet, Mamba) across independently encoded chunks, plus llama.cpp and other local-runtime support. Each returns a table of verified papers with URL, year, venue, method, reported result, code link, and marks unverified items.
- [ ] **Step 2: Verify the first sweep's key claims against primary sources** (arXiv abstract plus method section): ProphetKV, CacheClip, SpecCache, "Contiguity, Not Importance", KV Packet, MiniPIC, and the two evaluation papers. Drop or flag anything that cannot be confirmed.
- [ ] **Step 3: Write `research/landscape.md`** with the reference table (paper, year, venue, link, method class, reported speedup/quality, code yes/no), the verdict table above, and a recommended pivot if a gap is closed.
- [ ] **Step 4: Check it** — every table row has a URL; every verdict cites at least one source or says "searched, none found" with the queries used.
- [ ] **Step 5: Commit** `research/` in this repo.
- [ ] **Step 6: GATE G0** — report to the user: verdicts, any pivot, and whether sections 7-8 of the spec change. Do not start Task 2 coding until the user says go.

### Task 2: Prove the dotLLM baseline runs and branch it

**Files:**
- Create (dotLLM): branch `feature/chunk-kv-reuse`
- Create (here): `experiments/00-baseline/README.md`

**Interfaces:**
- Produces: a recorded, reproducible command that loads Qwen3-4B-Instruct-2507 on CPU and on Vulkan and prints a greedy completion, plus the dotLLM commit id, SDK version and driver versions.

- [ ] **Step 1:** In `C:\Development\dotLLM`, read `.docs/HANDOFF.md` if present, then `git switch -c feature/chunk-kv-reuse dev`.
- [ ] **Step 2:** Build (`dotnet build`) and run the existing unit tests for the KV/prefix areas (`dotnet test tests/DotLLM.Tests.Unit --filter "FullyQualifiedName~Engine"`); expected: build succeeds, tests pass or the pre-existing failures are listed in the README.
- [ ] **Step 3:** Fetch Qwen3-4B-Instruct-2507 GGUF into the HF cache (`hf download`), link per the model-storage rule if a plain path is needed; run a 64-token greedy completion with the dotLLM CLI on `--device cpu` and on Vulkan; expected: coherent text on both, and similar top tokens.
- [ ] **Step 4:** Write the commands, versions and outputs in `experiments/00-baseline/README.md`; commit there.

### Task 3: Code-verified map of the KV and prefill path

**Files:**
- Create: `experiments/01-dotllm-map/README.md`

**Interfaces:**
- Produces: written answers, with file:line references, to the questions Tasks 4-6 depend on.

- [ ] **Step 1:** Answer from the code (not the docs): (a) is K stored in `SimpleKvCache`/`PagedKvCache` before or after RoPE, and in what dtype; (b) how `TextGenerator` prefill calls `IModel.Forward` with a cache and positions, and whether a cache can be pre-filled externally and then continued; (c) where the CPU `TransformerModel` layer loop lives and whether its per-layer step can be driven for a subset of tokens; (d) how `IInferenceHook` exposes per-layer activations and whether K/V are reachable; (e) what Vulkan needs for externally filled KV.
- [ ] **Step 2:** Mark each answer `verified-by-code` or `still unknown`, and list the smallest dotLLM change each unknown would need.
- [ ] **Step 3:** Message `dotllm-b7` with the list of proposed changes and ask for objections before Task 6 starts; record its reply in the README.
- [ ] **Step 4:** Commit.

### Task 4: Chunk encoder and RoPE-shifted assembly (E1 building block)

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/DotLLM.ChunkReuse.csproj`, `ChunkKvEntry.cs`, `ChunkEncoder.cs`, `ChunkAssembler.cs`, `RopeShift.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkAssemblyTests.cs`

**Interfaces:**
- Produces: `record ChunkKvEntry(string ModelFingerprint, int[] TokenIds, float[][] KeysPerLayer, float[][] ValuesPerLayer)` with keys stored position-independent (as encoded at positions 0..n-1 in isolation); `ChunkKvEntry ChunkEncoder.Encode(IModel model, ReadOnlySpan<int> tokenIds)`; `void ChunkAssembler.Assemble(IKvCache destination, IReadOnlyList<ChunkKvEntry> chunks, string expectedFingerprint)`; `void RopeShift.Apply(Span<float> keys, int headDim, int positionDelta, in RopeParameters rope)`.

- [ ] **Step 1: Write failing tests** in `ChunkAssemblyTests`: `RopeShift_ShiftedKeys_EqualKeysComputedAtTargetPosition` (synthetic tiny model fixture, F32, tolerance 1e-5); `SingleChunkAtOffsetZero_MatchesFullPrefillLogits` (tolerance 1e-4); `Assemble_WrongFingerprint_Throws`; `Assemble_EmptyChunk_ThrowsArgumentException`; `Assemble_SameChunkTwice_ProducesDistinctPositions`; `Assemble_ReorderedChunks_ShiftsByNewOffsets`; `Assemble_QuantizedDestination_ThrowsNotSupported`.
- [ ] **Step 2:** Run `dotnet test --filter "FullyQualifiedName~ChunkAssemblyTests"`; expected: FAIL (types missing).
- [ ] **Step 3:** Implement the types above. The encoder runs an isolated prefill on a fresh cache and copies out per-layer K/V; the assembler writes entries into the destination cache at running offsets, applying `RopeShift` to keys (or no shift when Task 3 shows K is stored pre-RoPE). Fingerprint = hash of model id, quant, tokenizer id, RoPE parameters, engine version.
- [ ] **Step 4:** Rerun; expected: all PASS.
- [ ] **Step 5:** Commit on `feature/chunk-kv-reuse`.

### Task 5: E1 harness — full prefill vs naive concatenation vs prefix reuse

**Files:**
- Create (dotLLM): `benchmarks/ChunkKvLab/ChunkKvLab.csproj`, `Program.cs`, `ContextBuilder.cs`, `Metrics.cs`
- Create (here): `experiments/E1-baselines/run.ps1`, `README.md`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/MetricsTests.cs`

**Interfaces:**
- Consumes: `ChunkEncoder`, `ChunkAssembler`.
- Produces: `record RunRow(string Method, int Seed, int ContextTokens, double Top1Agreement, double MeanKl, double ExactMatch, double TtftMs, long PrefillTokensComputed, long CacheBytes)`; CLI `ChunkKvLab e1 --model <path> --corpus <dir> --seeds 3 --out results.csv`.

- [ ] **Step 1: Write failing tests** `Metrics_KlOfIdenticalLogits_IsZero`, `Metrics_Top1Agreement_CountsMatchingArgmax`, `ContextBuilder_TokenizesChunksOnce_ConcatenatedIdsEqualPerChunkIds` (pins the tokenisation Review Focus).
- [ ] **Step 2:** Run the filter `MetricsTests`; expected FAIL.
- [ ] **Step 3:** Implement `Metrics` and `ContextBuilder`, and the E1 command: for each seed, build contexts from shuffled chunks, run full prefill (reference), naive concatenation (no recompute), and dotLLM's existing prefix reuse; write `RunRow` CSV.
- [ ] **Step 4:** Rerun tests; expected PASS. Then run E1 on Qwen3-4B-Instruct-2507, Vulkan, contexts 4K/8K/16K, 3 seeds; expected: CSV with all three methods; naive concatenation shows measurable quality loss versus full prefill (if it does not, stop and examine the metric before going on).
- [ ] **Step 5:** Write findings in `experiments/E1-baselines/README.md`; commit in both repos.

### Task 6: Selective recompute (CacheBlend-style layer-wise fix-up) on the CPU model

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/SelectiveRecomputer.cs`, `ISelectiveRecomputeModel.cs`
- Modify (dotLLM): CPU `TransformerModel` to implement `ISelectiveRecomputeModel` (file path confirmed in Task 3)
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/SelectiveRecomputeTests.cs`

**Interfaces:**
- Consumes: `ChunkKvEntry`, `ChunkAssembler` from Task 4; Task 3's answers on the layer loop.
- Produces: `interface ISelectiveRecomputeModel { void RecomputeTokens(IKvCache cache, ReadOnlySpan<int> tokenIds, ReadOnlySpan<int> positions, ReadOnlySpan<int> selectedIndices); }` and `SelectiveRecomputer.Run(ISelectiveRecomputeModel, IKvCache, IReadOnlyList<ChunkKvEntry>, ReadOnlySpan<int> selectedIndices)`.

- [ ] **Step 1: Write failing tests:** `Recompute_AllTokensSelected_MatchesFullPrefill` (tolerance 1e-4, synthetic model); `Recompute_NoTokensSelected_EqualsNaiveConcat`; `Recompute_Monotone_ErrorShrinksAsMoreTokensSelected` (KL non-increasing over 0/10/50/100% selection on the synthetic fixture, within noise).
- [ ] **Step 2:** Run `--filter SelectiveRecomputeTests`; expected FAIL.
- [ ] **Step 3:** Implement: for each layer, compute Q/K/V for selected tokens only, attend against the assembled cache (selected tokens' own entries replaced layer by layer), write refreshed K/V back, as in CacheBlend. Only the CPU model implements it; Vulkan follows after E4 only if results warrant.
- [ ] **Step 4:** Rerun; expected PASS.
- [ ] **Step 5:** Commit.

### Task 7: Baseline selectors and the baseline gate (G1)

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Selectors/` containing `IRecomputeSelector.cs`, `FirstKSelector.cs`, `ChunkStartsSelector.cs`, `DeviationTopKSelector.cs`, `RandomSelector.cs`, `QueryRelevanceSelector.cs` (ProphetKV-style), `CombinedSelector.cs` (arXiv 2603.20218), and a `ContiguousRuns` decorator that expands any selector's picks into contiguous runs
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/SelectorTests.cs`
- Create (here): `experiments/E2-baseline-selectors/`

**Interfaces:**
- Produces: `interface IRecomputeSelector { int[] Select(ChunkedContext context, int budgetTokens, int seed); }` returning sorted, distinct token indices, length exactly `budgetTokens` (or all tokens if fewer).

- [ ] **Step 1: Write failing tests:** `AllSelectors_ReturnExactBudget_SortedDistinct`; `RandomSelector_SameSeed_SameOutput_DifferentSeed_DifferentOutput`; `FirstKSelector_PicksFirstKTokensOfEachChunk`; `DeviationTopKSelector_RanksByLayer1KvDeviation` (fixture with a planted high-deviation token).
- [ ] **Step 2:** Run `--filter SelectorTests`; expected FAIL.
- [ ] **Step 3:** Implement the five selectors: EPIC-like first-k per chunk; CacheClip-observed chunk starts; CacheBlend-like top-k by layer-1 K/V deviation; random control; query-relevance (ProphetKV-like, attention mass from the query tokens).
- [ ] **Step 4:** Rerun; expected PASS.
- [ ] **Step 5:** Run the quality-versus-budget sweep (budgets 5/10/15/20%, 3 seeds) for every selector on Qwen3-4B-Instruct-2507; write `experiments/E2-baseline-selectors/README.md`. Expected qualitative pattern from the literature: all selectors beat naive concatenation; deviation and relevance selectors beat random; if not, debug the pipeline before continuing.
- [ ] **Step 6:** Commit; **GATE G1** — report to the user with the quality-versus-budget curves and whether the baselines behave as published.

### Task 8: Code corpus, chunkers and task generator

Note (Step 0): report normalised scores and filter tasks the reference run itself fails or gets right without the required chunk, as in the Boxoffice evaluation paper (arXiv 2609.31415).

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Corpus/FixedSizeChunker.cs`, `SymbolChunker.cs` (Roslyn), `CrossFileTaskGenerator.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/CorpusTests.cs`
- Create (here): `experiments/corpus.md` (chosen repos with commit ids)

**Interfaces:**
- Produces: `IReadOnlyList<Chunk> IChunker.Chunk(SourceFile file)` where `Chunk(string FilePath, int StartLine, int EndLine, int[] TokenIds)`; `IReadOnlyList<CodeTask> CrossFileTaskGenerator.Generate(Corpus corpus, int count, int seed)` where `CodeTask(string Prefix, string ExpectedContinuation, IReadOnlyList<Chunk> RequiredChunks, IReadOnlyList<Chunk> DistractorChunks)`.

- [ ] **Step 1: Write failing tests:** `SymbolChunker_SplitsAtMethodAndClassBoundaries`; `SymbolChunker_ChunksCoverFileWithoutOverlap`; `FixedSizeChunker_ProducesChunksOfAtMostN_Tokens`; `TaskGenerator_RequiredChunkContainsDefinitionOfMaskedSymbol`; `TaskGenerator_SameSeed_SameTasks`.
- [ ] **Step 2:** Run `--filter CorpusTests`; expected FAIL.
- [ ] **Step 3:** Pick 2-3 repos under `C:\Development` (C# mix; include one larger than a single context window) and record commit ids in `experiments/corpus.md`. Implement chunkers and the generator: mask a call site's callee and arguments, require the definition chunk plus distractors, expected continuation is the original text; scoring is exact match of the greedy continuation (and compiles-check if cheap).
- [ ] **Step 4:** Rerun; expected PASS. Generate 100 tasks per repo and run the full-prefill reference once to confirm the model solves a reasonable share (if near 0% or near 100%, retune task difficulty, since neither can separate methods).
- [ ] **Step 5:** Commit.

### Task 9: Reference graph from Roslyn

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Graph/ReferenceGraph.cs`, `RoslynGraphBuilder.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ReferenceGraphTests.cs`

**Interfaces:**
- Consumes: `Chunk` from Task 8.
- Produces: `record SymbolEdge(int UseTokenIndex, int DefinitionTokenIndex, SymbolEdgeKind Kind)` with `Kind` in `Definition | Use | Import | Call`; `ReferenceGraph RoslynGraphBuilder.Build(IReadOnlyList<SourceFile> files, IReadOnlyList<Chunk> chunks)`; `IReadOnlyList<SymbolEdge> ReferenceGraph.EdgesForContext(ChunkedContext ctx)` returning edges that cross chunk boundaries inside the context.

- [ ] **Step 1: Write failing tests** on a three-file fixture: `Graph_CallInFileB_LinksToDefinitionInFileA`; `Graph_UsingDirective_ProducesImportEdge`; `Graph_EdgesForContext_ExcludesIntraChunkEdges`; `Graph_UnresolvedSymbol_ProducesNoEdgeAndNoException`.
- [ ] **Step 2:** Run `--filter ReferenceGraphTests`; expected FAIL.
- [ ] **Step 3:** Implement with Roslyn semantic models (accurate symbol resolution for C#; tree-sitter stays for other languages later). Map syntax nodes to token indices through the chunk token offsets.
- [ ] **Step 4:** Rerun; expected PASS. Record graph build time per 100K tokens (selection should cost near zero at request time, since the graph is built when chunks are encoded).
- [ ] **Step 5:** Commit.

### Task 10: Per-layer deviation profile (E3)

Note (Step 0): arXiv 2603.20218 already profiles per-layer deviation; this task extends it by token role from the reference graph and must not claim the profile itself as new.

**Files:**
- Create (dotLLM): `benchmarks/ChunkKvLab/E3Command.cs`
- Create (here): `experiments/E3-layer-deviation/` with `run.ps1`, `plot.py` or equivalent, `README.md`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/DeviationTests.cs`

**Interfaces:**
- Consumes: `ChunkEncoder`, full-prefill KV capture via `IInferenceHook`.
- Produces: `deviation.csv` with columns `layer, token_index, token_role, kv_l2_deviation` where `token_role` in `ChunkStart | DefinitionSite | UseSite | Import | Other`; summary of the share of total deviation captured by the top-k% tokens per layer.

- [ ] **Step 1: Write failing tests:** `Deviation_IdenticalIsolatedAndFullKv_IsZero`; `Deviation_FirstChunk_IsZeroForAllTokens` (the first chunk sees the same prefix in both encodings).
- [ ] **Step 2:** Run `--filter DeviationTests`; expected FAIL.
- [ ] **Step 3:** Implement the command: for contexts from Task 8, capture per-layer K/V of full prefill and isolated chunk encoding, compute per-token L2 deviation after position alignment, label roles from the Task 9 graph.
- [ ] **Step 4:** Rerun; expected PASS. Run on 100 contexts, 3 seeds; produce heatmaps (layer by role) and the top-k% capture curves.
- [ ] **Step 5:** Write findings, including whether deviation concentrates in deeper layers and on definition/use sites; commit. These findings decide whether Task 11 also tests layer-tiered recompute (E5).

### Task 11: Structure-aware selection (E4) and the core gate (G2)

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Selectors/GraphSelector.cs`, `HybridSelector.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/GraphSelectorTests.cs`
- Create (here): `experiments/E4-structure-aware/`, `REPORT.md`

**Interfaces:**
- Consumes: `IRecomputeSelector` (Task 7), `ReferenceGraph` (Task 9).
- Produces: `GraphSelector : IRecomputeSelector` (definition sites, used symbols, import lines, ranked by cross-chunk edge count); `HybridSelector : IRecomputeSelector` (graph picks first, remaining budget filled by `DeviationTopKSelector`).

- [ ] **Step 1: Write failing tests:** `GraphSelector_PrefersTokensWithCrossChunkEdges`; `GraphSelector_NoEdges_FillsBudgetDeterministically`; `HybridSelector_ReturnsExactBudget_NoDuplicates`; `GraphSelector_SelectionTime_IsUnder1MsPer10KTokens` (static selection must cost near zero).
- [ ] **Step 2:** Run `--filter GraphSelectorTests`; expected FAIL.
- [ ] **Step 3:** Implement both selectors.
- [ ] **Step 4:** Rerun; expected PASS.
- [ ] **Step 5:** Run E4: the Task 7 selectors versus Graph and Hybrid at budgets 5/10/15/20%, both chunkers (fixed 512 and symbol), 3 seeds, Qwen3-4B-Instruct-2507; then repeat the best configuration on Llama-3.1-8B. If E3 pointed to depth concentration, add the layer-tiered arm (E5): recompute only layers at or beyond a threshold from E3.
- [ ] **Step 6:** Write `REPORT.md`: quality-versus-budget curves with variance, selection overhead, whether the success criterion (match or beat the best baseline at equal budget, or match at lower budget) was met, and whether the 95%/20% quality bar holds.
- [ ] **Step 7:** Commit; **GATE G2** — report to the user and agree the next plan: Phase T (recurrent layers in `qwen4exp`) and/or Phase S (persistent store and release).

---

## Self-review notes

- Spec coverage: goals 1-2 and 5 (Tasks 4-11), goal 3 and 4 (deferred to the Phase S plan, stated in the header), Phase R (Task 1), Phase P (Tasks 2-11), Flint pairing (left to the dotLLM session per the spec; no task here).
- Deviation from the spec worth the user's attention: the reference graph uses Roslyn for C#, not tree-sitter, because Roslyn resolves symbols accurately; tree-sitter stays for other languages later.
- Task 3 may change Tasks 4 and 6: if K is stored pre-RoPE or the CPU layer loop cannot be driven per token subset, those tasks adapt before coding starts.
