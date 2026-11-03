# PR 3 body draft: `DotLLM.ChunkReuse` core library

> **DRAFT, not opened.** Branch `pr/chunkreuse-core` (local, worktree
> `C:\Development\dotLLM\.claude\worktrees\pr03-core`), 3 commits on `origin/dev` `29567637`, tip `912a353a`. Issue:
> draft `../01-library-core.md` (**not filed yet**; file it first, then put its number in the title / `Refs` line and the
> commit messages). Base: `dev`. Independent of PRs 1 and 2. Source of the files: fork branch
> `feature/chunk-cache-upstream-prep` (`3d2ad8f5`; the assembly split of `feature/chunk-cache-server`).

## Title

Chunk reuse: `DotLLM.ChunkReuse` core library (encode a chunk's K/V in isolation, assemble with RoPE re-rotation, chunk key)

## Body

Refs #1542 (umbrella: chunk-level KV reuse). Refs #1567 (this PR's issue). The core builds **without Roslyn or Vulkan** (a light assembly: key, store-independent encode/assemble, tokenisation, backend seam; the C# chunker and Vulkan backend arrive in later PRs as separate assemblies). `DotLLM.ChunkReuse` stays `IsPackable=false` until the server PR needs it (maintainer decision on #1567). PR 4 (store, #1568) is stacked on this PR.

### Summary

First library PR of chunk-level KV reuse (#1542). A **chunk** (a file, a function, a block of lines) is encoded once, in
isolation at positions `0..n-1`; a later prompt that contains it at another offset gets its K/V copied in with the keys
re-rotated to the new positions instead of re-running prefill over it. This PR adds the core of that as a new project,
`src/DotLLM.ChunkReuse`, with **no Roslyn and no Vulkan dependency** (the C# chunker and the Vulkan backend come later as
`DotLLM.ChunkReuse.CSharp` / `DotLLM.ChunkReuse.Vulkan`, so `DotLLM.Server` never pulls them). Nothing in the engine or
server uses it yet.

- **Encode / assemble.** `ChunkEncoder` (isolated prefill into a fresh exact-F32 cache, host copy as `ChunkKvEntry`, or
  the cache itself as `ResidentChunkKvEntry`), `ChunkAssembler` (writes chunks back to back from the destination's
  `CurrentLength`, re-rotating keys by the offset; values unchanged; NoPE layers untouched), `RopeShift` /
  `RopeParameters` (dotLLM stores K post-RoPE, so `R(Δ)·R(p)·k = R(p+Δ)·k`; exact for plain RoPE, scaled variants refused),
  `ChunkedContext`.
- **Backend seam.** `IChunkBackend` + `CpuChunkBackend` (reference, host `SimpleKvCache`). Entries carry the backend tag;
  it is in the fingerprint (non-CPU tags only, so CPU fingerprints keep their pre-seam value) and in the key, so CPU and
  Vulkan entries never mix.
- **Identity.** `ChunkFingerprint`, `GgufIdentity` (content-based model id over every shard: header + first / last
  4 KiB of each tensor, or a full hash; tokenizer id over `tokenizer.ggml.*`; quantisation label),
  `ChunkReuseSchema.KvOutputVersion` (hand-bumped schema version with a golden K/V summary test instead of the build SHA).
- **Key.** `ChunkKey.Create` (`chunk-key/v4`: SHA-256 over a length-prefixed canonical encoding of namespace,
  fingerprint, tokenizer, RoPE, schema version, backend, dtype, positioning, token ids) and `ChunkNamespace`
  (`Default` = `""`, `ForApiKey` = `k-` + 16 hex of SHA-256, strict validity rule).
- **Chunkers.** `Chunk` / `IChunker` / `SourceFile`; `ChunkTokenization.Encode` = `EncodeRaw(MarkUntrustedSpecials(text))`,
  the chat path's tokenisation of caller content (#1339), so a `<think>` spelling in a chunk gets the ids the server
  computes; `LinesChunker` (`lines-N`, text first: every piece tokenises alone and round-trips); `FixedSizeChunker`
  (`fixed-N`, id slices, not wire-eligible); `WireChunking` (allow-list, `sha256:` wire hash, `VerifyRoundTrip`).

**Review order suggestion:** `RopeShift` + `ChunkAssembler` (the math), then `ChunkKey` / `ChunkNamespace` (persistent
format), then the chunkers.

### Scope

`git diff --stat origin/dev` (32 files, +3,685, 0 deleted):

```
 docs/CHUNK_REUSE.md                                          |  86 ++
 dotLLM.slnx                                                  |   1 +
 src/DotLLM.ChunkReuse/Backends/{CpuChunkBackend,IChunkBackend}.cs      | 205 ++
 src/DotLLM.ChunkReuse/{ChunkAssembler,ChunkEncoder,ChunkFingerprint,ChunkKvEntry,ChunkReuseSchema,ChunkedContext,
   GgufIdentity,ResidentChunkKvEntry,RopeParameters,RopeShift}.cs        | 909 ++
 src/DotLLM.ChunkReuse/Corpus/{Chunk,ChunkTokenization,FixedSizeChunker,LinesChunker,WireChunking}.cs | 387 ++
 src/DotLLM.ChunkReuse/Store/{ChunkKey,ChunkNamespace}.cs                | 210 ++
 src/DotLLM.ChunkReuse/DotLLM.ChunkReuse.csproj               |  21 +
 tests/DotLLM.Tests.Unit/ChunkReuse/ (9 files)                | 1,865 ++
 tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj             |   1 +
```

- **New project** `src/DotLLM.ChunkReuse` (refs Core, Cpu, Engine, Models, Tokenizers; no package reference).
  `IsPackable=false` for now: it becomes a package in the server-execution PR, when the packable `DotLLM.Server` starts
  referencing it. **No release-asset change in this PR.**
- No server flag, endpoint, DTO or `JsonSerializerContext`.
- Precision note (CLAUDE.md rule 1): `ChunkKvEntry` holds F32 rows because the CPU reference cache (`SimpleKvCache`) is F32
  and the encoder reads it unchanged; this is an off-hot-path library, nothing is stored on an inference path in this PR.
  The KV dtype is in the key and (next PR) the file header, so F16 / Q8_0 rows can follow without colliding.

### Tests (CPU, `DOTLLM_SKIP_VULKAN=1`, Release, `-m:2`, from the clean PR worktree)

| run | result |
|---|---|
| `dotnet build tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release -m:2` | 0 errors |
| `--filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse` | **100 passed**, 0 skipped, 0 failed |

Test classes: `ChunkAssemblyTests` (RoPE shift vs keys the model computes at the target position, assembly vs full
prefill, capacity / context guards, fingerprint inputs and the CPU fingerprint golden), `ChunkReuseSchemaTests` (golden
K/V summary for `KvOutputVersion`), `GgufIdentityTests`, `ChunkKeyTests` (key inputs, field boundaries, `chunk-key/v4`
goldens cross-checked by an independent Python re-implementation, namespaces, `ForApiKey`), `ChunkTokenizationTests`
(synthetic vocabulary + the real Qwen3-4B tokenizer when present; skips otherwise), `LinesChunkerTests`,
`WireChunkingTests`. All CPU; the synthetic dense `qwen3` GGUF is generated in-test (no weights in the repo).

### Mutant evidence

Re-run on this cut: `git archive` of `pr/chunkreuse-core` (`8e66ba63`, then `912a353a` for the follow-up set) into a
throwaway copy, one mutant at a time, `--filter FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse`, Release, CPU,
`DOTLLM_SKIP_VULKAN=1`. Baseline passes. **45 / 47 killed; the 2 survivors are equivalent mutants** (below). Runner and
log (ChunkedkvCache): `.superpowers/sdd/2026-11-01-phase-s/pr-split-pr3-pr4-mutants.py` (set `pr03`),
`pr-split-pr3-core-mutants.log`. Test names omit the `Tests` suffix of the class.

| mutant | change | killed by |
|---|---|---|
| RP-M1 | RoPE delta sign flipped | `RopeShift_ShiftedKeys_EqualKeysComputedAtTargetPosition` (both archs), 4 `Assemble_*` |
| RP-M2 | RoPE pairing swapped (NeoX ↔ Norm) | same 6 as RP-M1 |
| RP-M4 | CPU backend never shifts keys | `Assemble_SameChunkTwice_*`, `_ReorderedChunks_*`, `_OneTokenChunk_*`, `_IntoNonEmptyCache_*` |
| RP-M5 | assembly starts at 0, not `CurrentLength` | `Assemble_IntoNonEmptyCache_AppendsAtCurrentLength`, `Assemble_ChunksExceedCapacity_ThrowsAndWritesNothing` |
| RP-R1b | `RopeShift` skips the last head of the slice | 6 (incl. `Assemble_OneTokenChunk_AtNonZeroOffset_MatchesModelKey`) |
| RP-R2 | encoder context guard removed | `Encode_ChunkLongerThanContext_Throws` |
| RP-R3 | assembler capacity guard removed | `Assemble_ChunksExceedCapacity_ThrowsAndWritesNothing` |
| M11 | CPU fingerprint also hashes the backend field (orphans CPU stores) | `ChunkFingerprint_BackendTag_CpuKeepsThePreSeamValue_OtherTagsDiffer` |
| M12 | fingerprint omits the backend for every tag (CPU / Vulkan mix) | same |
| N1 | namespace not hashed | `Key_DefaultNamespace_GoldenV4`, `Key_DiffersByNamespace` |
| N2 / N2b | default namespace skipped (scheme v4 / v3) | `Key_DefaultNamespace_GoldenV4` |
| N3 | scheme string not bumped | `Key_DefaultNamespace_GoldenV4` |
| N4 | namespace without its length prefix | `Key_DefaultNamespace_GoldenV4` |
| N5 | namespace hashed after the tokens | `Key_DefaultNamespace_GoldenV4` |
| G09 | fingerprint / tokenizer fields swapped | `Key_DefaultNamespace_GoldenV4` |
| G10 | token count not hashed | `Key_DefaultNamespace_GoldenV4` |
| F13 | positioning not hashed | `Key_DefaultNamespace_GoldenV4`, `Key_DiffersWhenModelTokenizerRopeOrEngineVersionChanges(positioning)` |
| N8 | `ForApiKey` returns the full digest | `ForApiKey_IsStable_AndNeverEqualsDefault`, `Key_DiffersByNamespace`, `Namespace_Null_IsNotValid` |
| N9 / N10 / N11 / N12 | `ForApiKey`: no `k-` prefix / UTF-16 / accepts `""` / returns the key | `ForApiKey_IsStable_AndNeverEqualsDefault` |
| F1 | `ChunkKey.Create` skips the validity rule | `Namespace_Invalid_IsRefusedEverywhere` |
| F3 | no rule + replacing UTF-8 encoder | `Namespace_Invalid_IsRefusedEverywhere`, `Namespace_LoneSurrogates_NeverShareAKey` |
| F4 / F5 / F6 / F7 / F8 | `IsValid` accepts upper case / any length / `/` `\` / anything; `Validate` checks null only | `Namespace_Invalid_IsRefusedEverywhere` (F7, F8 also `Namespace_LoneSurrogates_*`) |
| F10 | `IsValid(null)` true | `Namespace_Null_IsNotValid` |
| F11 | reserved `default` accepted | `Namespace_Invalid_IsRefusedEverywhere("default")` |
| B-M1 | `ChunkTokenization` without the special-token marking | 8 `ChunkTokenization*` tests (incl. the real-Qwen3 golden) |
| B-M3 | `Encode` (BOS framing) instead of `EncodeRaw` | `Encode_NeverAddsBos_EvenWhenTheTokenizerFramesEncode` |
| B-M7 / B-M8 / B-M9 / B-M10 | `LinesChunker` probes (rest-fits / binary search / line end / CRLF back-off) on bare `EncodeRaw` | `LinesChunker_SpecialSpellingNearLimit_StaysWithinN`, `LinesChunker_UsesChunkTokenization`, `VerifyRoundTrip_SpecialSpellingChunk_Passes`, `LinesChunker_CrlfBackOff_*` (B-M10) |
| B-M11 | `FixedSizeChunker` on bare `EncodeRaw` | `FixedSizeChunker_UsesChunkTokenization` |
| B-M12 | `VerifyRoundTrip` on bare `EncodeRaw` | `LinesChunker_SpecialSpellingNearLimit_StaysWithinN`, `VerifyRoundTrip_SpecialSpellingChunk_Passes` |
| T5-M2 | wire hash over UTF-16 | `Hash_IsSha256OfUtf8_LowercaseHex` |
| T5-M3 | round trip compares lengths only | `VerifyRoundTrip_SameLengthDifferentIds_Fails` |
| T5-M12 | fixed-size id slices marked wire-eligible | `FixedSizeChunker_IdSlices_NotWireEligible_LinesChunker_Eligible` |
| T5-M13 / T5-M14 | `lines-512` on the allow-list / `IsWireChunker` ignores the list | `Lines512_IsPendingNotEligible` |

**Survivors (equivalent):** B-M2 (special-token marking applied twice: marking is idempotent once spellings are broken,
which `PreMarkedOrCallerMarkerText_EncodesAsTheChatPathDoes` asserts); F2 (namespace encoded with the replacing instead of
the throwing UTF-8 encoder: the validity rule admits ASCII only, so no input reaches the difference; F3 shows the pair is
caught as soon as the rule is gone).

History: on the first cut M11 and M12 survived (their killing tests were in the store / Vulkan test classes, which ship
later); `ChunkFingerprint_BackendTag_CpuKeepsThePreSeamValue_OtherTagsDiffer` (the pre-seam CPU golden plus a
CPU / Vulkan / other-tag inequality) was added to this PR and kills both. The key / namespace and core wire-chunking tests
were moved into this PR (`ChunkKeyTests`, `WireChunkingTests`) for the same reason. GGUF-identity mutants (F14-F19,
G01-G07 in the original logs) are killed by `GgufIdentityTests`, which ship unchanged here.

### Conventions checklist

- [x] Targets `dev`, not `main`. `Closes #N` does not auto-close on `dev`: the issue is closed by hand after merge.
- [x] Issue first: draft `01-library-core.md` (filed as #1567).
- [x] Owning doc in the same PR: new `docs/CHUNK_REUSE.md`.
- [x] XML docs on all public API; builds with warnings as errors (crefs to types in later PRs are `<c>` text).
- [x] STJ source-gen DTO rule: n/a (no DTO, no `JsonSerializerContext`; the library's first context arrives in a later PR with its
      `ChunkReuseJsonContextDefaultsTests` guard).
- [x] Correctness tests shown to fail against mutants (table above).
- [x] No new server flag; no behaviour change for existing callers (nothing references the project except the tests).
- [x] New project added to `dotLLM.slnx`; `IsPackable=false` (no release-asset change).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
