# 01 — Code-verified map of dotLLM's KV and prefill path (Task 3)

**Source read:** dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse`, branch `feature/chunk-kv-reuse`,
commit `4a7818290766b69a3bae0999874154185c7fa587`. Read-only; no dotLLM file was changed.
All paths below are relative to that worktree's `src/` unless they start with `tests/`. Every claim was checked against the code, not the docs.

Status legend: **verified-by-code** = read in the source at the cited lines. **still unknown** = needs a run or a file we have not read.

---

## Summary (what Tasks 4-6 need to know)

| # | Question | Answer | Status |
|---|---|---|---|
| a | K pre- or post-RoPE? dtype? | **Post-RoPE in all three caches** (CPU `SimpleKvCache`, CPU `PagedKvCache`, `VulkanKvCache`). Qwen3 QK-norm is applied before RoPE, so stored K = RoPE(KNorm(Wk·x)). dtype: Simple = F32; Paged = F16 by default (Q8_0 option, F32 reference only); Vulkan = F32 for every architecture except Flint (so F32 for Qwen3/Llama). | verified-by-code |
| b | Prefill call shape; can a cache be filled externally and continued? | `ForwardPrefill` calls `IModel.Forward(tokens, positions=prefillStart+i, -1, kvCache, adapter, mtp, lastTokenLogitsOnly:true)`. Cache writes are scatter-by-position, so **yes at the `IModel.Forward` level**: fill a `SimpleKvCache` with `Update` at any positions, then `Forward(suffix, [N..])`. **Not through `TextGenerator`** without a change (`PrefixCache.Store` is `internal`). | verified-by-code |
| c | CPU layer loop; can a token subset be run per layer? | `TransformerModel.RunLayerRangeCore` (one loop for all entry points). A subset run through `Forward` gets correct RoPE and correct cache writes, but **the causal mask assumes contiguous query rows** (`qPos = positions[0] + i`). Exact workaround with zero dotLLM change: run each maximal contiguous run of selected positions as its own `Forward`, in ascending order. Per-layer stepping exists (`ForwardLayerWindow`) but is `internal` and hard-wires `kvCache: null`. | verified-by-code |
| d | `IInferenceHook` per-layer activations; K/V reachable? | **`IInferenceHook` is dead code**: declared in `DotLLM.Core`, never invoked by any model or engine. K/V are reachable another way: read the cache after the forward (`SimpleKvCache.KeysSpan/ValuesSpan`, public, F32). | verified-by-code |
| e | What Vulkan needs for externally filled KV | Nothing for E1: `VulkanKvCache` implements `IHostStagedKvCache.UploadLayer` (F32 host rows → device) and is used that way by the hybrid CPU-prefill/Vulkan-decode handoff. Limits: F32 only, always writes positions `[0, length)` (no start offset), host-side `Update`/`GetKeysRef` throw. | verified-by-code |
| — | Qwen3 model class | GGUF `qwen3` → `Architecture.Qwen` → CPU `TransformerModel`, Vulkan `VulkanTransformerModel` + `VulkanKvCache`. | verified-by-code |
| — | Exact RoPE table variant for Qwen3-4B-Instruct-2507 GGUF (plain / freq-factors / YaRN) | Depends on the GGUF's rope-scaling metadata. | **still unknown** (read the GGUF in Task 4) |

---

## (a) Where and how K is stored

### CPU `TransformerModel` → `SimpleKvCache` / `PagedKvCache` (verified-by-code)

Order of operations in the GQA branch of `DotLLM.Models/Architectures/TransformerModel.cs`:

1. Q/K/V projections — prefill `GemmInterleaved` 1667-1672 (decode `FusedQkvDecode` 1647); bias 1677-1679; LoRA delta 1694-1708.
2. **QK-norm before RoPE** — `ApplyPerHeadNorm(lw.KNormWeight, k, …)` 1720-1723 (Qwen3 has `k_norm`).
3. **RoPE in place on Q and K** with per-token positions — `RoPE.Execute(q, k, positions, …)` 1732-1741, skipped only on NoPE layers.
4. **Cache write after RoPE** — `kvCache.Update(kRef, vRef, positions, layer)` 1775 (`kRef` wraps the rotated `k`, `TensorRef(seqLen, kvStrideLayer, DType.Float32, -1, k)` 1765-1766).
5. Attention reads the cache — 1777-1793.

The method doc says the same: "K/V projections are stored in the cache after RoPE" (714-716). Row layout: `[position][numKvHeads × headDim]`, heads contiguous within a row.

`RoPE.Execute` (`DotLLM.Cpu/Kernels/RoPE.cs` 564-600) rotates token `t` by `positions[t]` using rows of a precomputed cos/sin table (`cosTable.Slice(pos * halfRopeDim, …)` 579-581). The Q loop runs `numHeads` times (584), so passing `numHeads: 0` and an empty Q span rotates K only.

dtypes:
- **`SimpleKvCache`** (`DotLLM.Engine/KvCache/SimpleKvCache.cs`): F32 `[maxSeqLen, stride]` per layer (doc 8-13; alloc 96-102; `GetKeysRef` returns `DType.Float32` 168-169). `SupportsExactF32PrefixCopy => _rows is null` (17) — true unless the geometry has compact sliding-window layers (none for Qwen3/Llama).
- **`PagedKvCache`** (`DotLLM.Engine/KvCache/PagedKvCache.cs`): accepts F32 host rows (`Update` checks `DType.Float32` 130-134) and encodes them into the pool element type via `_pool.EncodeRows` (175-176). Pool type is F16 by default, Q8_0 optional, F32 "reference only" (`KvBlockPool.cs` 14-16, 99-111; `PagedKvCacheFactory.cs` 30-45, `elementType ?? DType.Float16`). So a paged destination is **lossy** (F16/Q8_0) unless built with F32.
- **`QuantizedKvCache`** (CPU `--cache-type-k q8_0|q4_0`): Q8_0/Q4_0 with optional F32 recent window (`QuantizedKvCache.cs` header); same post-RoPE input.

### Vulkan `VulkanTransformerModel` → `VulkanKvCache` (verified-by-code)

`DotLLM.Vulkan/VulkanTransformerModel.cs`:
- QK-norm `RecordQkNorm` 4415, then either
  - **fused RoPE+KV write** (`_ropeKvWrite.Record(… startPos: positions[0] …)` 4442-4463), gated on F32 `VulkanKvCache`, no compact windows, and `IsContiguousAscending(positions)` 4435-4440; or
  - `RecordRopeQk` 4467-4469 then `vkCache.RecordUpdate(cmdBuf, _state.K, _state.V, positions, …)` 4473-4478. Comment at 4485-4486: "K is stored after RoPE".
- Storage: `DefaultKvStorage` is F16 only for `Architecture.Flint`, **F32 for every other architecture** (1259-1265); `CreateKvCache` passes it through (1402-1418). `VulkanKvStorage` enum F32/F16 (`VulkanNemotronHKvCache.cs` 8-20).
- Quantized Vulkan caches (`VulkanQuantizedKvCache` Q8_0/Q4_0, `VulkanTurboQuantKvCache`) also write post-RoPE K (4491-4520).

**Consequence:** the chunk assembler must re-rotate K by the position delta in every case. Task 4's "no shift when K is stored pre-RoPE" branch never applies.

---

## (b) `TextGenerator` prefill, positions, and external fill

### How prefill calls `Forward` (verified-by-code)

`DotLLM.Engine/TextGenerator.cs`:
- `ResolveKvCache` (1579-1657) returns `(cache, cachedTokenCount, owns)`: prefix-trie hit (1605-1610), `PrefixCache` hit (1612-1642, truncates `SimpleKvCache`/`PagedKvCache` to the matched length 1619-1628), or fresh `AllocateKvCache` (1662-1672; default `new SimpleKvCache(KvGeometry.FromConfig(config, model.SupportsCompactSlidingKv), size)`).
- `prefillStart = cachedTokenCount; prefillLen = promptLen - prefillStart` (542-543).
- `ForwardPrefill` (2198-2257) loops chunks; positions `prefillStart + offset + i` (2224-2226); call `_model.Forward(promptIds[prefillStart+offset ..], positions, deviceId: -1, kvCache, adapter, mtpState, lastTokenLogitsOnly: true)` (2234-2235). Row read is `Shape[0] - 1` (594-596).
- 100 % prefix hit: re-forwards the last prompt token at `promptLen - 1` (609).
- Recurrent models never take a KV-only hit (1588-1602); not relevant to Qwen3.

### Are positions arbitrary? (verified-by-code)

- **Writes: yes.** `SimpleKvCache.Update` writes row `pos - rowBase` for each `positions[i]` and sets `CurrentLength = max(CurrentLength, maxPos + 1)` (109-155). `PagedKvCache.Update` resolves each position to a block, batching contiguous runs (126-184), with copy-on-write for shared blocks (`KvBlockTable.EnsureWritable` 134-144). `RoPE.Execute` uses each token's own position (RoPE.cs 579).
- **Range check:** every position must be `< Config.MaxSequenceLength` (TransformerModel.cs 1135-1141) and `< cache.MaxLength`.
- **Attention: no** — see (c). Queries in one `Forward` call are treated as consecutive positions starting at `positions[0]`.

### Pre-fill externally, then continue (verified-by-code)

Works at the `IModel` level with no dotLLM change:
1. `var cache = new SimpleKvCache(KvGeometry.FromConfig(model.Config, false), maxLen);`
2. For each layer: `cache.Update(kRef, vRef, positions, layer)` with F32 host rows (any positions). `CurrentLength` becomes `max position + 1` after the first layer's write (151-154; one length for all layers).
3. `model.Forward(suffixIds, [N, N+1, …], -1, cache, lastTokenLogitsOnly: true)` — Update writes at N.., attention covers `[0, CurrentLength)` with `positionOffset = N` (TransformerModel.cs 1775-1793), which is exact for a contiguous suffix.

Through `TextGenerator`: **not possible today.** `PrefixCache.FindMatch` and `PrefixCache.Store` are `internal` (`DotLLM.Engine/PromptCache/PrefixCache.cs` 35, 61); `DotLLM.Engine.csproj` grants InternalsVisibleTo only to `DotLLM.Tests.Unit`, `GumbelVerifyAb`, `DotLLM.Tests.Integration` (8-10). The public `kvCacheFactory` constructor hook (241-242) does not help: a factory cache is returned with `cachedTokenCount = 0` (1654-1655), so prefill restarts at position 0 and overwrites it.
- Smallest change (only if needed): add `<InternalsVisibleTo Include="DotLLM.ChunkReuse" />` to `DotLLM.Engine.csproj`, or a public `PrefixCache.Seed(int[] tokens, IKvCache cache)`. **Recommendation:** not needed for Phase R/P — the `ChunkKvLab` drives `IModel.Forward` directly (greedy loop of its own). Defer `TextGenerator` integration to Phase S.

### Reusing the existing snapshot machinery (verified-by-code)

- `SnapshotPrefix` / `RestorePrefixFrom` exist only on `VulkanNemotronHKvCache` (`DotLLM.Vulkan/VulkanNemotronHKvCache.cs` 499-521): device-to-device copy of positions `[0, length)`, same storage format, used by the hybrid GDN models (`VulkanQwen3HybridDenseTransformerModel.cs` 1226-1253, `VulkanLfm2MoeTransformerModel.Snapshots.cs`). **Not available on `VulkanKvCache`** (Qwen3's cache), and it copies verbatim at offset 0 — it cannot place a chunk at offset o or re-rotate K.
- `IModel.SnapshotSequencePrefix` / `RestoreSequencePrefix` (`DotLLM.Core/Models/IModel.cs` 371-391) default to `null`/no-op; `TransformerModel` does not implement them. Implementations exist only for recurrent models (`Lfm2MoeTransformerModel.Snapshots.cs` 33-110, `Qwen4ExpTransformerModel.cs` 1093, Vulkan hybrids).
- The CPU LFM2 implementation is the **pattern to copy** for `ChunkKvEntry`: it guards on `SupportsExactF32PrefixCopy` + `IPerLayerKvCache` geometry (56-79) and copies `GetKeysRef(i)`/`GetValuesRef(i)` host F32 rows per layer (82-101). It is model-specific (sealed, needs an `ISsmState`), so reuse the pattern, not the code.
- Dense prefix reuse in `TextGenerator` keeps the whole cache object and truncates it (`SetCurrentLength`, 1619-1628); nothing to reuse for chunk placement.

---

## (c) CPU layer loop and running a token subset

### Entry points (verified-by-code)

All in `DotLLM.Models/Architectures/TransformerModel.cs` (`public sealed unsafe class TransformerModel : IModel, IEmbeddingModel`, line 22):

| Entry | Lines | Notes |
|---|---|---|
| `Forward(ids, pos, dev, kvCache)` | 723-728 | `RunLayersAndFinalNormCore` + `RunLmHead` (all rows) |
| `Forward(…, kvCache, lastTokenLogitsOnly)` | 844-849 | what `TextGenerator` reaches via the IModel default at `IModel.cs` 632-637 |
| `Forward(…, kvCache, adapter)` / `ForwardWithAdapter` | 502-544 | LoRA |
| `RunLayersAndFinalNormCore` | 1098-1101 | → `RunLayerRangeCore(…, firstLayer: 0, layerCount: -1, hiddenOut: empty)` |
| **`RunLayerRangeCore`** | 1122-~2300 | the single trunk: embed or `hiddenIn` (1173-1178), layer loop `for (layer = firstLayer; layer < endLayer; layer++)` (1364-1366), GQA branch 1604-…, attention 1759-1805 |
| `ForwardLayerWindow(ids, hiddenIn, positions, firstLayer, layerCount, hiddenOut)` | 760-789 | **`internal`**; calls `RunLayerRangeCore(…, kvCache: null, …)` (787) — layer stepping exists but without a cache |
| `ApplyOutputHead(hidden, seqLen, dev)` | 801-813 | `internal`; final norm + LM head |
| `GuardLayerWindowSupported` | 819-836 | rejects diffusion, MLA, Gemma-3n/4, shared-KV, PLE — plain Qwen3/Llama pass |
| `RunLayersAndFinalNormBatched` | 3638-… | `ForwardBatch` multi-sequence path; not needed |

`DotLLM.Models.csproj` InternalsVisibleTo: `DotLLM.Cuda`, `DotLLM.Vulkan`, `DotLLM.Tests.Unit`, `DotLLM.Tests.Integration`, `DotLLM.Benchmarks`, `EmbeddingBench` (8-13) — **not** a new `DotLLM.ChunkReuse` library.

### The blocker: causal mask assumes contiguous query rows (verified-by-code)

- CPU: `AttendCachedF32(q, kvCache, layer, attnOut, seqLen, positions[0], …)` (1791) and the quantized arm `… positions[0] …` (1785-1787). `AttendCachedF32` passes `seqKv = CurrentLength - rowBase`, `positionOffset - rowBase` (933-950). The kernel computes `qPos = positionOffset + i` (`DotLLM.Cpu/Kernels/Attention.cs` 198) and the causal bound `VisibleEnd = min(seqKv, qPos + 1)` (913-926; explicit mask 804-816).
- Vulkan: same assumption (`positionOffset = positions[0]` 4463 and `positions[0] - rowBase` 4489).

So for `Forward(selectedIds, selectedPositions, cache)` with non-contiguous positions, e.g. `[5, 6, 42]`, the token at true position 42 is masked as if at position 7: it cannot see keys 8-42. Everything else in that call is already right for CacheBlend-style recompute: embeds the subset, RoPE at the true positions, **overwrites the subset's own K/V rows before attention** (1775 then 1791), attends over the full assembled cache, FFN, residual.

Note: a query at position p with `CurrentLength = N > p` is correct — keys `> p` are masked by `VisibleEnd`. So running a contiguous block in the middle of an already-full cache is exact.

### Ways to run a subset (verified-by-code; option 1 needs no dotLLM change)

1. **Contiguous runs, ascending, one `Forward` per run — exact, zero dotLLM change.** Split the selected positions into maximal contiguous runs and call `Forward(runIds, runPositions, -1, cache, lastTokenLogitsOnly: true)` for each run in ascending position order. Proof sketch: for fixed selection, a combined one-pass recompute gives each selected token at layer l the keys `≤ p` where selected keys are fresh at layer l. Run A (earlier positions) never sees run B's keys (causal), and run B sees run A's keys after A has written fresh K/V at every layer. Same result. Cost: one full trunk per run (scattered single tokens → many GEMV-shaped calls). Fine for quality experiments; not for honest TTFT numbers.
2. **Per-token query positions in the attention kernel — the smallest real change.** Add an `Attention.Execute` overload that takes `ReadOnlySpan<int> queryPositions` and uses `qPos = queryPositions[i]` (also for the `IQuantizedKvCache` and `IPagedKvCache` overloads, 1075 and 1137), and pass `positions` instead of `positions[0]` from `AttendCachedF32`/the quantized arm when the positions are not contiguous. Additive, inside `DotLLM.Cpu` + `TransformerModel`; no interface change. Then one `Forward(selectedIds, selectedPositions, cache)` does the whole fixed-selection recompute in one pass, and `ISelectiveRecomputeModel.RecomputeTokens` becomes a thin wrapper over `Forward`.
3. **Per-layer stepping with a cache** (needed only for a selector that looks at layer-1 deviation and narrows the set per layer, i.e. full CacheBlend). `RunLayerRangeCore` already accepts `kvCache`; `ForwardLayerWindow` hard-codes `null` (787). Smallest change: an `internal` overload `ForwardLayerWindow(…, IKvCache? kvCache, …)` that passes it through, plus `<InternalsVisibleTo Include="DotLLM.ChunkReuse" />` in `DotLLM.Models.csproj` (or a public method on the opt-in `ISelectiveRecomputeModel`). The caller keeps each layer's hidden rows for the shrinking subset (`hiddenIn`/`hiddenOut`). Non-contiguous subsets still need option 1 (per run, per layer — also exact by the same argument applied per layer) or option 2.

Caveats: `_state` scratch is per instance, so `TransformerModel` is single-threaded per instance (comment 42-47). MLA state resets on `positions[0] == 0` (1344-1360) — irrelevant to Qwen3/Llama.

---

## (d) `IInferenceHook` and K/V access (verified-by-code)

- `IInferenceHook` (`DotLLM.Core/Diagnostics/IInferenceHook.cs` 7-19), `HookPoint` (PostEmbedding … PostLmHead, no K/V points; `HookPoint.cs` 6-31), `HookContext(LayerIndex, TokenPosition, SequenceId, CurrentStep)` (`HookContext.cs` 10-14), `HookResult` (`HookResult.cs`).
- **No call sites.** A repo-wide search for `IInferenceHook|OnActivation|HookPoint` in `*.cs` finds only those Core files and a comment in `DotLLM.Models/Gguf/SyntheticGemma4Harness.cs` 31. No model, engine, or backend invokes a hook. It cannot expose anything today.
- Other seams: `ActivationRangeProbe` (`DotLLM.Cpu/ActivationRangeProbe.cs`) is env-gated (`DOTLLM_AMAX_PROBE`) and records only amax/block-sum stats for q/k/v (TransformerModel.cs 1768-1773); `Gemma4PostEmbeddingHook` is `internal` and Gemma-only (129, 1182).
- **K/V per layer are reachable without hooks:** after `Forward` on a `SimpleKvCache`, `KeysSpan(layer)` / `ValuesSpan(layer)` (`SimpleKvCache.cs` 228-250, public, F32, `[0, CurrentLength)`) or `GetKeysRef/GetValuesRef` (168-174). That is all `ChunkEncoder` needs. On a `PagedKvCache`, `DownloadLayer` decodes to F32 (238-253).
- Per-layer hidden states (for hidden-state-based selectors) are not exposed; option 3 above (`ForwardLayerWindow` + `hiddenOut`) gives them. Wiring `IInferenceHook` into `RunLayerRangeCore` would be a larger change and is not needed.

---

## (e) Vulkan and externally filled KV (verified-by-code)

`DotLLM.Vulkan/VulkanKvCache.cs`:
- Host-side `Update(TensorRef/ITensor …)`, `GetKeysRef`, `GetValuesRef`, `GetKeys`, `GetValues` all **throw** `NotSupportedException` (388-411).
- **`IHostStagedKvCache`** (`DotLLM.Core/Attention/IHostStagedKvCache.cs` 19-41) is the supported seam: `UploadLayer(layer, length, keys, values)` → `IngestFromHost` (673-674, 586-626): host F32 `[length, kvStride]` → staging → device copy at **dstOffset 0**, advances `CurrentLength` to `max(CurrentLength, length)`. `DownloadLayer` (657-670) reads `[0, CurrentLength)` back to host.
- **F32 only** (`RequireF32` 677-681) and **not on compact sliding-window layers** (`ThrowIfWindowed` 592). Qwen3 on Vulkan is F32 and has no sliding window, so both hold.
- Proven in production: the hybrid CPU-prefill / Vulkan-decode path builds a `SimpleKvCache` on CPU and hands it to the Vulkan cache (`DotLLM.Engine/Strategies/HybridPrefillDecodeStrategy.cs` 26, 243-254; tests `tests/DotLLM.Tests.Integration/Engine/HybridPrefillDecodeTests.cs` 96 `Hybrid_FirstToken_MatchesPureVulkanBaseline`, 187; `tests/DotLLM.Tests.Unit/Vulkan/VulkanCrossDeviceKvTransferTests.cs`).
- After upload, the Vulkan forward attends over `vkCache.CurrentLength` (4462, 4488), so `Forward(suffix, [N..], -1, vkCache)` continues correctly. Uploading does not reallocate buffers, so the descriptor-cache epoch issue (#1100) does not arise.

What E1 on Vulkan needs: **nothing.** Assemble the whole context `[0, L)` per layer on the host (re-rotated F32 rows), `UploadLayer(layer, L, k, v)` for every layer, then forward the suffix. Chunk encoding can even run on Vulkan (forward the chunk into a fresh `VulkanKvCache`, `DownloadLayer`).

Smallest changes, only if later wanted:
- Per-chunk upload at an offset (avoid re-uploading the whole context): add `startPosition` to `IngestFromHost` (`dstOffset = startPos × rowBytes`) — internal to `VulkanKvCache`.
- F16 Vulkan KV: add an F16 arm to `IngestFromHost`/`DownloadLayer` (the code marks this as a known shortcut, 676).
- Selective recompute on Vulkan (after E4 only): same contiguous-query assumption in the attention dispatch (4463/4489); option 1 (runs) works unchanged.

---

## Qwen3 (pure attention) model class (verified-by-code)

- GGUF `general.architecture = "qwen3"` → `Architecture.Qwen` (`DotLLM.Models/Gguf/GgufModelConfigExtractor.cs` 1081; `qwen3moe` → `QwenMoe` 1083, `qwen35` → `Qwen3HybridDense` 1092 — not ours).
- CPU: `ModelLoader.CreateCpuModelFromGguf` switch, `_ => TransformerModel.LoadFromGguf(…)` (`DotLLM.Models/ModelLoader.cs` 71-87).
- Vulkan: `VulkanModelLoader.CreateFromGguf` `default:` → `VulkanTransformerModel.LoadFromGguf` with `CreateKvCache` (`DotLLM.Vulkan/VulkanModelLoader.cs` 159-168) → `VulkanKvCache`, F32.
- Llama-3.1-8B takes the same classes (`"llama" => Architecture.Llama`, 1072).

## RoPE table for `RopeShift` (partly still unknown)

- The model's cos/sin tables live in the `internal sealed` `TransformerForwardState` (`TransformerForwardState.cs` 11, 116, 133) behind the private `_state` (TransformerModel.cs 34); `GetLayerRope(layer)` is private (977-985).
- Table variants: plain `PrecomputeFrequencyTable`, or `PrecomputeFrequencyTableWithFactors` when the GGUF has `rope_freqs.weight` (Llama-3.1, `TransformerForwardState.cs` 177-183; `DenseRopeFreqFactors.Select` 26-42), or **YaRN** `PrecomputeFrequencyTableYarn` with an `mscaleMultiplier` that scales cos/sin magnitude (TransformerModel.cs 388-406).
- Rotation composes (`R(p+Δ) = R(Δ)·R(p)`) for plain and freq-factor tables, so `RopeShift` = `RoPE.Execute(Span<float>.Empty, k, positions: all Δ, numHeads: 0, …)` with the same table. **For a YaRN table with mscale ≠ 1, applying the table row Δ multiplies K by mscale once more** — wrong. Safe for every variant: take the model's table row Δ and normalise each (cos, sin) pair by `sqrt(cos² + sin²)`. Δ ≥ 0 always (chunks are encoded at 0..n-1), so table rows suffice.
- Which variant Qwen3-4B-Instruct-2507's GGUF uses: **still unknown** — read its rope metadata in Task 4.
- Smallest change to use the exact table: `internal (float[] Cos, float[] Sin, int RopeDim, RoPEType Type) GetLayerRopeTable(int layer) => GetLayerRope(layer);` on `TransformerModel` + InternalsVisibleTo for `DotLLM.ChunkReuse`. Alternative with no change: rebuild the table with the public `RoPE.Precompute*` from `ModelConfig` (+ `rope_freqs.weight` for Llama) and pin it with a test against a real forward.

---

## Proposed dotLLM changes (smallest first)

| ID | Change | Needed by | Size |
|---|---|---|---|
| C0 | None: E1 assembly into `SimpleKvCache` (public `Update` at any positions), suffix via `IModel.Forward`, Vulkan via `UploadLayer`, K/V read via `KeysSpan` | Task 4, 5 | — |
| C1 | `<InternalsVisibleTo Include="DotLLM.ChunkReuse" />` (and `ChunkKvLab` if it calls internals) in `DotLLM.Models.csproj` | C2, C4 | 1 line |
| C2 | `internal GetLayerRopeTable(int layer)` on `TransformerModel` returning the existing private tuple | Task 4 `RopeShift` exact table | ~3 lines |
| C3 | Per-token query positions in CPU `Attention.Execute` (+ quantized/paged overloads) and pass `positions` from `AttendCachedF32` when non-contiguous | Task 6 single-pass recompute; honest TTFT | additive overload, ~50-100 lines + tests |
| C4 | `internal ForwardLayerWindow(…, IKvCache? kvCache, …)` passing the cache to `RunLayerRangeCore` | Task 6/7 layer-wise (CacheBlend gradual) selection, layer-1 deviation | ~10 lines |
| C5 | `IngestFromHost(…, startPosition)` on `VulkanKvCache` | Vulkan per-chunk upload (optimisation) | ~10 lines |
| C6 | InternalsVisibleTo `DotLLM.ChunkReuse` in `DotLLM.Engine.csproj` or public `PrefixCache.Seed` | `TextGenerator` integration (Phase S) | 1 line |

None changes `IKvCache`, `IModel`, prefix cache, snapshots, speculative decoding or MTP behaviour. C3/C4 are opt-in paths (contiguous positions keep today's code path).

## Proposed changes to the plan

**Task 4**
- K is post-RoPE everywhere: drop the "no shift when K is stored pre-RoPE" branch; `RopeShift` is always applied.
- `ChunkEncoder.Encode`: fresh `SimpleKvCache(KvGeometry.FromConfig(config, compactSlidingWindows: false), n)`, `Forward(ids, 0..n-1, -1, cache, lastTokenLogitsOnly: true)`, copy `KeysSpan/ValuesSpan` per layer. Stored keys are post-QK-norm, post-RoPE at positions 0..n-1.
- `RopeShift.Apply(keys, headDim, Δ, rope)`: implement as K-only rotation by Δ using the model's own table (C2) with the magnitude normalisation above; `RopeParameters` must carry rope dim, NeoX vs Norm (`RoPEType`), theta, freq factors, YaRN params. Add a test that fails on a YaRN table with mscale ≠ 1 if normalisation is missing. Tolerance 1e-5 may be tight at large Δ (two float32 rotations vs one); measure, and allow ~1e-4 relative if needed.
- Destination gate: accept caches with `SupportsExactF32PrefixCopy == true` (today: `SimpleKvCache` without compact windows) and `VulkanKvCache` with F32 storage (via `IHostStagedKvCache`); throw `NotSupportedException` for `IQuantizedKvCache`, F16/Q8_0 `PagedKvCache` (lossy), F16 `VulkanKvCache`. Extend `Assemble_QuantizedDestination_ThrowsNotSupported` to cover paged F16.
- Fingerprint: include the RoPE table variant and `KvGeometry` strides.

**Task 5**
- "dotLLM's existing prefix reuse" baseline: `PrefixCache.Store/FindMatch` are internal. Either run it through `TextGenerator` with a `PrefixCache` (public ctor; the generator stores automatically after each request) or emulate it in the lab: keep the cache from the previous context and `Rollback(matchedTokens)` (public) before prefilling the suffix.

**Task 6**
- Do not plan a new layer-stepping API inside `TransformerModel` for the core recompute. `Forward(selected, positions, cache)` already does the recompute except for the mask. Implement `RecomputeTokens` first with option 1 (contiguous runs, ascending — exact, zero dotLLM change), which is enough for the three planned tests. Then C3 (per-token mask) for single-pass speed; with C3, `ISelectiveRecomputeModel` reduces to `Forward`.
- If layer-wise narrowing (CacheBlend's layer-1 deviation, gradual filtering) is wanted in Task 6/7, add C4 + C1 and change the interface to expose the layer window, e.g. `void ForwardLayers(IKvCache cache, ReadOnlySpan<int> tokenIds, ReadOnlySpan<float> hiddenIn, ReadOnlySpan<int> positions, int firstLayer, int layerCount, Span<float> hiddenOut)`.
- File path confirmed: `src/DotLLM.Models/Architectures/TransformerModel.cs` (class `TransformerModel`, sealed, line 22).
- Test note: `Recompute_AllTokensSelected_MatchesFullPrefill` is exact under option 1 (all tokens = one run = a normal prefill over the assembled cache).

## dotllm-b7 review

Not done by this task (the controller sends the proposed-change list to `dotllm-b7` and records the reply here).
