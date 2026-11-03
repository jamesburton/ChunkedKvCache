# Library: `DotLLM.ChunkReuse` core — chunk encode, RoPE-shifted assembly, key and text-first chunkers (draft)

> **Status: DRAFT, not filed.** PR 3 of the series in `docs/superpowers/plans/2026-11-03-pr-split.md` (umbrella row 2,
> first library PR). Refs #1542 (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when
> and whether it is filed. Source: `feature/chunk-cache-upstream-prep` (the assembly split of `feature/chunk-cache-server`
> `1113c953`). **Cut branch (local, not pushed): `pr/chunkreuse-core`** (worktree
> `C:\Development\dotLLM\.claude\worktrees\pr03-core`) off `origin/dev` `29567637`. PR body draft:
> `pr-bodies/PR-03-chunkreuse-core.md`. Folds in the key part of `02-library-namespace-key.md` (Phase I Task 2) and the
> tokenisation / wire-eligibility part of `05-library-wire-chunking.md` (Tasks 5 / 5b).

## Title

Chunk reuse: `DotLLM.ChunkReuse` core library (encode a chunk's K/V in isolation, assemble with RoPE re-rotation, chunk key)

## Body

First of a short series that brings chunk-level KV reuse (#1542) into dotLLM. This PR adds a new library project with
**no Roslyn and no Vulkan dependency** (the C# chunker and the Vulkan backend are later, separate projects,
`DotLLM.ChunkReuse.CSharp` / `DotLLM.ChunkReuse.Vulkan`, so `DotLLM.Server` never pulls them):

- `ChunkEncoder` / `ChunkAssembler`: encode a token chunk's per-layer K/V at positions `0..n-1`; assemble cached chunks
  into an `IKvCache` at new offsets, re-rotating keys by the RoPE delta (`RopeShift`, `RopeParameters`; NoPE layers
  untouched). `ChunkedContext`, `ResidentChunkKvEntry`.
- `IChunkBackend` + `CpuChunkBackend`: the backend seam; `ChunkKvEntry.Backend` tags every entry so CPU and Vulkan entries
  never mix.
- `ChunkFingerprint`, `GgufIdentity` (incl. `QuantizationLabel`), `ChunkReuseSchema.KvOutputVersion`: what a stored
  chunk's K/V depends on.
- `ChunkKey` / `ChunkNamespace` (key scheme `chunk-key/v4`): store key of a chunk, partitioned by namespace.
- `Chunk`, `IChunker`, `SourceFile`, `ChunkTokenization`, `FixedSizeChunker`, `LinesChunker` (`lines-N`, text-first),
  `WireChunking` (allow-list, wire hash, round-trip check).
- Nothing in the engine or server uses it yet; `dotLLM.slnx` and the unit-test project reference it.
- **Not packed yet** (`IsPackable=false`, user decision 2026-11-03): it becomes a package when `DotLLM.Server` references
  it (server execution PR). No release-asset change in this PR.

**Docs:** new `docs/CHUNK_REUSE.md` (library half of ChunkedkvCache `experiments/store/README.md`: encode / assemble,
identity, chunkers, exactness, precision).

## Acceptance criteria

- Targets `dev`. Builds with `dotnet build -c Release` (warnings as errors, XML docs) with no Roslyn / Vulkan reference
  in `src/DotLLM.ChunkReuse/DotLLM.ChunkReuse.csproj`.
- `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit -c Release --filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse`
  passes on the clean cut: **100 passed, 0 skipped** (2026-11-03): `ChunkAssemblyTests` (incl. the CPU fingerprint golden / backend-tag test added for mutants M11 / M12), `GgufIdentityTests`,
  `ChunkReuseSchemaTests` (golden for `KvOutputVersion`), `ChunkTokenizationTests`, `LinesChunkerTests`, **`ChunkKeyTests`**
  (key / namespace tests, moved out of `ChunkStoreTests` so this PR tests its own key code) and **`WireChunkingTests`**
  (core half; the symbol / index half is `WireChunkingIndexTests`, the contract-fixture hashes `WireChunkingFixtureTests`).
  Held back to later PRs: 3 `SymbolChunker_*` tokenisation cases (`SymbolChunkerTokenizationTests`, C# chunker PR) and
  `Corpus_UsesTheChunker_AndTheHashNamesIt` (now in `CorpusTests`).
- New public API documented in `docs/CHUNK_REUSE.md`; no `JsonSerializerContext` in this PR.
- Mutant evidence in the PR body, re-run on the cut.

## Mutant evidence (re-run on the cut, 2026-11-03)

Runner `.superpowers/sdd/2026-11-01-phase-s/pr-split-pr3-pr4-mutants.py` (set `pr03`), log
`.superpowers/sdd/2026-11-01-phase-s/pr-split-pr3-core-mutants.log`; `git archive` of `pr/chunkreuse-core` `8e66ba63` and `912a353a` (follow-up set). **45 / 47 killed, 2 equivalent survivors (B-M2, F2).**
Results and the killed-by table: `pr-bodies/PR-03-chunkreuse-core.md`. Original logs:

- Encoder / assembly / RoPE shift: Phase R/P Task 4 (`.superpowers/sdd/2026-10-31-chunk-kv-reuse-phase-r-p/task-4-report.md`).
- Backend tag in the fingerprint: `phase-s/phase-i-task-1-mutants.log` M11 / M12.
- Namespace in the key: `phase-s/phase-i-task-2-mutants.log`, `phase-i-task-2-fix-mutants.log`; key encoding:
  `phase-s/task-3-r2-mutants.log` G09 / G10, `task-3-fix-mutants.log` F13.
- Chunk tokenisation / text-first chunker / wire eligibility: `phase-s/phase-i-task-5-mutants.log`.
- GGUF identity: `phase-s/task-3-fix-mutants.log` F14-F19, `task-3-r2-mutants.log` G01-G07 (killing tests unchanged in
  this PR: `GgufIdentityTests`; not re-run).
