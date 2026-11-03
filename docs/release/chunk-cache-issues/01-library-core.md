# Library: `DotLLM.ChunkReuse` core — chunk encode, RoPE-shifted assembly, key and text-first chunkers (draft)

> **Status: DRAFT, not filed.** PR 3 of the series in `docs/superpowers/plans/2026-11-03-pr-split.md` (umbrella row 2,
> first library PR). Refs #1542 (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when
> and whether it is filed. Source: `feature/chunk-cache-server` `3db1b01c` (library files as of that commit). Cut branch
> (local only, not yet created): `feature/chunk-cache-pr03-core` off `origin/dev`. Folds in the key part of
> `02-library-namespace-key.md` (Phase I Task 2) and the tokenisation part of `05-library-wire-chunking.md` (Task 5/5b).

## Title

Chunk reuse: `DotLLM.ChunkReuse` core library (encode a chunk's K/V in isolation, assemble with RoPE re-rotation, chunk key)

## Body

First of a short series that brings chunk-level KV reuse (#1542) into dotLLM. This PR adds a new library project with
**no Roslyn and no Vulkan dependency** (core only; the C# chunker and the Vulkan backend are later, separate projects so
`DotLLM.Server` never pulls them):

- `ChunkEncoder` / `ChunkAssembler`: encode a token chunk's per-layer K/V at position 0; assemble cached chunks into an
  `IKvCache` at new offsets, re-rotating keys by the RoPE delta (`RopeShift`, `RopeParameters`; NoPE layers untouched).
- `IChunkBackend` + `CpuChunkBackend`: the backend seam (the Vulkan backend comes later in its own assembly);
  `ChunkKvEntry.Backend` tags every entry so CPU and Vulkan entries never mix.
- `ChunkFingerprint`, `GgufIdentity` (incl. `QuantizationLabel`), `ChunkReuseSchema.KvOutputVersion`: what a stored
  chunk's K/V depends on.
- `ChunkKey` / `ChunkNamespace` (key scheme `chunk-key/v4`): store key of a chunk, partitioned by namespace.
- `Chunk`, `IChunker`, `SourceFile`, `ChunkTokenization`, `FixedSizeChunker`, `LinesChunker` (`lines-512`, text-first),
  `WireChunking` (wire-eligibility round-trip check).
- Nothing in the engine or server uses it yet; `dotLLM.slnx` and the unit-test project reference it.

**Docs:** new `docs/CHUNK_REUSE.md` (ported from ChunkedkvCache `experiments/store/README.md`, library half).

## Acceptance criteria

- Targets `dev`. Builds with `dotnet build -c Release` (warnings as errors, XML docs) with no Roslyn / Vulkan reference
  in `src/DotLLM.ChunkReuse/DotLLM.ChunkReuse.csproj`.
- `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit -c Release --filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse`
  passes (scratch cut 2026-11-03: 59 passed, 0 skipped): `ChunkAssemblyTests`, `GgufIdentityTests`,
  `ChunkReuseSchemaTests` (golden for `KvOutputVersion`), `ChunkTokenizationTests` (without its 3 `SymbolChunker_*`
  cases, which ship with the C# chunker PR), `LinesChunkerTests` (without `Corpus_UsesTheChunker_AndTheHashNamesIt`).
- New public API documented in `docs/CHUNK_REUSE.md`; every `JsonSerializerContext` follows the STJ source-gen rule
  (none in this PR).
- Mutant evidence in the PR body (below), re-run on the cut.

## Mutant evidence (to re-run on the cut; logs on our side)

- Encoder / assembly / RoPE shift: Phase R/P Task 4 (`.superpowers/sdd/2026-10-31-chunk-kv-reuse-phase-r-p/task-4-report.md`,
  mutant table; e.g. "append at offset 0" killed by `Assemble_IntoNonEmptyCache_AppendsAtCurrentLength`).
- Backend tag on entries: `.superpowers/sdd/2026-11-01-phase-g/task-1-report.md`; `phase-s/phase-i-task-1-mutants.log`
  M2 (assembler keys on cpu regardless of backend).
- Namespace in the key: `phase-s/phase-i-task-2-mutants.log` (15 killed, 0 survived) — keep only the key mutants.
- Chunk tokenisation / text-first chunker: `phase-s/phase-i-task-5-mutants.log` (Task 5b section).

Each cited mutant must be re-run against this PR's tests alone (several were killed by tests that now ship in later
PRs); list only the ones this PR's tests kill.
