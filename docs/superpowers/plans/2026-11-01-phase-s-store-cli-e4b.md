# Phase S (store, CLI, release) and E4b (related-chunk contexts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chunk-level KV reuse usable on real .NET solutions: a persistent content-addressed chunk store with incremental invalidation, Roslyn-driven build/select/compare tooling (`chunkcache`), a fair test of the structure-aware idea on related-chunk contexts (E4b), and a release path through dotLLM to NuGet.

**Architecture:** Library code stays in `src/DotLLM.ChunkReuse` (C# / .NET 10, dotLLM worktree). The store holds per-chunk KV in the model's native KV precision, keyed by a hash of model fingerprint, tokenizer, RoPE parameters, engine version and chunk tokens. The CLI lives in a separate tool project until the dotLLM lead agrees to host the verb group. Default recipe from G2: fixed-size chunks, chunk-start plus query-relevance selection; the reference graph is an optional signal.

**Tech Stack:** C#/.NET 10, Roslyn (`Microsoft.CodeAnalysis.CSharp`, `Microsoft.CodeAnalysis.Workspaces.MSBuild`, `Microsoft.Build.Locator`), dotLLM CPU and Vulkan backends, xUnit.

**Spec:** `docs/superpowers/specs/2026-10-31-chunk-kv-reuse-design.md` (sections 7 Phase S, 10c). Findings so far: `REPORT.md`, `experiments/E4-structure-aware/README.md`.

## Global Constraints

- Work in the dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse` (branch `feature/chunk-kv-reuse`); nothing is pushed, and no dotLLM issue or PR is opened without the user's approval. dotLLM rules: issue first, PRs target `dev`, one issue per PR, small diffs, rebase on `dev` often.
- Correctness tests must fail against a wrong implementation (mutation evidence in each task report); run mutants in a `git archive` scratch copy, never in the live worktree while jobs run.
- Precision rules: no new F32 hot-path storage; quantized KV stays quantized; the store writes the cache's native dtype.
- Do not edit Vulkan code (owned by the dotLLM session, issue jamesburton/dotLLM#1531). CPU is the correctness oracle; Vulkan runs are only for timing and parity once #1531 primitives land.
- GPU on the T5500 needs the user's approval each time. The local iGPU is fine.
- Every experiment: at least 3 seeds, paired bootstrap clustered by definition, provenance (commit, dirty=0, snapshot hashes, model revision), logs force-added.
- Speed checkpoint (user request): each task that adds a runtime path records a timing against the previous path (CPU per-run `Forward` vs single-pass once #1531 step 3 lands).

## Review Focus

- Model, tokenizer or RoPE parameter change must be a store miss, never a wrong hit (test: same chunk text, different fingerprint).
- Torn or concurrent writes: a crash mid-write must not leave a loadable corrupt entry (atomic rename; test with truncated file).
- An edit inside a method invalidates only that chunk (and fixed-size neighbours that shift); `status` must list exactly the stale ones.
- Identical chunk text in two files dedupes to one entry but both files resolve to it.
- Solution load failures (missing SDK, unresolved references, non-C# projects) report which projects were skipped and why; they never abort silently.
- 1.5M-token repo: the build streams chunk by chunk with bounded memory, and the store size and read path (mmap) are reported.

---

### Task 1: E4b related-chunk contexts

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Corpus/RelatedContextBuilder.cs`
- Modify: `benchmarks/ChunkKvLab/E4Command.cs` (add `--context-kind related|random`)
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/RelatedContextBuilderTests.cs`
- Create (here): `experiments/E4b-related-contexts/` with `run.ps1`, `README.md`; append a section to `REPORT.md`

**Interfaces:**
- Consumes: `Corpus`, `CodeTask`, `ReferenceGraph` (Tasks 8, 9 of the previous plan), `E4Command` arms.
- Produces: `RelatedContextBuilder.Build(Corpus corpus, CodeTask task, ReferenceGraph graph, int contextTokens, double relatedFraction, int seed) -> ContextPlan` where related chunks come from files within two reference-graph hops of the calling file (excluding the answer's masked span), the required chunk is always included, and the remaining budget is filled with random distractors.

- [ ] **Step 1: Write failing tests** `Related_RequiredChunkAlwaysIncluded`; `Related_FractionRespected_WithinOneChunk`; `Related_NoChunkFromOutsideTwoHopsUnlessFilling`; `Related_SameSeed_SameContext`; `Related_MaskedTextNeverInContext` (the masked callee text may not be reachable through query edges).
- [ ] **Step 2:** Run `--filter RelatedContextBuilderTests`; expected FAIL.
- [ ] **Step 3:** Implement the builder; fraction 0.5 by default (half of the non-required chunks are related). Reuse the cluster key (definition file) from E4.
- [ ] **Step 4:** Rerun; expected PASS; add mutation evidence.
- [ ] **Step 5:** Run E4 arms (Naive, ChunkStarts, QueryRelevance, Graph, Hybrid(QR), oracle) on related contexts, both chunkers, 3 seeds, same validated tasks, CPU. State plainly whether Graph or Hybrid now beats QR at equal budget and where the graph signal helps; report fraction of instances with a query target and in-context cross-chunk edges per context.
- [ ] **Step 6:** Write the README and REPORT.md section; commit both repos.

### Task 2: Chunk key, fingerprint and on-disk store

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Store/ChunkKey.cs`, `IChunkStore.cs`, `FileChunkStore.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkStoreTests.cs`

**Interfaces:**
- Consumes: `ChunkKvEntry`, `ChunkFingerprint` (existing).
- Produces: `readonly record struct ChunkKey(string Hex)` with `ChunkKey.Create(ModelFingerprint model, string tokenizerId, RopeParameters rope, string engineVersion, ReadOnlySpan<int> tokenIds)`; `interface IChunkStore { bool TryGet(ChunkKey key, out ChunkKvEntry entry); void Put(ChunkKey key, ChunkKvEntry entry); bool Contains(ChunkKey key); IEnumerable<ChunkKey> Keys(); long TotalBytes { get; } void Evict(ChunkKey key); }`; `FileChunkStore(string root)` (sharded directories, header with format version, KV in the entry's native dtype, mmap read, write to temp file then atomic rename).

- [ ] **Step 1: Write failing tests:** `Key_DiffersWhenModelTokenizerRopeOrEngineVersionChanges` (four variants); `Key_SameInputs_SameKey`; `Store_RoundTrip_IsBitExact`; `Store_TruncatedFile_IsTreatedAsMiss`; `Store_ConcurrentPutSameKey_LeavesOneValidEntry`; `Store_IdenticalChunksFromTwoFiles_OneEntry`; `Store_FormatVersionMismatch_IsMiss`.
- [ ] **Step 2:** Run `--filter ChunkStoreTests`; expected FAIL.
- [ ] **Step 3:** Implement. Hash with SHA-256 over a length-prefixed canonical encoding of all fields.
- [ ] **Step 4:** Rerun; expected PASS; mutation evidence (drop one key field, skip atomic rename, skip header check).
- [ ] **Step 5:** Measure bytes per token per layer for Qwen3-4B Q4_K_M and write it to `experiments/store/README.md`; commit.

### Task 3: Store-backed assembly parity

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Store/StoredContextAssembler.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/StoredAssemblyTests.cs`

**Interfaces:**
- Consumes: `IChunkStore`, `ChunkEncoder`, `ChunkAssembler`.
- Produces: `StoredContextAssembler.Assemble(IReadOnlyList<Chunk> chunks, IModel model, IChunkStore store) -> (ChunkedContext Context, AssemblyStats Stats)` where `AssemblyStats(int Hits, int Misses, long EncodedTokens)`; misses are encoded and stored.

- [ ] **Step 1: Write failing tests:** `Assemble_FromStore_EqualsFreshEncode_BitExact` (on the tiny test model); `Assemble_SecondCall_AllHits`; `Assemble_ModelChanged_AllMisses`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** Rerun; expected PASS with mutation evidence.
- [ ] **Step 5:** On Qwen3-4B (CPU) compare quality from stored versus fresh chunks on 20 E4 contexts (identical results expected) and record cold versus warm assembly time; commit.

### Task 4: Index, status and incremental invalidation

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Store/ChunkIndex.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkIndexTests.cs`

**Interfaces:**
- Produces: `ChunkIndex.Update(IReadOnlyList<SourceFile> files, IChunker chunker, ...) -> IndexDiff(IReadOnlyList<ChunkRef> Added, IReadOnlyList<ChunkRef> Removed, IReadOnlyList<ChunkRef> Unchanged)`; `ChunkIndex.Status(IChunkStore store) -> StatusReport` listing stale or missing chunks by file and line range. The index persists as JSON next to the store.

- [ ] **Step 1: Write failing tests:** `Edit_InsideOneMethod_ChangesOnlyThatSymbolChunk`; `Edit_ShiftsFixedChunks_FromEditPointOnly`; `Status_ListsExactlyMissingChunks`; `DeletedFile_RemovesItsChunks_ButSharedEntriesStay`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** Rerun; PASS with mutants.
- [ ] **Step 5:** Simulate 100 single-method edits on the codesharp snapshot; report re-encoded tokens per edit for symbol versus fixed chunking (the E7 incremental-re-encode result) and write `experiments/E7-incremental/README.md`; commit.

### Task 5: Solution scanner (Roslyn workspace)

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Corpus/SolutionScanner.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/SolutionScannerTests.cs` (small fixture solution under `tests/.../Fixtures/MiniSolution`)

**Interfaces:**
- Produces: `SolutionScanner.LoadAsync(string slnOrProjectPath, CancellationToken) -> ScanResult(IReadOnlyList<SourceFile> Files, IReadOnlyList<SkippedProject> Skipped)`; the reference graph can be built with real project references instead of BCL-only (`RoslynGraphBuilder` accepts a compilation per project).

- [ ] **Step 1: Write failing tests:** `Scan_FixtureSolution_ReturnsAllCSharpFiles`; `Scan_ProjectFailsToLoad_IsReportedInSkipped`; `Scan_GeneratedFiles_AreFlagged`; `Graph_WithProjectReferences_ResolvesCrossProjectCall` (a call that BCL-only resolution cannot resolve).
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement with `MSBuildLocator`. **Step 4:** Rerun; PASS with mutants.
- [ ] **Step 5:** Run on dotLLM itself; report files, projects, skipped, and resolved-call share versus BCL-only; commit.

### Task 6: Selection tools

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Tooling/ContextSelector.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ContextSelectorTests.cs`

**Interfaces:**
- Produces: `ContextSelector.Select(SelectionRequest request, ScanResult scan, ReferenceGraph graph, IGitInfo git) -> IReadOnlyList<ChunkRef>`; `SelectionRequest` has any of `Paths` (globs), `Symbol` plus `Hops`, `ChangedSince` (git ref), and a `TokenBudget`; result order is deterministic and trimmed to the budget with the reason recorded per chunk.

- [ ] **Step 1: Write failing tests:** `Select_Glob_ReturnsMatchingFiles`; `Select_SymbolNeighbourhood_IncludesDefinitionAndCallersWithinHops`; `Select_ChangedSince_UsesGitDiff` (fake `IGitInfo`); `Select_OverBudget_TrimsLowestPriorityFirst`; `Select_Deterministic`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** Rerun; PASS with mutants. **Step 5:** Commit.

### Task 7: `chunkcache` CLI and compare

**Files:**
- Create (dotLLM): `tools/DotLLM.ChunkCache/` (console project: `Program.cs`, `BuildCommand.cs`, `SelectCommand.cs`, `CompareCommand.cs`, `StatusCommand.cs`, `EvictCommand.cs`)
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkCacheCliTests.cs`

**Interfaces:**
- Consumes: Tasks 2-6, selectors from the previous plan.
- Produces: `chunkcache build --solution X --model M --store DIR [--chunker symbol|fixed --chunk-tokens 512]`; `select`; `status`; `evict`; `compare --task FILE --selectors a,b --budgets 5,10,20 --chunkers fixed,symbol` printing a quality-versus-prefill table (KL, top-1, tokens recomputed, forward calls, wall time for reuse and for full prefill). Compare uses the single-pass recompute path when available and says which path produced each timing.

- [ ] **Step 1: Write failing tests:** exit codes and output for each verb on the fixture solution with the tiny test model; `Compare_PrintsTableWithBothPaths`; `Build_Rerun_IsAllHits`; `Build_SkippedProject_ExitsNonZeroOnlyWithStrictFlag`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** Rerun; PASS. **Step 5:** Run on the dotLLM solution with Qwen3-4B (CPU) and record build time, store size and a compare table in `experiments/chunkcache-demo/README.md`; commit.

### Task 8: Speed checkpoint on Vulkan (gated on jamesburton/dotLLM#1531)

**Files:**
- Create (here): `experiments/speed-vulkan/` with `run.ps1`, `README.md`

- [ ] **Step 1:** When the dotLLM session reports #1531 steps merged, rebase the worktree onto `dev` and run the tiny-model and Qwen3-4B parity tests against the CPU oracle (tolerances from the PRs).
- [ ] **Step 2:** Re-run the E4 core arms (ChunkStarts, QR, Hybrid) at 2K, 8K, 32K contexts on the local Vulkan iGPU; report quality versus the CPU oracle, time-to-first-token for full prefill versus reuse (store warm), and speedup with variance over 3 runs. Say which attention path was used.
- [ ] **Step 3:** Write the README; commit; report to the user.

### Task 9: Release path

**Files:**
- Create (here): `docs/release/chunkcache-release-plan.md`

- [ ] **Step 1:** Read `dotLLM/docs/PACKAGING.md`; list what the NuGet trusted-publishing setup needs from the user's account (package id, repo, workflow, environment) and which packages change (`DotLLM.ChunkReuse` library, `dotllm` tool vs a separate `chunkcache` tool).
- [ ] **Step 2:** With the dotLLM lead, agree the PR split (internal bits C1/C4/C7, ChunkReuse library, CLI) and draft issue text for each; do not file anything until the user approves.
- [ ] **Step 3:** Commit the plan and report to the user for the go-ahead.

---

## Self-review notes

- Spec coverage: Phase S (store, mmap, invalidation, API/CLI, tests, docs) is Tasks 2-4, 7, 9; spec 10c (build/select/compare/status/evict, Roslyn, git changed files) is Tasks 5-7; the E4 fairness gap is Task 1; the speed checkpoint requested by the user is Task 8 and the Global Constraints. Phase T (recurrent layers) is a separate plan, coordinated with the dotLLM Flash-Next agent.
- Order: Task 1 (CPU, independent) and Tasks 2-4 can run in parallel with the dotLLM session's Vulkan PRs; Task 8 waits for them.
