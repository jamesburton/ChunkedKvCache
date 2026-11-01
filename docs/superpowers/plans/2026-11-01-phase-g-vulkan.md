# Phase G (Vulkan iGPU port of chunk-KV reuse) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the whole chunk-reuse path (encode, store/read, RoPE shift, assemble, selective recompute, query-relevance probe) on the Vulkan iGPU, verified against the CPU path, and measure real time-to-first-token and quality at 2K to 32K contexts.

**Architecture:** An integration branch off dotLLM `dev` (which now has the Vulkan primitives from #1532-#1535) merges the existing `feature/chunk-kv-reuse` work. `DotLLM.ChunkReuse` gains a backend seam: CPU keeps the `SimpleKvCache` path (oracle); Vulkan uses `IPositionedHostKvCache.WriteRows/ReadRows`, `CopyRowsFrom`, `RopeShiftKvKernel.Shift`, `Forward(subsetIds, subsetPositions, cache)` and the Vulkan query-relevance probe. Every step is compared with a measured numerical floor, not exact equality.

**Tech Stack:** C#/.NET 10, dotLLM CPU + Vulkan backends (local Strix Halo iGPU), xUnit with `[SkippableFact]` GPU gating.

**Spec:** `docs/superpowers/specs/2026-10-31-chunk-kv-reuse-design.md`. Facts from the dotLLM session: merged PRs #1532 (public `IPositionedHostKvCache`, F32 and F16, plus device `CopyRowsFrom`), #1533 (K-only RoPE delta shift `RopeShiftKvKernel.Shift`, plain RoPE only; YaRN, freq factors and MLA must be refused by the caller), #1534 (per-query-position attention `ATTN_QPOS`, non-flash kernel, routed when positions are non-contiguous or a run sits inside a filled cache, requires F32 KV and no sinks), #1535 (probe: `probe.Begin` then `AttachQueryRelevanceProbe` then `Forward` then `ReadScores` then `cache.Rollback(L)`). Reported numerics floor: an 8-row forward versus a 96-row prefill differs by about 2e-2 relative L2 on K for Qwen3-4B Q4_K_M, because the Q4_K activation-quant paths depend on row count.

## Global Constraints

- Do not edit Vulkan code or shaders (owned by the dotLLM session). If a primitive is missing or wrong, write it up for them (issue text with a failing repro) instead of patching it.
- GPU runs use the dotLLM GPU lock (`scripts/gpu-lock.sh`; stale after 90 min, so long runs must refresh); GPU work queues FIFO behind the Flash-Next agent. The local iGPU is fine; the T5500 needs the user's approval each time. A Vulkan device-lost kills the process: disable the offending case statically, never catch-and-skip; kill and retry once on a silent stall.
- Tests that need the GPU use `[SkippableFact]`, `Skip.IfNot(VulkanDevice.IsAvailable())`, `DOTLLM_SKIP_VULKAN=1`, the existing GPU collection and `Trait Category=GPU`.
- `ChunkKey` and `ChunkFingerprint` carry a backend tag so CPU- and Vulkan-encoded chunks never mix.
- The oracle for Vulkan reuse is Vulkan full prefill; the CPU path is the cross-check. Report every parity result as a ratio to the measured floor (Task 2), never as bit equality.
- Correctness tests must fail against a wrong implementation (mutation evidence in a `git archive` scratch copy, never in the live worktree while jobs run). Provenance per run: commit, dirty=0, model revision, GPU lock holder, driver version.
- Nothing is pushed and no dotLLM issue or PR is opened without the user's approval; dotLLM rules apply (issue first, PRs to `dev`, small diffs, rebase on `dev` often).
- Each experiment reports at least 3 seeds with paired, cluster-bootstrapped intervals.

## Review Focus

- Chunk entries encoded on CPU must never be assembled into a Vulkan cache without an explicit conversion (backend tag mismatch is a miss).
- A model with YaRN, rope freq factors, MLA or attention sinks must be refused with a clear error before any Vulkan reuse, never silently mis-shifted.
- F16 versus F32 KV: the assembler must refuse a dtype it cannot write exactly (Qwen3 Vulkan KV is F32; Flint F16).
- Selective recompute where the selected set is all positions, one position, or the first/last position must equal the corresponding plain Vulkan path within the floor.
- A device-lost or stall mid-run must leave a log that says which job and step, and must not produce a partial CSV that looks complete.

---

### Task 1: Integration branch and backend seam

**Files:**
- Modify (dotLLM): `src/DotLLM.ChunkReuse/DotLLM.ChunkReuse.csproj` (reference `DotLLM.Vulkan`), `ChunkAssembler.cs`, `ChunkEncoder.cs`, `RopeShift.cs`, `ChunkFingerprint.cs`; `benchmarks/ChunkKvLab` (`--backend cpu|vulkan`, all-row logits enabled via `TrySetAllRowLogitsLimit`)
- Create (dotLLM): `src/DotLLM.ChunkReuse/Backends/IChunkBackend.cs`, `CpuChunkBackend.cs`, `VulkanChunkBackend.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/BackendSeamTests.cs`

**Interfaces:**
- Produces: `interface IChunkBackend { string Tag { get; } IKvCache CreateCache(int maxSeqLen); void WriteRows(IKvCache cache, int layer, int startPos, ReadOnlySpan<float> k, ReadOnlySpan<float> v); void ReadRows(IKvCache cache, int layer, int startPos, int count, Span<float> k, Span<float> v); void ShiftKeys(IKvCache cache, int startPos, int count, int delta, RopeParameters rope); }`. The CPU backend keeps current behaviour; the Vulkan backend wraps `IPositionedHostKvCache` and `RopeShiftKvKernel.Shift` and throws `NotSupportedException` for non-plain RoPE.

- [ ] **Step 1:** Create a worktree from `dev` (`git worktree add ...\chunk-vulkan -b feature/chunk-reuse-vulkan origin/dev`), merge `feature/chunk-kv-reuse` at `b99570ba` (later commits are merged when the E4b task finishes), build, run the ChunkReuse suite. Record the merge in the report.
- [ ] **Step 2: Write failing tests:** `Backend_Tag_IsInKeyAndFingerprint`; `VulkanBackend_RefusesYarnRopeFreqFactorsAndMla`; `Assembler_RefusesCacheWithoutPositionedIo`; `CpuBackend_RoundTrip_EqualsOldPath` (bit-exact against the existing CPU assembly); `VulkanBackend_WriteThenRead_RoundTrips` (GPU-gated, within F32 exactness).
- [ ] **Step 3:** Run `--filter BackendSeamTests`; expected FAIL. **Step 4:** Implement the seam; the CPU backend must leave all 259 existing tests green.
- [ ] **Step 5:** Rerun; expected PASS (GPU tests included when a GPU is available); mutants for each refusal; commit.

### Task 2: Numerical floor (Step 0)

**Files:**
- Create (dotLLM): `benchmarks/ChunkKvLab/FloorCommand.cs`
- Create (here): `experiments/G0-floor/` with `run.ps1`, `README.md`

**Interfaces:**
- Produces: `floor.csv` with `layer, kind(K|V), rel_l2_mean, rel_l2_p99, kl, top1` for each comparison pair and a tolerance table in the README: (a) CPU full prefill vs Vulkan full prefill; (b) Vulkan full prefill vs Vulkan prefill in different row-count batches (the 8-row versus 96-row effect); (c) Vulkan prefill vs Vulkan with the same tokens re-run (determinism).

- [ ] **Step 1: Write failing tests** for the metric helpers (relative L2 per layer, KL, top-1 on synthetic tensors with known answers).
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement the command over 20 E4 contexts at 2K and 5 at 8K on Qwen3-4B Q4_K_M, both CPU and Vulkan. **Step 4:** Run; write the tolerance table ("pass = at most 1.5x the floor of the matching pair" unless the floor shows otherwise) and commit. Record the CPU-versus-Vulkan floor in `~/.claude/LLMs.md`.

### Task 3: Encode, store and assemble on Vulkan; E1 on Vulkan

**Files:**
- Modify (dotLLM): `ChunkEncoder.cs`, `ChunkAssembler.cs`, `ChunkedContext.cs`, `benchmarks/ChunkKvLab/E1Runner.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/VulkanAssemblyTests.cs` (GPU-gated)

**Interfaces:**
- Consumes: Task 1 seam, Task 2 tolerances.
- Produces: `ChunkEncoder.Encode(IModel model, IChunkBackend backend, ...)` returning a `ChunkKvEntry` tagged with the backend; assembly through `WriteRows` (host) or `CopyRowsFrom` (device to device) plus `ShiftKeys`.

- [ ] **Step 1: Write failing tests:** `VulkanEncode_LayerZeroV_MatchesCpuWithinFloor`; `VulkanAssemble_SingleChunkAtPositionZero_EqualsFullPrefillWithinFloor`; `VulkanAssemble_ShiftedChunk_KeysMatchFullPrefillShiftedWithinFloor`; `VulkanAssemble_RejectsCpuTaggedEntry`; `DeviceCopyAndHostWrite_AssembleIdentically`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** Rerun; PASS with mutants (wrong delta sign, wrong layer offset, skip shift).
- [ ] **Step 5:** Re-run E1 on Vulkan (2K, 4K, 8K, 16K, plus 32K) and compare naive, prefix and full numbers with the CPU E1 table: mean KL and top-1 within the floor-derived tolerance; record tokens per second for the full prefill and the assembly; write `experiments/G1-e1-vulkan/README.md`; commit.

### Task 4: Single-pass selective recompute on Vulkan

**Files:**
- Modify (dotLLM): `src/DotLLM.ChunkReuse/SelectiveRecomputer.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/VulkanRecomputeTests.cs` (GPU-gated)

**Interfaces:**
- Produces: `SelectiveRecomputer.Recompute(..., IChunkBackend backend)` using `Forward(subsetIds, subsetPositions, cache)` in one call on Vulkan; CPU keeps the per-run loop.

- [ ] **Step 1: Write failing tests:** `Recompute_AllPositions_EqualsFullPrefillWithinFloor`; `Recompute_SinglePosition_EqualsPerRunPathWithinFloor`; `Recompute_RandomSubset_VulkanVsCpu_WithinFloor`; `Recompute_NonContiguousSubset_UsesOneForwardCall` (count dispatches via a counting wrapper); `Recompute_FirstAndLastPosition_Edge`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** Rerun; PASS with mutants.
- [ ] **Step 5:** Speed checkpoint: for 2K and 8K contexts at 5/10/20% budgets, time single-pass recompute versus per-run `Forward` on Vulkan versus full prefill; 3 repeats each; write `experiments/G2-recompute-speed/README.md`; commit.

### Task 5: Query-relevance probe on Vulkan

**Files:**
- Modify (dotLLM): `src/DotLLM.ChunkReuse/Selectors/ScoreSources.cs`, `QueryRelevanceSelector.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/VulkanProbeTests.cs` (GPU-gated)

**Interfaces:**
- Produces: `ScoreSources.QueryRelevanceVulkan(IModel model, ...)` following `probe.Begin`, `AttachQueryRelevanceProbe`, `Forward`, `ReadScores`, `cache.Rollback(L)`; same `ITokenScoreSource` contract as the CPU source.

- [ ] **Step 1: Write failing tests:** `VulkanProbe_Scores_CorrelateWithCpuProbe` (Spearman and top-10% overlap above thresholds taken from the floor study); `VulkanProbe_LeavesCacheLengthUnchanged`; `VulkanProbe_SameInputs_SameScores`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** Rerun; PASS with mutants. **Step 5:** Report probe time per request on Vulkan versus the 16 s CPU probe; commit.

### Task 6: E4 rerun on Vulkan at larger contexts

**Files:**
- Create (here): `experiments/G3-e4-vulkan/` with `run.ps1`, `README.md`; append a section to `REPORT.md`

- [ ] **Step 1:** Re-run the E4 arms (Naive, FirstK, ChunkStarts, QueryRelevance, Graph, Hybrid(QR), oracles) on the same validated tasks at 2K on Vulkan and check the CPU orderings hold within the floor.
- [ ] **Step 2:** Extend to 8K and 32K contexts (validate tasks at each size first, because difficulty and solved-without rates change); both chunkers; 3 seeds; budgets 5/10/20%.
- [ ] **Step 3:** Report quality versus budget with intervals, time-to-first-token for full prefill versus reuse (store warm and cold), speedup with variance over 3 runs, and which attention path ran; state plainly whether the G2 conclusions change (graph signal, symbol versus fixed chunks, 95%/20% bar).
- [ ] **Step 4:** Commit; report to the user.

### Task 7: Upstream preparation

**Files:**
- Create (here): `docs/release/chunkreuse-pr-split.md`

- [ ] **Step 1:** List the changes that need a dotLLM issue and PR (C1 `InternalsVisibleTo`, C4 layer-window overload, C7 CPU query probe, the `DotLLM.ChunkReuse` library, the lab) with their tests and size; propose the split with the dotLLM lead. Do not file anything until the user approves. Folds into Task 9 of the Phase S plan.

---

## Self-review notes

- Spec coverage: moves every experiment stage (E1, E2/E4 arms, selective recompute, probe) to Vulkan with the CPU path as a cross-check; the user's speed-at-each-step request is Tasks 3 (assembly speed), 4 (recompute speed), 5 (probe time) and 6 (end-to-end TTFT).
- Order: Task 1 first; Task 2 immediately after (it fixes every later tolerance); Tasks 3-5 strictly in order; Task 6 last. Phase S Tasks 3 onward (store-backed assembly, CLI) run on the merged branch afterwards.
