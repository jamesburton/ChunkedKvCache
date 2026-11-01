# Chunk store: size and speed checkpoint (Phase S, Task 2)

dotLLM branch `feature/chunk-store` (worktree `C:\Development\dotLLM\.claude\worktrees\chunk-store`, not pushed):
`src/DotLLM.ChunkReuse/Store/{ChunkKey,IChunkStore,FileChunkStore}.cs`, tests `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkStoreTests.cs`,
lab command `ChunkKvLab store-probe` (`benchmarks/ChunkKvLab/StoreProbe.cs`).

## What the store is

- **Key** (`ChunkKey.Create`): SHA-256 over a length-prefixed canonical encoding of model fingerprint, tokenizer id, RoPE
  parameters (rotated dims, theta bits, pairing), engine version, **backend** (`cpu`, `vulkan`, ...), **KV dtype** and the chunk
  token ids. No file path, so identical chunk text in two files is one entry.
- **File** `root/<hex[0..2]>/<hex>.ckv`: 452-byte header for Qwen3-4B (magic, format version 1, dtype, key, fingerprint,
  token count, per-layer K/V lengths, payload size), then token ids and the K/V rows of every layer as stored in the
  `ChunkKvEntry`.
- **Precision:** `ChunkKvEntry` holds F32 rows because the CPU oracle cache (`SimpleKvCache`) is F32, so the store writes
  F32. It does not convert. The dtype is in both the key and the header so F16/Q8_0 entries can be added later without a
  format bump, but only F32 is implemented. Other dtypes read as misses.
- **Safety:** written to a unique temp file, flushed, then renamed to the final name. Read through a memory map. The reader
  checks magic, version, dtype, key and the exact file length. Truncation, trailing bytes, another version or another key's
  file are all misses, never wrong hits.

## Measurement (Qwen3-4B-Instruct-2507 Q4_K_M, CPU)

Command (model: HF cache `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF`, snapshot `ae44f08e1392f39c0e474af10c3ff8355c8b6688`;
corpus: the frozen AFClaude snapshot `t8-corpus-AFClaude-b3f29c30-20261101111141` from `../corpus.md`, E1 512-token chunker):

```
ChunkKvLab store-probe --model <Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf> --corpus <t8-corpus-AFClaude-...> --store <empty dir> --chunks 3 --threads 8
```

Log: [`store-probe.log`](store-probe.log). dotLLM commit `27191c9f` (dirty=0). The binary was built at `6d3e3116` plus the
StoreProbe code later committed unchanged as `0c6a3ac0`, so the engine string ends `+6d3e3116...`.

| quantity | value |
|---|---|
| geometry | 36 layers, 8 KV heads, head dim 128, so the KV stride is 1024 floats per layer |
| **bytes per token per layer (F32 K+V)** | **8,192**. Measured in the file, equal to the analytic 2 × 1024 × 4 |
| bytes per token (all layers) | 294,912 (288 KiB) |
| file per 512-token chunk | 150,997,444 B (144 MiB). 452 B of that is header, 2,048 B is token ids |
| round trip | bit-exact for all 3 chunks |

**Speed checkpoint** (the new path, store read, against the previous path, a fresh `ChunkEncoder.Encode`). Each row is one
512-token chunk. The CPU was about 87 % busy with another session's ChunkKvLab jobs, so treat these as rough numbers.

| chunk | encode (fresh) ms | put ms | get ms (new store instance) |
|---:|---:|---:|---:|
| 1 | 10,244 | 161 | 198 |
| 1 (drawn again) | 12,438 | 0.5 (already stored: short-circuit) | 288 |
| 16 | 11,566 | 192 | 187 |

A warm read is about 40–60× faster than re-encoding on this contended CPU. The read is a copy out of the mapped file into
`float[][]`, and the OS page cache was warm because the file had just been written. A cold read from disk was not measured.

## What this means for Phase S

- **F32 does not fit a large repo.** Storing the 1.5 M-token codesharp corpus would take 1.5 M × 288 KiB ≈ **442 GB**, and the
  2K-token E4 context alone is 576 MiB. F16 would halve that (≈ 221 GB). Q8_0 rows (34 B per 32 elements) would bring it to
  ≈ 0.27× of F32 (≈ 117 GB). A store for real solutions needs a quantized or F16 KV dtype in `ChunkKvEntry` and the
  assembler. That is a design decision for Task 3/4 (precision rules: quantized KV stays quantized). The header and key are
  already ready for it.
- **Engine-version granularity is open.** `ChunkFingerprint.EngineVersion` (and so the model fingerprint) contains the build
  commit SHA, so every rebuild invalidates every stored chunk. Same in the key's `engineVersion` if callers pass it. Phase S
  needs a stable "KV-affecting engine version" chosen by the user/dotLLM lead.
