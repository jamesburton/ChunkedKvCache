# Strix Halo usable GPU memory per process: re-measurement (2026-11-03)

Box: Radeon 8060S, 127.1 GiB visible RAM, 512 MB dedicated VRAM / dynamic split, Vulkan driver 26.10.1 (LLPC), Adrenalin INF 32.0.32015.7029 (2026-10-18), Windows 11 26200.
Tool: `dotLLM` branch `research/vk-cap-remeasure` (commit 568c5dab), `tools/vk-alloc-probe` new `--mode submit`:
1 GiB chunks, a VkBuffer bound per chunk, after every N GiB one `vkQueueSubmit` of a `vkCmdFillBuffer` (1 GiB per fill) over ALL buffers so far, fence wait, abort if Available RAM < 4 GiB. One process per run (failure is sticky). GPU lock `gpu` held; no model-resident process present (ollama empty); Docker/WSL (about 15 GiB) were still resident, so Available RAM baseline was 84-88 GiB.

## Results

| Run (type) | Target GiB | Max GiB submitted OK | First failure | Min Available RAM |
|---|---|---|---|---|
| heap 1, strict DEVICE_LOCAL (type 0) | 64 | 64 | none | 21 GiB |
| heap 1 (type 0) | 80 | 68 | alloc #69 OUT_OF_DEVICE_MEMORY (heap size 69,632 MiB; same as 2026-10-07) | 18 GiB |
| heap 0, HOST_VISIBLE (type 1) | 64 | 64 | none | 21 GiB |
| heap 0 (type 1) | 80 | 80 | none | 6.7 GiB |
| heap 0 (type 1), submit every 1 GiB | 82 / 83 | 82 / 83 | none | 4.8 / 5.1 GiB |
| heap 0 (type 1), submit every 1 GiB | 84 (x2), 85 | **83** | **submit at 84 GiB: VK_ERROR_OUT_OF_DEVICE_MEMORY** (deterministic, allocation itself succeeded) | 6.2 GiB |
| heap 0 + heap 1 alternating (types 0+1) | 80 | 80 | none | 10 GiB |
| heap 0 + heap 1 (types 0+1), every 1 GiB | 85 | **83** | **submit at 84 GiB: OUT_OF_DEVICE_MEMORY** | n/a |

Targets 90/100/110/120 were not run: the wall is at 84 GiB and failure is sticky, so there is nothing above it to learn.

Observations
- The wall is a per-process residency limit, independent of heap: heap 0, heap 1 and mixed all pass 83 GiB and fail at 84 GiB (0.653 x RAM ok, 0.661 x RAM fail). Heap 1 alone is limited earlier by its 68.15 GiB heap size.
- It is not RAM exhaustion: the failure came with 6-7 GiB Available RAM, and the same wall appears at the same GiB with different Available figures.
- GPU allocations are counted in the process working set 1:1 (WS = GiB allocated), so Available RAM falls 1:1. No pagefile growth or instability was seen (pagefile usage 6 GiB, unchanged class); the 4 GiB abort never fired.
- Fill submits stayed short (about 1 s for 83 GiB).

## Rerun with Docker Desktop and WSL stopped (James-approved, same day)

Freed about 6-20 GiB of host RAM (Available 83 -> 102.6 GiB on the first attempt; 97.8 -> 104.2 GiB on the second). Other agents' CPU model loads (dotnet 25-31 GiB, llama-completion 70 GiB) repeatedly starved the box mid-run; those attempts hit my 4 GiB Available-RAM abort at 58-78 GiB and are void (heap 0 at 83 GiB passed once with 18.6 GiB Available; the mixed and 59-78 GiB runs aborted on RAM, not on the wall).

| Run (heap 0, type 1, submit every 1 GiB, Docker/WSL down) | Result | Available RAM at failure |
|---|---|---|
| target 84, twice | **first failure at 82 GiB, last good 81 GiB** (VK_ERROR_OUT_OF_DEVICE_MEMORY at submit), identical both times | 21.6 and 20.6 GiB |
| 86 / 88 / 90 / 95 / 100, mixed heap0+heap1 | not run (stop at first failure; mixed attempt aborted on another agent's RAM use) | n/a |

Result: freeing RAM did NOT lift the wall. With 21 GiB Available it failed at 82 GiB, one to two GiB BELOW the 83 OK / 84 fail seen with Docker/WSL running. So the limit is an OS/driver per-process residency limit of about 0.64-0.66 x RAM that does not depend on free RAM; it wanders by a couple of GiB between runs/boots (81-83 GiB OK, measured 80.5 on 2026-10-10).

## Conclusion: cap UNCHANGED (OS-level, ~81-83 GiB OK, 82-84 GiB fails; independent of free RAM)

Not lifted: no process on this driver keeps more than ~83 GiB of GPU memory resident. Recommended `DOTLLM_VK_UMA_USABLE_FRACTION` default: **keep 0.64** (81.4 GiB on 127.15 GiB; the lowest OK point seen is 81 GiB, so do NOT raise it to 0.65). Code change is only documentation: update the remarks in `src/DotLLM.Vulkan/VulkanMemoryCapacity.cs` `UmaUsableFraction` (measured 2026-11-03: 81-83 GiB OK, 82-84 fail, independent of free RAM) and the "0.64" comment in `VulkanQwen4ExpTransformerModel.Mtp.cs:376`. Caveat: one box, one driver, 127.15 GiB visible; the limit probably scales with RAM, and it moved by a few GiB between 2026-10-10 and today (original note said it varies with page-cache pressure), so keep a margin.

Effect on current targets
- Qwen3.8-Flash-Next UD-Q4_K_XL trunk 79.2 GiB + 2.0-2.6 GiB MTP head = 81.2-81.8 GiB: is at or past the realistic 81-83 GiB wall (about 0-1.5 GiB spare, run-to-run variable); keep (needs `DOTLLM_VK_ALLOW_OVERCOMMIT=1` while the fraction is 0.64; the overcommit override is a gamble: a 82 GiB set failed in one run). The long-context KV (16K needs +0.9 GiB) is still tight.
- GLM-5.3-Flash: smallest quant (UD-IQ1_S 93 GB / 86.7 GiB) exceeds the ~81-83 GiB wall by 4-6 GiB, so it still needs host-resident experts or expert tiering. The 86 GB bar is not cleared.

## Other runtimes (item 6)

Nothing indicates a model above 86 GB ran through a GPU path here recently. Ollama logs end Aug-Sep 2026 (before the dynamic split); largest Ollama blob 25 GB; gguf-cache largest file 5.9 GB; largest HF-cache blobs 49.8 and 43.8 GB (2026-10-08); LM Studio holds 6.7 GB; `ollama ps` empty. HF cache does hold unsloth/Qwen3.8-Flash-Next-GGUF (91 GiB, all quants) and ISTA (54 GiB). If James saw >86 GB running it was via host-resident/mmap memory (CPU or partial offload), not via this limit being exceeded by device allocations.

## Already handled in dotLLM?

Reviewed `docs/MOE_OFFLOAD.md`, `docs/EXPERT_TIERING.md`, `docs/GPU.md`, `git log --all`, `LLMs.md`, `STRIX_HALO.md`.
- No cap bypass exists. `VulkanMemoryCapacity.UsableCapacityBytes` (fraction 0.64) gates residency; `DOTLLM_VK_ALLOW_OVERCOMMIT=1` only relaxes the guard.
- Over 82 GiB runs found:
  - Qwen3.8-Flash-Next UD-Q4_K_XL (111 GB, 106 GiB mmap): CPU oracle, dotLLM and CPU-only llama.cpp, about 1-1.5 tok/s (LLMs.md, 2026-10-09, #862/#871). Not GPU.
  - Same model on Vulkan: `DOTLLM_VK_EXPERT_SLOTS` expert tiering (docs/EXPERT_TIERING.md, #939): routed experts stream from SSD into per-layer device slots; 64/128/256 slots = 15.1/24.1/42.0 GiB device, 1.69/3.38/5.06 tok/s (resident 17.9 tok/s at 77.9 GiB). Device stays below the cap; prefill token by token.
  - Resident Vulkan runs of the 111 GB file keep 69.3 GiB on heap 1 plus the rest, about 79 GiB total (LLMs.md); MTP at 81-82 GiB needed overcommit (#900/#902).
  - CUDA MoE expert offload (#1070/#1187, MOE_OFFLOAD.md): Flint 26 GB on a 12 GB RTX 3060 and Nemotron-H Bolt; host store plus VRAM expert cache. Not iGPU, not >82 GiB models.
  - MiMo-V2.6-Flash BPW2.0 (about 77 GB) CPU only.
- STRIX_HALO.md / LLMs.md record no GPU run above 82 GiB. Line 270 of LLMs.md cites other-runtime Q2 figures from kyuz0/ds4 (Linux ROCm, from PRs, not run here).
- Conclusion: models above about 83 GiB currently run on this box only on CPU or via host-resident experts / SSD tiering. A real fix is a Vulkan layer/expert offload with host-visible memory outside the process residency limit, which is unproven and which the cap above suggests will also be limited by the same WDDM per-process budget.
