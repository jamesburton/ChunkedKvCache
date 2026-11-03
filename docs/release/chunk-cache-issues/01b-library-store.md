# Library: on-disk chunk store and store-backed assembly (draft)

> **Status: DRAFT, not filed.** PR 4 of the series in `docs/superpowers/plans/2026-11-03-pr-split.md` (umbrella row 2,
> second library PR). Refs #1542. Depends on PR 3 (`01-library-core.md`). Our side files nothing and pushes nothing.
> Source: `feature/chunk-cache-upstream-prep`. **Cut branch (local, not pushed): `pr/chunkreuse-store`** (worktree
> `C:\Development\dotLLM\.claude\worktrees\pr04-store`), stacked on `pr/chunkreuse-core`; rebase onto `origin/dev` once
> PR 3 merges. PR body draft: `pr-bodies/PR-04-chunkreuse-store.md`. Folds in the `.ckv` header backend tag (Phase I
> Task 1, L4) and the namespace through the assembler (Task 2).

## Title

Chunk reuse: file chunk store (`.ckv`, backend tag in the header) and store-backed context assembly

## Body

- `IChunkStore`, `FileChunkStore`: one `.ckv` file per `ChunkKey` (atomic write-then-rename, header with format
  version 2 and the **backend tag**; a CPU / Vulkan mismatch is a miss, never a conversion), `OpenExisting`, header-only
  `Contains` probe, `StoreStats`, `SweepTempFiles`, `ChunkStoreBusyException` (and `ChunkStoreLockTimeoutException`,
  which the lock PR throws).
- `StoredContextAssembler`: assemble a context from the store, encoding and putting misses; a structurally valid but
  wrong entry is a miss, evicted and replaced; store failures are misses; `ForModel` refuses a model that does not
  reproduce the fingerprint.
- Locks, index, ledger and registry are **not** here (next library PRs; their crefs are `<c>` text in this cut). The
  server (`--chunk-cache`) is the first consumer (server exec PR).

**Docs:** `docs/CHUNK_REUSE.md` gains "On-disk store" and "Store-backed assembly".

## Acceptance criteria

- Builds (warnings as errors) on top of PR 3 only.
- `DOTLLM_SKIP_VULKAN=1 dotnet test ... --filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse` passes on the clean cut:
  **187 passed, 0 skipped cumulative** (100 from PR 3 + 87): `ChunkStoreTests` (key tests moved to PR 3's `ChunkKeyTests`;
  their store halves stay as `Store_ChangedProducerKey_IsMiss` (10 cases) and `Store_OtherNamespaceKey_IsMiss`;
  `Index_SavedUnderOtherNamespace_LoadsEmptyWithNote` moved to `ChunkIndexTests`), `StoredAssemblyTests` (without
  `StoreAssemblyCheck_RefusesNonCpuBackend_BeforeLoading` — research lab only, now `StoreAssemblyGuardTests` on the fork
  — and without the `StoredAssemblyTestsGpu` class, now `StoredAssemblyGpuTests.cs`, Vulkan backend PR).
- Mutant evidence in the PR body, re-run on the cut.

## Mutant evidence (re-run on the cut, 2026-11-03)

Runner `.superpowers/sdd/2026-11-01-phase-s/pr-split-pr3-pr4-mutants.py` (set `pr04`), log
`.superpowers/sdd/2026-11-01-phase-s/pr-split-pr4-store-mutants.log`; `git archive` of `pr/chunkreuse-store` `89a842ea` (before the rebase onto PR 3's extra test commit; no store file changed). **22 / 22 killed.**
Results: `pr-bodies/PR-04-chunkreuse-store.md`. Original logs:

- Header backend tag and backend-aware assembly: `phase-s/phase-i-task-1-mutants.log` M1-M13, F1, F2 (re-run).
- Namespace through the assembler: `phase-s/phase-i-task-2-mutants.log` N6, N7, N14; `phase-i-task-2-fix-mutants.log` F9
  (re-run).
- Store-backed assembly: `phase-s/task-3-mutants.log` M01-M23, `task-3-fix-mutants.log` F01-F12, `task-3-r2-mutants.log`
  G08 (killing tests in `StoredAssemblyTests`, unchanged by the split; not re-run).
- Store format and key: `phase-s/task-2-report.md` (mutant section; key part now in PR 3).
