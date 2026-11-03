# Library: on-disk chunk store and store-backed assembly (draft)

> **Status: DRAFT, not filed.** PR 4 of the series in `docs/superpowers/plans/2026-11-03-pr-split.md` (umbrella row 2,
> second library PR). Refs #1542. Depends on PR 3 (`01-library-core.md`). Our side files nothing and pushes nothing.
> Source: `feature/chunk-cache-server` `3db1b01c`. Cut branch (local only, not yet created):
> `feature/chunk-cache-pr04-store`. Folds in the `.ckv` header backend tag (Phase I Task 1, L4).

## Title

Chunk reuse: file chunk store (`.ckv`, backend tag in the header) and store-backed context assembly

## Body

- `IChunkStore`, `FileChunkStore`: one `.ckv` file per `ChunkKey` (atomic write-then-rename, header with format
  version and **backend tag**; a CPU / Vulkan mismatch is a miss, never a conversion), `OpenExisting`, header-only
  `Contains` probe, `StoreStats`, `ChunkStoreBusyException`.
- `StoredContextAssembler`: assemble a context from the store, encoding and putting misses; a structurally valid but
  wrong entry is a miss, evicted and replaced.
- Locks, index, ledger and registry are **not** here (next library PRs). The server (`--chunk-cache`) is the first
  consumer (server exec PR).

**Docs:** `docs/CHUNK_REUSE.md` gains the store section (format, header, atomicity, backend tag).

## Acceptance criteria

- Builds (warnings as errors) on top of PR 3 only.
- `DOTLLM_SKIP_VULKAN=1 dotnet test ... --filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse` passes (scratch cut
  2026-11-03: 169 passed cumulative): `ChunkStoreTests` (without `Index_SavedUnderOtherNamespace_LoadsEmptyWithNote`,
  which ships with the index PR), `StoredAssemblyTests` (without `StoreAssemblyCheck_RefusesNonCpuBackend_BeforeLoading`
  — research lab only — and without the `StoredAssemblyTestsGpu` class, which ships with the Vulkan backend PR).
- Mutant evidence in the PR body, re-run on the cut.

## Mutant evidence (to re-run on the cut)

- Store-backed assembly: `.superpowers/sdd/2026-11-01-phase-s/task-3-mutants.log` (M01-M23, 23 killed, 0 survived).
- Header backend tag: `phase-s/phase-i-task-1-mutants.log` M1, M1b, M3 (tag never checked; reader ignores tag; v1
  accepted).
- Store format and key: `phase-s/task-2-report.md` (mutant section).
