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

dotLLM branch `feature/chunk-store`: `src/DotLLM.ChunkReuse/Store/StoredContextAssembler.cs` (`8d1d83ff`), tests
`tests/DotLLM.Tests.Unit/ChunkReuse/StoredAssemblyTests.cs` (`8d1d83ff`, `955a0af4`), lab command `ChunkKvLab store-assembly`
(`benchmarks/ChunkKvLab/StoreAssemblyCheck.cs`, `a806f4c0`).

## What it does

`StoredContextAssembler(fingerprint, tokenizerId).Assemble(chunks, model, store, destination?, query)` returns
`StoredAssembly(Context, Stats, Entries)` (deconstructs to `(Context, Stats)`), where `Stats = AssemblyStats(Hits, Misses,
EncodedTokens)`.

- It looks each chunk up under `ChunkKey.Create(fingerprint, tokenizer, RoPE from config, "cpu", F32, tokens)`.
- It accepts a hit only when the entry has this fingerprint, exactly the chunk's token ids, and one `[n, stride(l)]` K and V
  array per KV layer. A well-formed entry that fails these checks is evicted, re-encoded and replaced (`Rejected`).
- A damaged, truncated, old-format, foreign-key or stale-schema entry is a miss: it is re-encoded and stored, never an error.
- A chunk that appears twice in one context is encoded once.
- If Put throws `ChunkStoreBusyException`, the fresh entry is used and not stored (`StoreFailures`), and a later call repairs
  the entry. Any other store exception propagates.
- The entries are then placed with `ChunkAssembler`.

## Measurement (Qwen3-4B-Instruct-2507 Q4_K_M, CPU, 8 threads)

`ChunkKvLab store-assembly`, E4 kept contexts (symbol chunker, seed 0, 2K tokens):

- 17 docagent contexts (all that docagent has) and the first 3 afclaude contexts, giving 20 contexts and 33 tasks.
- Logs: [`assembly-docagent.log`](assembly-docagent.log), [`assembly-afclaude.log`](assembly-afclaude.log). Per-task CSVs are
  next to them.
- Release build of `a806f4c0` (dirty=0).

Each context is assembled three ways:

- **fresh:** `ChunkEncoder` plus `ChunkAssembler`, with no store.
- **cold:** store-backed, against one store shared across contexts, so a chunk seen in an earlier context is a hit.
- **warm:** store-backed, with a new store instance, so every chunk is read from disk.

Every task is then evaluated teacher-forced on the fresh cache and on the warm cache.

| quantity | value |
|---|---|
| caches bit-identical (fresh = cold = warm, all layers, all rows) | **20 / 20 contexts** |
| continuation logits bit-identical (warm vs fresh) | **33 / 33 tasks** (max \|Δ\| 0, KL 0, top-1 1.0) |
| masked-call NLL identical / greedy EM fresh vs warm | 33 / 33; 6 vs 6 (naive concatenation, no recompute) |
| warm assembly (2K tokens, 12–23 chunks) | mean **668 ms** (556–801), all hits |
| fresh assembly | mean 32,989 ms (median 30,830) |
| cold assembly (encode + put; 91 hits, 241 misses over 20 contexts) | mean 22,764 ms |
| fresh / warm | mean **49.7×**, min 31.1× |
| store after 17 docagent contexts | 206 entries, 7.99 GB (F32) |

**Caveats:**

- The box was shared with other agents' builds, so the times are rough.
- The fresh pass ran first in each context. On the 3 contexts where cold had no hits, cold was faster than fresh (29.8 s vs
  43.5 s), so the order and the contention matter at this scale. Put costs about 0.2 s per chunk (Task 2).
- Warm reads come from a just-written store, so the OS page cache is warm. A cold-disk read was not measured.
- The stores were deleted after the run.

**Open point:**

- The `.ckv` header does not yet persist the backend tag.
- `ChunkKvEntry.Backend` exists only on `feature/chunk-reuse-vulkan`.
- Until those branches meet, the skipped test `StoredAssemblyTests.TODO_StoreHeader_PersistsBackendTag` holds the place for this.
