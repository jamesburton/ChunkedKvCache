# Requests for the dotLLM Vulkan owner (from Phase G Task 3; not filed, needs the user's approval)

No Vulkan code or shader was changed by this task. Items 1–2 are speed only; values are correct (bit-exact round trips). Items 3–4
are safety checks that ChunkReuse cannot do itself because the needed state is internal.

**Why they matter.** With host entries, Vulkan host-write assembly runs at about 9,000 tok/s, which is no faster than the CPU
assembly (E1 on the CPU: 139–534 ms for 2K–8K). So naive time-to-first-token with host entries is about the same on both backends,
while device-copy assembly is about 8× faster (about 70,000 tok/s). The Phase S chunk store persists **host** entries (write path:
encode, then `ReadRows`; read path: `WriteRows`), so both items sit on the critical path of a real Vulkan TTFT gain from reuse.

## 1. `VulkanKvCache.ReadRows` reads back through uncached host memory (~145 MB/s)

**Observed.** ChunkKvLab `e1 --backend vulkan` (dotLLM `feature/chunk-reuse-vulkan`, Qwen3-4B Q4_K_M, Radeon 8060S, driver
26.10.1). Encoding one 512-token chunk = one 512-row forward into a fresh F32 `VulkanKvCache` + `ReadRows` of 36 layers (K and V,
2 MiB each, 144 MiB total). Measured split per chunk (`results-*-timing.csv`, steps `encode_chunk*`): **readback ≈ 1.0 s**, forward
≈ 0.3 s, cache creation ≈ 30 ms. That is ≈ 145 MB/s for the readback, against ≈ 1.5 ms per 4 MiB `WriteRows` upload.

**Cause (from the code, not instrumented).** `VulkanKvCache.StageDownload` allocates its staging buffer with
`VulkanDevice.Allocate(bytes)` → `AllocateInternal(deviceLocal: false)`, which requires `HOST_VISIBLE | HOST_COHERENT` only. On this
driver that is write-combined, uncached memory; CPU reads from it are very slow. `VulkanDevice.AllocateHostReadback(bytes)`
(`preferHostCached: true`) exists for exactly this and is not used there. `VulkanDevice.Download` has the same pattern.

**Repro.** Any F32 `VulkanKvCache` of 512 rows × 1024 floats per layer: time `ReadRows(layer, 0, 512, k, v)` per layer (expect
≈ 28 ms per layer here), versus the same copy staged through `AllocateHostReadback`.

**Ask.** Use `AllocateHostReadback` for the staging buffer in `StageDownload` (and `Download` for device-local sources), or add
a multi-layer `ReadRows` that stages every layer in one host-cached buffer and one submit.

## 2. Per-call synchronous submits in `WriteRows` / `CopyRowsFrom`

**Observed.** Host-write assembly of a 2K context (4 chunks × 36 layers) spends 213 of 219 ms in `WriteRows` (144 calls, each two
one-shot staging allocations and two fenced submits, ≈ 1.5 ms per call). Device-copy assembly (`CopyRowsFrom`, two fenced submits
per call) takes 24 ms for the same 144 calls. The RoPE shift is no longer a cost: recorded for all 36 layers into one command
buffer through the public `RopeShiftKvKernel.Record` + `VulkanDevice.CreateSubmitContext`, it takes ≈ 0.8 ms per chunk (median; the first call after warm-up takes ≈ 1.3 ms; it was one
submit per layer, ≈ 330 ms for 32 rows × 36 layers together with the row IO in Task 1).

**Ask.** A `Record`-style overload of `WriteRows` / `CopyRowsFrom` (caller-owned command buffer, persistent or caller-supplied
staging), or a multi-layer variant, so that a whole chunk (all layers, K and V, plus the shift) is one submit. With that, host
assembly would be bound by the memcpy into staging rather than by 2 × 36 fenced submits per chunk.

## 3. No public device identity on `VulkanKvCache`

**Observed.** `VulkanChunkBackend.CheckCacheSupported` cannot verify that a `VulkanKvCache` lives on the backend's `VulkanDevice`:
the cache keeps its device in a private field (`_device`) and exposes no accessor. A resident chunk entry whose cache comes from
another device is only refused by `CopyRowsFrom` ("Caches must share one VulkanDevice", `VulkanKvCache.cs:745`) when the
assembler reaches that chunk. The earlier chunks have been copied by then. Since the Task 3 fix round, the assembler rolls the
destination back to its start length on any failure, so the cache is not left half-assembled, but the check still happens late.

**Ask.** A public `VulkanDevice Device { get; }` (or `bool IsOnDevice(VulkanDevice)`) on `VulkanKvCache`, so a caller can refuse a
foreign cache before writing anything.

## 4. `SubmitContext.Begin()` silently clears the device-wide hazard tracker

**Observed.** `VulkanDevice.SubmitContext.Begin()` sets `_device.ActiveHazards = null`. A caller that records its own submit (the
chunk backend's one-submit RoPE shift, or the old per-layer `RopeShiftKvKernel.Shift`) while a model forward on the same device is
being recorded would disarm that forward's hazard tracking. The tracker is internal, so ChunkReuse cannot detect this. Today it is
safe by architecture: forwards, row IO and shifts are all synchronous on one thread. The contract is documented in the
`VulkanChunkBackend.ShiftKeys` remarks.

**Ask.** Have `Begin()` throw (or assert in debug builds) when `ActiveHazards != null`, that is, when another recording is open on the
device.
