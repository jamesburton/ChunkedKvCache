# PR split: Task 1 (prep branch) and Task 3 (PR 3 core, PR 4 store) — report

Date 2026-11-03. Plan: `docs/superpowers/plans/2026-11-03-pr-split.md`. Decisions applied (controller, 2026-11-03): three
assemblies + prep branch (Q1), server S2/S3/S5 as three PRs (Q2, not touched here), defer compare / recompute / selectors /
deviation / probe (Q3), core `IsPackable=false` until PR 7 (Q4), lab on `research/chunk-kv-lab` (Q5), new
`docs/CHUNK_REUSE.md` (Q6), drop/restore the 3 `ChunkIndex.DefaultPath` lines at cut time of PR 8/10 (Q7, not touched
here).

**Status: DONE (local only).** Nothing pushed, no PR opened, no issue filed. All verification CPU-only.

## Branches and commits (dotLLM, all local)

| branch | worktree | base | commits |
|---|---|---|---|
| `feature/chunk-cache-upstream-prep` | `.claude/worktrees/chunk-prep` | `feature/chunk-cache-server` `1113c953` | `e23c02a4` split + test moves; `71aad6b3` `docs/CHUNK_REUSE.md`; `bf5eccef` per-PR key / wire test files; `e6ab6ab8` cref nit; `3d2ad8f5` core fingerprint golden test |
| `research/chunk-kv-lab` | none (ref only) | = prep tip `3d2ad8f5` | none yet (lab home, Q5) |
| `pr/chunkreuse-core` (PR 3) | `.claude/worktrees/pr03-core` | `origin/dev` `29567637` | `88e9b808` library core + docs; `8e66ba63` key + core wire tests; `912a353a` fingerprint golden test |
| `pr/chunkreuse-store` (PR 4) | `.claude/worktrees/pr04-store` | `pr/chunkreuse-core` | `e1cd46aa` store + assembler + docs; `68973c2c` store-side key tests |

Branch names follow the controller's `pr/chunkreuse-*` (the plan's `feature/chunk-cache-prNN-*` names were not used;
the concurrent PR 1 / 2 agent uses `pr/chunkcache-*`). No existing branch or worktree was modified; a temporary detached
worktree `chunk-prep-base` (baseline suite) was created and removed.

ChunkedkvCache: drafts `docs/release/chunk-cache-issues/01-library-core.md`, `01b-library-store.md` updated; PR bodies
`pr-bodies/PR-03-chunkreuse-core.md`, `PR-04-chunkreuse-store.md`; mutant runner `pr-split-pr3-pr4-mutants.py` and logs
`pr-split-pr3-core-mutants.log`, `pr-split-pr4-store-mutants.log` (this directory).

## Task 1: prep branch

- **Prep base deviation:** `feature/chunk-cache-server` had moved from the plan's `3db1b01c` to `1113c953` (Task 15,
  I1b sole writer: new `Store/StoreOwnerLock.cs`, `Tooling/ChunkDenyList.cs`, `ChunkIndex` changes, server files). Prep is
  cut from the current tip; the new library files stay in core (later PRs: 11 / I1b). PR 3 / 4 files are identical at
  both commits.
- **Assemblies:** core `DotLLM.ChunkReuse` (no Vulkan, no Roslyn; IVT `.CSharp`, `.Vulkan`, `.Research`, Tests; "(research)"
  dropped from the description); `DotLLM.ChunkReuse.CSharp` (SymbolChunker, Corpus, Graph/*, ContextSelector,
  SelectionTypes, SymbolLocator, GitInfo; `IsPackable=false`); `DotLLM.ChunkReuse.Vulkan` (VulkanChunkBackend;
  `IsPackable=false`); `DotLLM.ChunkReuse.Research` (fork only: SelectiveRecomputer, CrossFileTaskGenerator,
  TaskValidator, RelatedContextBuilder, Deviation/*, **all** Selectors incl. GraphSelector). `DotLLM.Models` IVT now names
  `.Research`. Solution → `.CSharp`; CLI → `.CSharp` + `.Research` (fork, for `compare`); lab → `.CSharp`, `.Vulkan`,
  `.Research`; unit tests → all three. `dotLLM.slnx` lists the three new projects. All moves are `git mv` (100 %
  renames), namespaces unchanged.
- **Crefs → `<c>`:** 6 in core (IChunkBackend, Chunk, WireChunking, ChunkRef, PathGlob ×2) + 1 in `.CSharp`
  (ReferenceGraph → `CodeTask`). `git grep -nE "DotLLM\.Vulkan|Microsoft\.CodeAnalysis" -- src/DotLLM.ChunkReuse` → empty.
- **Test moves** (plan list): `SymbolChunkerTokenizationTests` (3 out of `ChunkTokenizationTests`, helpers made
  `internal`); `Corpus_UsesTheChunker_AndTheHashNamesIt` → `CorpusTests`; `Index_SavedUnderOtherNamespace_LoadsEmptyWithNote`
  → `ChunkIndexTests`; `StoredAssemblyTestsGpu` → `StoredAssemblyGpuTests.cs`; lab guard → `StoreAssemblyGuardTests.cs`;
  2 CLI tests → `Server/ChunkCache/ChunkCacheCliServerTests.cs` (uses `ChunkCachePipelineTests.Fixture`; `Run`, `Apply`,
  `Body`, `Report` made `internal`).
- **Extra test moves (not in the plan, needed so each PR tests its own code):**
  - `CorpusTests` research half → `CrossFileTaskTests.cs` (fork only: task generator, validator, model scorer use
    `.Research`).
  - Key / namespace tests out of `ChunkStoreTests` (PR 4) → `ChunkKeyTests.cs` (PR 3). The two tests that also checked the
    store were split: key half in `ChunkKeyTests`, store half as `ChunkStoreTests.Store_ChangedProducerKey_IsMiss` (10
    cases) + `Store_OtherNamespaceKey_IsMiss` (+11 test cases, no assertion dropped).
  - `WireChunkingTests` split: core half stays (PR 3), `WireChunkingIndexTests.cs` (symbol chunker / ChunkRef / ChunkIndex,
    PR 9/10), `WireChunkingFixtureTests.cs` (2 contract-fixture hash tests; need library + `ChunkCache/Fixtures/v1`).
  - New core test `ChunkAssemblyTests.ChunkFingerprint_BackendTag_CpuKeepsThePreSeamValue_OtherTagsDiffer` (pre-seam CPU
    golden `b724e623…`, same as `StoredAssemblyTests.GoldenCpuFingerprint`): M11 / M12 survived on the PR 3 cut without it.

### Verification (prep)

| command (`chunk-prep` worktree; tests with `DOTLLM_SKIP_VULKAN=1`) | result |
|---|---|
| `dotnet build dotLLM.slnx -c Release -m:2` (after crefs) | 0 errors |
| full unit suite, server branch `1113c953` (detached copy) | 11,395 total: 7,509 passed, 3,884 skipped, **2 failed** |
| full unit suite, prep `e23c02a4` | 11,395 total: 7,510 passed, 3,884 skipped, **1 failed** |
| the CPU failures re-run alone (prep: `ChunkIndexTests.Save_WhileAReaderHoldsTheIndex_Succeeds`; base: `StoreRegistryTests.Registry_TransientReadError_IsRetried_PersistentOneBlocksOnlyThatSave`), both tests on both trees | pass: timing flakes under two parallel suites + builds |
| `~DotLLM.Tests.Unit.ChunkReuse\|~DotLLM.Tests.Unit.Server.ChunkCache`, base vs prep `e23c02a4` | 978 passed / 23 skipped on both |
| same filter, prep `bf5eccef` (after the key / wire splits) | 989 passed / 23 skipped (+11 split store cases) |

Same total (11,395) and same executed count (7,511) base vs prep. The other base failure,
`Vulkan.VulkanPipelineParityTests.PipelinedForwardBatch_MatchesPerSequenceForward`, is GPU (see Risks).

## Task 3: PR 3 and PR 4 cuts

Recipe: `git fetch origin`; worktree off `origin/dev` `29567637`; `git checkout feature/chunk-cache-upstream-prep -- <paths>`;
hand hunks (`dotLLM.slnx` one line, unit-test csproj one `ProjectReference`); build from the clean worktree.

- PR 3 paths: core root (10 files incl. `ChunkedContext`, `ResidentChunkKvEntry`), `Backends/{IChunkBackend,CpuChunkBackend}`,
  `Corpus/{Chunk,ChunkTokenization,FixedSizeChunker,LinesChunker,WireChunking}`, `Store/{ChunkKey,ChunkNamespace}`, csproj;
  tests `ChunkAssemblyTests`, `GgufIdentityTests`, `ChunkReuseSchemaTests`, `ChunkTokenizationTests`, `LinesChunkerTests`,
  `ChunkKeyTests`, `WireChunkingTests`, `TestTokenizers`, `SyntheticDenseGguf`; new `docs/CHUNK_REUSE.md`.
  Cut-only edits: csproj (`IsPackable=false` per Q4, only the Tests IVT, description without the store), 1 more cref
  (`ChunkNamespace` → `ChunkIndex.DefaultPath`). `git grep "VulkanChunkBackend\|SymbolChunker" -- src/DotLLM.ChunkReuse` →
  only `<c>` text.
- PR 4 paths: `Store/{FileChunkStore,IChunkStore,ChunkStoreBusyException,StoreStats,StoredContextAssembler}`, tests
  `ChunkStoreTests`, `StoredAssemblyTests`; docs store sections; 6 crefs to lock / index types → `<c>`; csproj description
  + IVT comment.
- `git diff feature/chunk-cache-upstream-prep pr/chunkreuse-store -- <PR paths>` shows only those csproj / cref /
  slnx / test-csproj differences.

| run (clean PR worktree, CPU, Release, `-m:2`) | result |
|---|---|
| PR 3 build | 0 errors |
| PR 3 `--filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse` | **100 passed**, 0 skipped (plan's scratch figure 59 before the key / wire / fingerprint tests joined) |
| PR 4 build | 0 errors |
| PR 4 same filter (cumulative) | **187 passed**, 0 skipped (plan 169) |
| PR 4 whole suite `FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU` | 6,397 passed, 56 skipped, 0 failed |

## Mutant re-runs (CPU, `git archive` scratch copies, never a live worktree)

Runner `pr-split-pr3-pr4-mutants.py` (original edits from `phase-i-task-1/2/2-fix/5-mutate.py`, `phase-i-task-5-mutants.py`;
G09 / G10 / F13 / RP-* / F11 / S1 re-created; F5, F10, N14 re-targeted at today's code: the reserved-name check (Task 4b)
and `Validate` in `Assemble` changed their lines).

- **PR 3** (`8e66ba63`, follow-up `912a353a`): **45 / 47 killed**; survivors B-M2 and F2 are the known equivalents. M11 /
  M12 survived on the first cut → new core test → killed. Table in `pr-bodies/PR-03-chunkreuse-core.md`.
- **PR 4** (`89a842ea`; the rebase changed no PR 4 file): **22 / 22 killed** (M1-M13, TF1, TF2, N1, N6, N7, N14, F9, S1).
  Table in `pr-bodies/PR-04-chunkreuse-store.md`.
- Not re-run (killing tests did not move): Task 3 store-assembly M01-M23 / F01-F12 / G08 (`StoredAssemblyTests`), GGUF
  identity F14-F19 / G01-G07 (`GgufIdentityTests`).

## Deviations from the plan

1. Prep cut from `1113c953` (server tip now includes Task 15), not `3db1b01c`.
2. `GraphSelector` goes to `.Research` (deferred), not `.CSharp`: it derives `RankedSelector` (`IRecomputeSelector.cs`,
   deferred). **PR 12 loses `GraphSelector` + `GraphSelectorTests`** (they use Random / FirstK / ChunkStarts selectors and
   `CrossFileTaskGenerator` too); they return with the I5 applied-reuse PR.
3. Extra test moves above (`CrossFileTaskTests`, `ChunkKeyTests` + store-side split, `WireChunking*` split, fingerprint
   golden test). PR 3 / 4 test counts therefore differ from the plan (100 / 187 vs 59 / 169).
4. Branch names `pr/chunkreuse-core` / `pr/chunkreuse-store` (controller), not `feature/chunk-cache-prNN-*`.
5. PR 3 csproj is `IsPackable=false` (Q4) — the plan's §4 table said packable from PR 3.
6. `docs/CHUNK_REUSE.md` added to the prep branch too, as the source for later doc sections.

## Findings for later cuts (not acted on)

- **PR 9 (`.CSharp`)**: `CorpusTests.FixedSizeChunker_EncodeStripsACharacter_ChunksTileAndMatchTheirIds` uses
  `ChunkIndex` (PR 10). Either PR 9 drops its 3 index lines / the test moves to PR 10, or PR 10 lands before PR 9's tests.
- **`WireChunkingFixtureTests`** needs the library and the contract fixtures: ship with PR 7 (or any PR after both 3 and 5).
- **`WireChunkingIndexTests`** needs `SymbolChunker` + `ChunkIndex`: PR 10 (after 9).
- **`DotLLM.ChunkReuse.Research`** is fork-only; PR 15 must drop the CLI's reference to it with `CompareCommand.cs` /
  `Recompute.cs` (plan Task 15 Step 1).
- New Task 15 library files (`StoreOwnerLock`, `ChunkDenyList`, `ChunkIndex` index-only changes) are not in the plan's §1
  inventory; they belong with PR 11 or a later I1b library PR.

## Risks

- **`DOTLLM_SKIP_VULKAN=1` does not skip the `DotLLM.Tests.Unit.Vulkan.*` suites**: the two full-suite runs (baseline and
  prep, ~09:45-09:55) each executed 270 Vulkan tests on the iGPU **without the GPU lock** (one failed on the baseline:
  `PipelinedForwardBatch_MatchesPerSequenceForward`, serial 0.2628 vs batched 0.2799; passed on prep). No device-lost seen.
  The plan's Task 1 Step 4 command (`dotnet test tests/DotLLM.Tests.Unit` with only the env var) is therefore not
  CPU-only; later full runs should add `--filter "FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU"` (as used for
  the PR 4 whole-suite run). The user / GPU-lock holders should know this happened.
- Concurrency tests (`ChunkIndexTests.Save_WhileAReaderHoldsTheIndex_Succeeds`, `StoreRegistryTests.Registry_TransientReadError_*`)
  flake under heavy parallel load; they pass alone.
- PR 4 is stacked: opening it before PR 3 merges would show both diffs.
- The prep branch's `ChunkCachePipelineTests` / `ChunkStoreTests` now expose `internal` helpers to sibling test classes;
  PR 7 / 15 must cut the prep versions together.

## Commands to push and open later (only after the user's per-PR approval and the issue is filed)

From `C:\Development\dotLLM` (fork `origin` = `jamesburton/dotLLM`; PRs to its `dev`, Lane S convention):

```powershell
git fetch origin
# PR 3
git -C .claude/worktrees/pr03-core rebase origin/dev        # re-run build + ChunkReuse filter after any rebase
git push -u origin pr/chunkreuse-core
gh pr create --repo jamesburton/dotLLM --base dev --head pr/chunkreuse-core `
  --title "Chunk reuse: DotLLM.ChunkReuse core library (encode a chunk's K/V in isolation, assemble with RoPE re-rotation, chunk key)" `
  --body-file C:\Development\ChunkedkvCache\docs\release\chunk-cache-issues\pr-bodies\PR-03-chunkreuse-core.md
#   (strip the "DRAFT" header block and the "## Title" section from the body file first; add the filed issue number)

# PR 4 — only after PR 3 has merged
git -C .claude/worktrees/pr04-store rebase --onto origin/dev pr/chunkreuse-core pr/chunkreuse-store
git push -u origin pr/chunkreuse-store
gh pr create --repo jamesburton/dotLLM --base dev --head pr/chunkreuse-store `
  --title "Chunk reuse: file chunk store (.ckv, backend tag in the header) and store-backed context assembly" `
  --body-file C:\Development\ChunkedkvCache\docs\release\chunk-cache-issues\pr-bodies\PR-04-chunkreuse-store.md
```

If the PRs go to upstream `kkokosa/dotLLM` instead, use `--repo kkokosa/dotLLM --head jamesburton:pr/chunkreuse-core`
(and the base the maintainer names). The prep and lab branches are fork-only; push them only if wanted
(`git push -u origin feature/chunk-cache-upstream-prep research/chunk-kv-lab`).
