# Chunk store: size and speed checkpoint (Phase S, Task 2)

dotLLM branch `feature/chunk-store` (worktree `C:\Development\dotLLM\.claude\worktrees\chunk-store`, not pushed):
`src/DotLLM.ChunkReuse/ChunkReuseSchema.cs`, `src/DotLLM.ChunkReuse/Store/{ChunkKey,IChunkStore,FileChunkStore,StoreStats,ChunkStoreBusyException}.cs`,
tests `tests/DotLLM.Tests.Unit/ChunkReuse/{ChunkStoreTests,ChunkReuseSchemaTests}.cs`, lab command `ChunkKvLab store-probe`
(`benchmarks/ChunkKvLab/StoreProbe.cs`).

## What the store is

- **Key** (`ChunkKey.Create`): SHA-256 over a length-prefixed canonical encoding of these fields:
  - model fingerprint
  - tokenizer id
  - RoPE parameters (rotated dims, theta bits, pairing)
  - **K/V schema version** (`ChunkReuseSchema.KvOutputVersion`)
  - **backend** (`cpu`, `vulkan`, ...)
  - **KV dtype**
  - chunk token ids

  There is no file path in the key, so identical chunk text in two files is one entry.
- **Pass the real model fingerprint, not a label.** `RopeParameters` holds only rotated dims, theta and pairing. RoPE scaling
  fields (scaling type and factor, original context, attention factor, YaRN betas), NoPE layers and the per-layer KV layout
  reach the key only through `ChunkFingerprint.Compute(config, ...)`. A caller that passes a hand-made label could get the same
  key for two differently scaled models. The test `Key_RopeScalingFieldsOnlyInFingerprint_StillDifferentKeys` pins the
  correct path.
- **Schema version, not build version.** The fingerprint and the key hash `ChunkReuseSchema.KvOutputVersion` (an integer,
  currently 1), not the build's commit SHA, so a rebuild keeps stored chunks valid. Bump it by hand whenever a change moves the
  K/V a chunk encodes to. `ChunkReuseSchemaTests.Encode_TinyModel_MatchesGoldenForCurrentKvOutputVersion` holds a golden K/V
  summary per version for the synthetic test model and fails when the K/V change without a new version and a new golden row.
  It uses a relative tolerance of 1e-4, because CPU SIMD paths differ by ISA. Changes below that are not detected; a 1.00001×
  scale on K passes.
- **File** `root/<hex[0..2]>/<hex>.ckv`:
  - a 452-byte header for Qwen3-4B: magic, format version 1, dtype, key, fingerprint, token count, per-layer K/V lengths,
    payload size
  - then the token ids
  - then the K/V rows of every layer, as stored in the `ChunkKvEntry`
- **Precision:** `ChunkKvEntry` holds F32 rows because the CPU oracle cache (`SimpleKvCache`) is F32, so the store writes F32
  and does not convert. The dtype is in both the key and the header, but only F32 is implemented. Any other tag is read as a
  miss.
- **Safety:**
  - **Write:** to a unique temp file, flush, then one rename to the final name.
  - **Read:** through a memory map. Magic, version, dtype, key and the exact file length are checked. Truncation, trailing
    bytes, another version or another key's file are misses, never wrong hits.
  - **Destination busy:** on Windows a mapped destination cannot be replaced. If the destination is valid (another writer
    stored the same key), Put returns. If it is invalid and still held by a reader, Put throws `ChunkStoreBusyException` at
    once and stores nothing, without a retry loop; a later Put repairs it.
  - **Temp files:** a crashed writer can leave its temp file behind. `GetStats()` counts entries and temp files separately,
    and `SweepTempFiles(olderThan)` removes old temp files.

## Measurement (Qwen3-4B-Instruct-2507 Q4_K_M, CPU)

Command:

```
ChunkKvLab store-probe --model <Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf> --corpus <t8-corpus-AFClaude-...> --store <empty dir> --chunks 3 --threads 8
```

- **Model:** HF cache `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF`, snapshot `ae44f08e1392f39c0e474af10c3ff8355c8b6688`.
- **Corpus:** the frozen AFClaude snapshot `t8-corpus-AFClaude-b3f29c30-20261101111141` from `../corpus.md`, E1 512-token
  chunker.
- **Log:** [`store-probe.log`](store-probe.log), from a Release build of dotLLM `63cebfbd` (dirty=0).
- **Earlier run:** made with a binary built at `6d3e3116` plus StoreProbe code that was not yet committed (committed
  unchanged as `0c6a3ac0`). That was disclosed and has been replaced by this run. Sizes are identical, and the timings are in
  the same range.

| quantity | value |
|---|---|
| geometry | 36 layers, 8 KV heads, head dim 128, so the KV stride is 1024 floats per layer |
| **bytes per token per layer (F32 K+V)** | **8,192**. Measured in the file, equal to the analytic 2 × 1024 × 4 |
| bytes per token (all layers) | 294,912 (288 KiB) |
| file per 512-token chunk | 150,997,444 B (144 MiB). 452 B of that is header, 2,048 B is token ids |
| round trip | bit-exact for all 3 chunks |

**Speed checkpoint:** the new path (a store read) against the previous path (a fresh `ChunkEncoder.Encode`). Each row is one
512-token chunk. The CPU was about 93 % busy with two other ChunkKvLab processes from another session, so the timings are
rough.

| chunk | encode (fresh) ms | put ms | get ms (new store instance) | encode / get |
|---:|---:|---:|---:|---:|
| 1 | 11,629 | 207 | 229 | 51× |
| 1 (drawn again) | 10,404 | 0.5 (already stored: short-circuit) | 231 | 45× |
| 16 | 9,668 | 178 | 199 | 49× |

On this contended CPU, a read was 45–51× faster than re-encoding; the earlier run gave 43–62×. The read copies the mapped file
into `float[][]`. The OS page cache was warm, because the file had just been written. A cold read from disk was not measured.

## What this means for Phase S

- **F32 does not fit a large repo.** The 1.5 M-token codesharp corpus would need 1.5 M × 288 KiB ≈ **442 GB (412 GiB)**, and
  the 2K-token E4 context alone is 576 MiB. F16 rows would halve that (≈ 221 GB / 206 GiB). Q8_0 rows (34 B per 32 elements)
  would bring it to ≈ 0.27× of F32 (≈ 117 GB / 110 GiB). Compact F16/Q8_0 rows are deferred to a separate task, as the
  controller ruled. The key and header already carry the dtype.

# Store-backed assembly parity (Phase S, Task 3)

dotLLM branch `feature/chunk-store`:

- `src/DotLLM.ChunkReuse/Store/StoredContextAssembler.cs` (`8d1d83ff`; review fixes in `3d35d20f`)
- `src/DotLLM.ChunkReuse/GgufIdentity.cs` (`3d35d20f`)
- tests `tests/DotLLM.Tests.Unit/ChunkReuse/{StoredAssemblyTests,GgufIdentityTests}.cs`
- lab command `ChunkKvLab store-assembly` (`benchmarks/ChunkKvLab/StoreAssemblyCheck.cs`, `a806f4c0`)

## What it does

`StoredContextAssembler.Assemble(chunks, model, store, destination?, query)` returns `StoredAssembly(Context, Stats, Entries)`.
It deconstructs to `(Context, Stats)`.

- **Counts.** `Stats = AssemblyStats(Hits, Misses, EncodedTokens, Repeats)`, and `Hits + Misses + Repeats` is the chunk count.
  - `Hits` counts store hits only.
  - `Repeats` counts chunks whose key already occurred earlier in the same call. They reuse that entry with no store read and
    no encode.
- **Lookup.** Each chunk is looked up under `ChunkKey.Create(fingerprint, tokenizer, RoPE from config, "cpu", F32, tokens,
  positioning: Isolated)`.
- **Hit check.** A hit is accepted only when the entry has this fingerprint, exactly the chunk's token ids, and one
  `[n, stride(l)]` K and V array per KV layer. A well-formed entry that fails these checks is evicted, re-encoded and replaced
  (`Rejected`).
- **Store failures are misses.**
  - A damaged, truncated, old-format, foreign-key or stale-schema entry is re-encoded and stored, never an error.
  - If the store cannot write, the fresh entry is used and not stored, and `StoreFailures` counts it. That covers Put throwing
    `ChunkStoreBusyException`, and Evict of a rejected entry throwing `IOException` or `UnauthorizedAccessException`. A later
    call repairs the entry.
  - Any other store exception propagates.
- **Validation before any work.** The chunks, the model identity (see below) and the destination are all checked before any
  store read or encode. The destination check covers exact host F32, the layer count, the per-layer strides and the capacity
  (`CurrentLength + Σn ≤ MaxLength`). The destination is left unchanged whenever the call throws.
- **Non-empty destination.** The chunks are appended at the destination's `CurrentLength`, and that value is returned as
  `DestinationOffset`. `Context.ChunkStarts` stays relative to the context, so chunk `c` sits at destination row
  `DestinationOffset + ChunkStarts[c]`. The keys are re-rotated to those absolute positions; a test compares this bit-exactly
  against placing `[D, A, B]` in one call.

## Identity contract

- **The fingerprint is the caller's responsibility.**
  - `new StoredContextAssembler(fingerprint, tokenizerId)` does not tie the fingerprint to the model passed to `Assemble`. A
    mismatched pair would write one model's K/V under another model's keys, and every later reader would accept them (store
    poisoning).
  - `StoredContextAssembler.ForModel(config, modelId, quant, tokenizerId)` keeps the fingerprint inputs and refuses a model
    whose configuration does not reproduce the fingerprint (shape, RoPE, NoPE layers, KV layout). It cannot see the weights, so
    the model id must itself be content-based.
- **Content-based ids (`GgufIdentity`), now used by the lab instead of the file name:**
  - `ModelId(gguf)` hashes every shard of the file or split set, in order. For each shard it hashes the index, the length, the
    header (all metadata and the tensor table), and the first and last 4 KiB of every tensor's data. A renamed file or set keeps
    its id. Split GGUFs are supported, with a synthetic 2-shard test.
  - **What the sampled id misses.** It does not catch edits strictly inside a tensor, more than 4 KiB from both ends, when the
    metadata (including `general.name`), the tensor table and the length are identical. Examples:
    - a fine-tune that trains only interior rows of `token_embd` or `output`;
    - surgical edits of a few rows;
    - a tool that rewrites only interior blocks;
    - adversarial files.
  - **What it does catch.** Dense changes alter every tensor's head: full fine-tunes, merges, merged attention or MLP LoRAs,
    re-quantization and imatrix changes. Edits to the last rows, such as trained reserved or special tokens at the end of the
    vocabulary, fall in the sampled tail.
  - **Full hash.** `ModelId(gguf, fullHash: true)` hashes every byte and gives a `gguf-full-sha256:` prefix. The planned
    `chunkcache build --strict-model-id` will use it. A hub revision is the other option.
  - `TokenizerId` is the SHA-256 of the `tokenizer.ggml.*` metadata, in key order and length-prefixed. The chat template does
    not take part.
  - On Qwen3-4B Q4_K_M: model id `gguf-sha256:383e0dc9…` (head and tail samples, `e3cd917d`), tokenizer id
    `gguf-tokenizer-sha256:ac4d5cb5…`, quant label `ftype-15` (from `general.file_type`). The sampled hash adds no measurable
    load time with a warm page cache (0.6–1.0 s load). Cold-disk cost was not measured: the header plus 2 × 4 KiB per tensor.
- **Isolated encodes only.**
  - Store entries must be `ChunkEncoder` encodes of the chunk alone at positions `0..n-1`. This is documented in `IChunkStore`,
    `ChunkKey` and the assembler.
  - The positioning is now part of the key (`ChunkPositioning.Isolated` or `Contextual`, key scheme `chunk-key/v3`). K/V
    computed with preceding context, such as a recompute output, would be stored as `Contextual` and never answer an isolated
    lookup. A test checks this.
  - Keys written by Task 2 (`chunk-key/v2`) no longer match. Those stores were deleted.

## Namespace in the key (Phase I Task 2, L8): key scheme `chunk-key/v4`

- **What changed.** `ChunkKey.Create(..., positioning, string @namespace = ChunkNamespace.Default)` hashes a store partition,
  length-prefixed, right after the scheme string. The default namespace `""` is hashed too (a zero length), never skipped,
  so no v4 key equals a v3 key.
- **Namespaces.** `ChunkNamespace.Default` (`""`) is for a single-user local store. `ChunkNamespace.ForApiKey(key)` is
  `"k-"` + the first 16 lowercase hex of SHA-256 over the key's UTF-8 bytes. It never holds the key and never equals the
  default; an empty key is refused (a caller without a key uses the default).
- **Validity rule** (review S1, `a152e504`): a namespace matches `^(|k-[0-9a-f]{16}|[a-z0-9._-]{1,64})$` (empty = default),
  checked by `ChunkNamespace.IsValid` / `Validate` and enforced by `ChunkKey.Create` and, before any store read, by
  `StoredContextAssembler.Assemble`. Valid namespaces are plain ASCII, safe in file names, JSON and logs. The namespace is also
  hashed with a throwing UTF-8 encoder, because the default encoder turns every lone surrogate into U+FFFD
  (`"\uD800"` and `"\uDC00"` would otherwise share every key). Golden values did not change.
- **Assembler.** `StoredContextAssembler.KeyOf(config, ids, @namespace = Default)` and `Assemble(..., query, @namespace =
  Default)`. One namespace's entries are never hits, rejects or evictions in another.
- **Indexes.** An index's producer identity is `keyOf([])`, so it includes the namespace: an index saved under one namespace
  loads empty, with a `LoadNote`, under another.
- **v3 stores are rebuilt, not migrated.** Every v3 key misses under v4, including the default namespace. `.ckv` entries and
  indexes written before Phase I Task 2 are stale: run `chunkcache build` again (it re-encodes under the v4 keys), then
  `chunkcache evict` to collect the v3 files as orphans once no index references them. The `.ckv` format (version 2) did not
  change; only the file names (keys) did.
- Tests: `ChunkStoreTests.{Key_DefaultNamespace_GoldenV4, Key_DiffersByNamespace, ForApiKey_IsStable_AndNeverEqualsDefault,
  Index_SavedUnderOtherNamespace_LoadsEmptyWithNote}`, `StoredAssemblyTests.Assemble_OtherNamespace_AllMisses`. The v4
  goldens were derived by an independent Python re-implementation of the encoding that reproduces the v3 goldens.

## Measurement (Qwen3-4B-Instruct-2507 Q4_K_M, CPU, 8 threads)

**Run setup.**

- `ChunkKvLab store-assembly` on the E4 kept contexts (symbol chunker, seed 0, 2K tokens).
- Docagent has only 17 kept contexts, so all 17 were used, plus the first 3 afclaude contexts: 20 contexts and 33 tasks.
- Logs: [`assembly-docagent.log`](assembly-docagent.log), [`assembly-afclaude.log`](assembly-afclaude.log). Per-task CSVs are
  next to them.
- Release build of `a806f4c0` (dirty=0). That build predates the review fixes, so it keyed by file-name identities, and its
  `cold_hits` include in-call repeats. Neither affects parity or the timings.

**Three assembly paths per context.**

- **fresh:** `ChunkEncoder` plus `ChunkAssembler`, with no store.
- **cold:** store-backed. One store was shared across the contexts of each corpus run (docagent and afclaude each had their own
  store), so a chunk seen in an earlier context of the same run is a hit.
- **warm:** store-backed, with a new store instance, so every chunk is read from disk.

Every task was then evaluated teacher-forced on the fresh cache and on the warm cache.

| quantity | value |
|---|---|
| caches bit-identical (fresh = cold = warm, all layers, all rows) | **20 / 20 contexts** |
| continuation logits bit-identical (warm vs fresh) | **33 / 33 tasks** (max \|Δ\| 0, KL 0, top-1 1.0) |
| masked-call NLL identical / greedy EM fresh vs warm | 33 / 33; 6 vs 6 (naive concatenation, no recompute) |
| warm assembly (2K tokens, 12–23 chunks, all from the store) | mean **668 ms**, median 655 ms (556–801) |
| fresh assembly | mean 32,989 ms, median 30,830 ms |
| cold assembly (encode + put; 91 hits incl. in-call repeats, 241 misses) | mean 22,764 ms |
| fresh / warm, per context | **median 47.2×**, mean 49.7×, min 31.1×, max 81.6× |
| docagent store after 17 contexts | 206 entries, 7,994,086,208 B = 7.99 GB = 7.44 GiB (F32) |

Per context. Cold hits marked * include in-call repeats as well as chunks shared with earlier contexts of the same run.

| context | chunks | cold encoded / context tokens | fresh ms | cold ms | cold hits* / misses | warm ms | fresh / warm |
|---|---:|---:|---:|---:|---:|---:|---:|
| doc0 | 14 | 2040 / 2040 | 49,946 | 30,322 | 0 / 14 | 636 | 78.5× |
| doc1 | 16 | 2013 / 2048 | 46,193 | 33,714 | 1 / 15 | 759 | 60.9× |
| doc2 | 22 | 2048 / 2048 | 53,199 | 31,674 | 0 / 22 | 652 | 81.6× |
| doc3 | 22 | 2020 / 2048 | 44,470 | 32,016 | 2 / 20 | 747 | 59.5× |
| doc4 | 15 | 1995 / 2048 | 26,981 | 26,533 | 2 / 13 | 671 | 40.2× |
| doc5 | 12 | 1931 / 2048 | 27,808 | 23,217 | 3 / 9 | 612 | 45.4× |
| doc6 | 12 | 1915 / 2047 | 22,288 | 21,311 | 1 / 11 | 716 | 31.1× |
| doc7 | 18 | 1848 / 2048 | 32,801 | 23,101 | 6 / 12 | 618 | 53.1× |
| doc8 | 20 | 1069 / 2046 | 24,071 | 13,254 | 7 / 13 | 556 | 43.3× |
| doc9 | 19 | 1841 / 2048 | 22,791 | 19,436 | 6 / 13 | 612 | 37.2× |
| doc10 | 23 | 1106 / 2045 | 22,311 | 20,368 | 9 / 14 | 642 | 34.8× |
| doc11 | 12 | 1992 / 2046 | 31,274 | 31,135 | 1 / 11 | 602 | 52.0× |
| doc12 | 13 | 889 / 2045 | 28,884 | 19,654 | 5 / 8 | 801 | 36.1× |
| doc13 | 20 | 1290 / 2043 | 33,350 | 22,000 | 10 / 10 | 642 | 51.9× |
| doc14 | 16 | 1378 / 2048 | 23,533 | 15,171 | 8 / 8 | 744 | 31.6× |
| doc15 | 14 | 1312 / 2044 | 34,796 | 17,282 | 7 / 7 | 577 | 60.3× |
| doc16 | 19 | 419 / 2041 | 34,185 | 5,902 | 13 / 6 | 697 | 49.0× |
| afc0 | 12 | 2045 / 2045 | 27,340 | 27,399 | 0 / 12 | 684 | 40.0× |
| afc1 | 14 | 1823 / 2041 | 30,386 | 32,310 | 2 / 12 | 735 | 41.3× |
| afc2 | 19 | 602 / 2048 | 43,167 | 9,481 | 8 / 11 | 658 | 65.6× |

**Caveats:**

- **The box was shared**, with other agents building in parallel, so the times are rough.
- **Contention varied over time.** Fresh took 44–53 s for docagent contexts 0–3 and about 22–35 s afterwards. This is most
  likely time-varying contention early in the run rather than an ordering effect. Fresh always ran first in each context, so
  the data cannot rule out ordering.
  - On the three contexts where cold had no hits, cold was faster than fresh only for doc0 (49.9 → 30.3 s) and doc2
    (53.2 → 31.7 s). For afc0 it was the same (27.3 → 27.4 s).
  - Those early contexts inflate the mean ratio, so the median (47.2×) is the better summary.
- **Put cost:** about 0.2 s per chunk (Task 2).
- **Page cache:** the warm pass reads files that the cold pass had just written, so they were in the OS page cache, possibly
  still as dirty pages. A cold-disk read was not measured.
- **Timing asymmetry, since fixed:** in this run the fresh time included allocating its cache and the other paths did not.
  This is negligible against 33 s, and the lab now allocates outside the stopwatch.
- **Cleanup:** the stores were deleted after the run.

**Open point:**

- The `.ckv` header does not yet persist the backend tag.
- `ChunkKvEntry.Backend` exists only on `feature/chunk-reuse-vulkan`.
- The backend is part of the key, so a cross-backend wrong hit is impossible today.
- The skipped test `StoredAssemblyTests.TODO_StoreHeader_PersistsBackendTag` (`TODO(chunk-store-backend-in-header)`) holds the
  place until those branches meet.
