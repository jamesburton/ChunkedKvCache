# PR 4 body draft: chunk store and store-backed assembly

> **DRAFT, not opened.** Branch `pr/chunkreuse-store` (local, worktree
> `C:\Development\dotLLM\.claude\worktrees\pr04-store`), 2 commits stacked on `pr/chunkreuse-core` (PR 3), tip
> `68973c2c`. **Open only after PR 3 merges**: then `git rebase origin/dev` (drops PR 3's commits) and re-run the filter.
> Issue: draft `../01b-library-store.md` (**not filed yet**). Base: `dev`.

## Title

Chunk reuse: file chunk store (`.ckv`, backend tag in the header) and store-backed context assembly

## Body

Refs #1542 (umbrella: chunk-level KV reuse). Refs #1568 (this PR's issue). **Stacked on the core PR (PR 3, #1567)**: open it after PR 3 merges (rebase with `git rebase --onto origin/dev pr/chunkreuse-core`); until then this branch contains PR 3's commits. `DotLLM.ChunkReuse` stays `IsPackable=false`.

### Summary

Persistence for encoded chunks, and assembly of a context from it. Still no consumer in the engine or server (the server's
`--chunk-cache` execution PR is the first).

- **`IChunkStore` / `FileChunkStore`.** One file per `ChunkKey` at `root/<hex[0..2]>/<hex>.ckv`, format version 2: magic,
  version, dtype, key, fingerprint, **backend tag**, token count, per-layer K / V lengths, payload size; then ids, K, V.
  - Writes: unique temp file, flush, one rename; a crash or concurrent writer never leaves a partial `.ckv`.
    `SweepTempFiles` and `GetStats` (entries and temp files counted apart).
  - Reads: memory-mapped, every header field and the exact length checked; truncation, trailing bytes, another version
    (incl. v1 without a tag), another key, a malformed or over-long tag are **misses**, never wrong hits. `Contains` /
    `TryReadFingerprint` read the header only. `OpenExisting` does not create the root.
  - Busy destination (Windows cannot replace a mapped file): valid entry for the key → `Put` returns; invalid and held →
    `ChunkStoreBusyException` at once, nothing written, no retry loop. `ChunkStoreLockTimeoutException` (a subclass) is
    declared here for the lock PR.
  - No locking in this class: each put is atomic on its own; the store / index lock model comes with the index PRs.
- **`StoredContextAssembler`.** Looks each chunk up under its isolated key (namespace-aware), encodes and puts misses,
  dedupes repeats within a call, rejects (evicts and re-encodes) a structurally valid but wrong entry (fingerprint,
  backend, tokens, shapes), treats store failures as misses (`StoreFailures`), validates chunks, namespace and destination
  before any store read, appends at the destination's `CurrentLength`. `ForModel(config, modelId, quant, tokenizerId)`
  refuses a model whose config does not reproduce the fingerprint (store-poisoning guard).

### Scope

`git diff --stat pr/chunkreuse-core` (9 files, +2,760 / -1):

```
 docs/CHUNK_REUSE.md                                       |   46 ++   ("On-disk store", "Store-backed assembly")
 src/DotLLM.ChunkReuse/DotLLM.ChunkReuse.csproj            |    3 +-   (description; IVT comment)
 src/DotLLM.ChunkReuse/Store/ChunkStoreBusyException.cs    |   52 ++
 src/DotLLM.ChunkReuse/Store/FileChunkStore.cs             |  527 ++
 src/DotLLM.ChunkReuse/Store/IChunkStore.cs                |   40 ++
 src/DotLLM.ChunkReuse/Store/StoreStats.cs                 |    8 +
 src/DotLLM.ChunkReuse/Store/StoredContextAssembler.cs     |  335 ++
 tests/DotLLM.Tests.Unit/ChunkReuse/ChunkStoreTests.cs     |  726 ++
 tests/DotLLM.Tests.Unit/ChunkReuse/StoredAssemblyTests.cs | 1024 ++
```

No new project, package, flag, endpoint, DTO or `JsonSerializerContext`; no release-asset change (`DotLLM.ChunkReuse`
stays `IsPackable=false`). Crefs to the lock / index types of later PRs are `<c>` text.

Precision / transfer notes (CLAUDE.md rules 1 and 3): entries are F32 rows written as stored (the CPU reference cache is
F32), dtype in key and header so compact rows can follow. This is a host (CPU) store: disk → host only; a device-direct
path (DirectStorage / zero-copy import) is Phase D, not this PR.

### Tests (CPU, `DOTLLM_SKIP_VULKAN=1`, Release, `-m:2`, from the clean PR worktree)

| run | result |
|---|---|
| `dotnet build tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release -m:2` | 0 errors |
| `--filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse` (cumulative with PR 3) | **187 passed**, 0 skipped, 0 failed |

`ChunkStoreTests` (round trip bit-exact incl. NaN payloads / signed zero / subnormals, every corruption mode a miss,
backend-tag layout and tampering, busy / repair, concurrent puts, temp sweep, store side of a changed key /
other namespace), `StoredAssemblyTests` (store = fresh encode bit-exact, hit / miss / repeat counts, wrong-entry
reject-and-replace, store failures, destination validation, namespaces, backend keying, `ForModel` identity).
Not in this PR: the index-namespace test (index PR), the research-lab guard (fork only), the GPU class
`StoredAssemblyTestsGpu` (Vulkan backend PR).

### Mutant evidence

Re-run on this cut: `git archive` of `pr/chunkreuse-store` (`89a842ea`; the later rebase onto PR 3's extra test commit
changed no file of this PR) into a throwaway copy, one mutant at a time, `--filter
FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse`, Release, CPU, `DOTLLM_SKIP_VULKAN=1`. Baseline passes. **22 / 22
killed.** Runner / log (ChunkedkvCache): `.superpowers/sdd/2026-11-01-phase-s/pr-split-pr3-pr4-mutants.py` (set `pr04`),
`pr-split-pr4-store-mutants.log`.

| mutant | change | killed by |
|---|---|---|
| M1 | header tag bytes never checked on read | `Store_HeaderBackendTampered_IsMiss` |
| M1b | reader ignores the header tag, reports `cpu` | `Store_HeaderBackendTampered_WellFormedTag_IsReportedAsWritten`, `Store_HeaderBackendTagLongerThanMax_IsMiss`, `Store_PutOverEntryWithOtherBackendTag_ReplacesIt`, `StoreHeader_PersistsBackendTag`, `StoredAssembly_HeaderBackendTampered_IsMissAndReencoded` |
| M2 | assembler keys on `cpu` whatever its backend | `StoredAssembly_OtherBackend_KeysOnItsTag_AndNeverHitsCpuEntries` |
| M3 | v1 files accepted (read as cpu) | `Store_FormatV1File_IsMiss` |
| M4 | hit check ignores the entry's backend | `StoredAssembly_EntryBackendDiffers_IsRejectedAndReencoded`, `..._HeaderBackendTampered_*`, `..._OtherBackend_FindsCpuTaggedEntryUnderItsOwnKey_*` |
| M5 | identity check recomputes the fingerprint with `cpu` | `StoredAssembly_OtherBackend_*` (2) |
| M6 | misses encoded on the CPU backend | `StoredAssembly_OtherBackend_*` (2) |
| M7 | `ForModel` fingerprints with `cpu` for every backend | `StoredAssembly_OtherBackend_*` (2) |
| M8 | `Put` does not validate the tag | `Store_PutRejectsMalformedBackendTag` |
| M9 | `HeaderBytes` omits the tag | 37 store / assembly tests |
| M10 | destination not vetted by the backend | `Assemble_UnusableDestination_ThrowsBeforeAnyStoreReadOrEncode` |
| M11 / M12 | fingerprint backend field (also killed in PR 3) | `StoredAssembly_DefaultCtor_KeysOnCpu` / `StoredAssembly_OtherBackend_KeysOnItsTag_*` |
| M13 | tag length upper bound unchecked | `Store_HeaderBackendTagLongerThanMax_IsMiss` |
| TF1 | header comparison only for the cpu assembler | `StoredAssembly_OtherBackend_FindsCpuTaggedEntryUnderItsOwnKey_IsRejectedAndReencoded` |
| TF2 | `Put` keeps any valid entry regardless of its tag | `Store_PutOverEntryWithOtherBackendTag_ReplacesIt` |
| N1 | namespace not hashed | `Key_DefaultNamespace_GoldenV4`, `Key_DiffersByNamespace`, `Store_OtherNamespaceKey_IsMiss`, `Assemble_OtherNamespace_AllMisses`, `StoredAssembly_DefaultCtor_KeysOnCpu` |
| N6 | `Assemble` looks up in the default namespace | `Assemble_OtherNamespace_AllMisses` |
| N7 | `KeyOf` drops its namespace | `Assemble_OtherNamespace_AllMisses` |
| N14 | `Assemble` / `KeyOf` accept a null namespace | `Assemble_OtherNamespace_AllMisses` |
| F9 | `Assemble` checks only null up front | `Assemble_OtherNamespace_AllMisses` |
| S1 | `Contains` true for any entry file (key ignored) | 14, incl. `Store_ChangedProducerKey_IsMiss`, `Store_OtherNamespaceKey_IsMiss` |

The store-backed assembly mutants of Phase S Task 3 (M01-M23, F01-F12, G08: never read the store, never put, accept any
entry, no token / fingerprint / shape check, no evict, no dedupe, busy handling, counters, slot placement, destination
checks, `ForModel` identity) were all killed by `StoredAssemblyTests` on the source branch
(`.superpowers/sdd/2026-11-01-phase-s/task-3-mutants.log`, `task-3-fix-mutants.log`, `task-3-r2-mutants.log`); that
class ships here unchanged except for the two tests moved out (lab guard, GPU class), neither of which killed any of
them, so they were not re-run.

### Conventions checklist

- [x] Targets `dev`, not `main`; opened after PR 3 merges, rebased on `dev`. `Closes #N` does not auto-close on `dev`.
- [x] Issue first: draft `01b-library-store.md` (filed as #1568).
- [x] Owning doc in the same PR: `docs/CHUNK_REUSE.md` store sections.
- [x] XML docs on all public API; warnings as errors.
- [x] STJ source-gen DTO rule: n/a (binary format, no JSON).
- [x] Correctness tests shown to fail against mutants (table above).
- [x] No new project, flag or package; no behaviour change for existing callers.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
