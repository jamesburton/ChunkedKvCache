# PR 14 body draft: ChunkReuse.Vulkan backend

> DRAFT, not pushed, not opened. Branch `pr/chunkreuse-vulkan` (local, worktree `C:\Development\dotLLM\.claude\worktrees\pr14`), head `6195609b`, off dev `f54e36c5` (= #1703 merged).
> Needs James's explicit go; route through dotllm-00.

## Title

ChunkReuse.Vulkan: Vulkan chunk backend (positioned row IO, device RoPE delta shift)

## Body

Refs #1542, #1531. Follows #1646 (`.CSharp`) and #1648 (index); independent of PR 13 and PR 15.

### Summary

A new project, `DotLLM.ChunkReuse.Vulkan` (`IsPackable=false`; references `DotLLM.ChunkReuse` and `DotLLM.Vulkan`), so the core library keeps no Vulkan dependency.
It holds one class and one record:

- **`VulkanChunkBackend : IChunkBackend`**: chunk rows move through `IPositionedHostKvCache` on a `VulkanKvCache` with F32 storage, and cached keys are re-rotated on the
  device with `RopeShiftKvKernel` (all RoPE layers recorded into one command buffer, one submit). Entries carry the `vulkan` backend tag, so CPU and Vulkan entries never mix
  (a store filled through one gives no hit to the other).
- **`ChunkModelFeatures`**: reads `rope_freqs.weight` and `attn_sinks.weight` from the GGUF tensor names.

Core changes: one `InternalsVisibleTo DotLLM.ChunkReuse.Vulkan` (the backend reads `CpuChunkBackend.RowCount`), the project in `dotLLM.slnx`, and a project reference from the unit tests.

### What it refuses (at construction or on first use, with a message naming the feature)

YaRN, MLA, per-attention-type or scaled RoPE (everything `RopeParameters.FromConfig` refuses), Llama-3-style frequency factors, attention sinks; caches that are not a
`VulkanKvCache` with positioned row IO, F16 caches (rows would be rounded), compact sliding-window caches (rows are addressed by absolute position).

### Safety / contract notes

- `ShiftKeys` is not re-entrant and not thread-safe: it records into the backend's own `SubmitContext`, whose `Begin()` clears the device-wide hazard tracker, so it must
  not run while a model forward on the same device is being recorded (documented on the method; the assembler calls it between completed forwards).
- The backend does not own the device; caches it creates live on it and the model that runs on them must be loaded on the same device. `CheckCacheSupported` cannot verify
  that (no device on `VulkanKvCache`); a foreign cache is refused by `CopyRowsFrom` and the assembler rolls the destination back.
- A refused argument throws before the submit, so no layer is left shifted while another is not.
- Vulkan chunks are in-memory only (no store format change).

### Tests (moved from the prep branch)

`BackendSeamTests` (CPU seam + `BackendSeamTestsGpu`), `VulkanAssemblyTests` (+ `VulkanAssemblyTestsGpu`), `StoredAssemblyGpuTests.cs` (class `StoredAssemblyTestsGpu`).
GPU tests are `Category=GPU` + `Collection("VulkanKernels")` and skip without a device. Added here: a compact sliding-window cache is refused (found missing by mutant V4).

### Verification

- Windows, non-GPU tests of the three files: 13 pass. GPU (`Category=GPU`, gpu lock held, AMD Radeon 8060S / Vulkan): 13 pass (12 seam/assembly + 1 stored-assembly), 0 skip.
- Linux Docker, CI filter (`Category!=GPU&Category!=Benchmark&FullyQualifiedName!~Vulkan`, non-root) on the ChunkReuse namespace: 610 tests, 608 pass / 2 skip / 0 fail
  (the project builds on Linux; the Vulkan-named classes are excluded by the CI filter as for every Vulkan test).
- Mutants V1-V16 on a fresh `git archive` copy (`pr14-mutants.py`, log `.superpowers/sdd/2026-11-01-phase-s/pr14-mutants.log`, run with the GPU tests, copy checked pristine): all 15 applicable
  killed (V5 was dropped: its edit could not be written as a one-line change). V4 (compact windows accepted) SURVIVED the moved tests; a test was added and V4 is now killed.
  Mutated: freq-factor / sink / F16 / compact checks, no-RoPE layer skip, foreign-RoPE check, shift delta sign, start offset, KV head count, NeoX/Norm variant, missing submit, backend tag,
  CopyRows offsets, cache storage, ReadRows start.

### Not in this PR

`SelectiveRecomputer` and the Vulkan recompute path (research, `VulkanRecomputeTests`), the CLI, the server apply path (I5 Part B B4).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
