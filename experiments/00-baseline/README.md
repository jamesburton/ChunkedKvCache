# 00-baseline: dotLLM runs Qwen3-4B-Instruct-2507 on CPU and Vulkan

## Environment
- dotLLM: worktree `C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse`, branch `feature/chunk-kv-reuse`, base `dev` commit `4a781829` (unchanged, no edits)
- .NET SDK 10.0.401 (`global.json` pinned), Windows 11 Pro 10.0.26200, Release build
- GPU: AMD Radeon 8060S (gfx1151, Strix Halo), Vulkan apiVersion 1.4.359, driverVersion 2.0.416, AMD proprietary, driverInfo 26.10.1 (LLPC)
- Model: `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF`, file `Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, HF revision `ae44f08e1392f39c0e474af10c3ff8355c8b6688`, used in place from the HF hub cache (no copy):
  `~/.cache/huggingface/hub/models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF/snapshots/ae44f08e.../`

## Commands (from the dotLLM worktree)
```
dotnet build dotLLM.slnx -c Release                     # 0 errors, 1754 warnings (pre-existing analyzers)
dotnet test tests/DotLLM.Tests.Unit -c Release --no-build --filter "FullyQualifiedName~Engine"
M=<path to the Q4_K_M .gguf above>
dotnet run -c Release --no-build --project src/DotLLM.Cli -- run "$M" --device cpu    --prompt "The capital of France is" --max-tokens 64
dotnet run -c Release --no-build --project src/DotLLM.Cli -- run "$M" --device vulkan --prompt "The capital of France is" --max-tokens 64
```
Greedy (argmax) is the default sampler; there is no `--temperature` flag (`-t/--temp` defaults to 0).

## Tests
Engine filter: Passed 1075, Failed 0, Skipped 4 (of 1079). No pre-existing failures. Skips: MultiAdapterBatcherTests.ConcurrentMixedAdapter_Note, TurboQuantKvParityTests.TurboQuantKv_NextTokenParity_VsFullPrecision, HybridMidHistoryResumeProbe.Bonsai2_TrimmedToolResult_ResumesFromTheNearestStep, CudaRecurrentPrefixPersistenceTests.EngineDiskSpill_RestoresActualCudaStateWithExactColdLogits (attribute/hardware skips).

## Output (64 greedy tokens, identical on both devices)
> The capital of France is Paris. The capital of Germany is Berlin. The capital of Italy is Rome. The capital of Spain is Madrid. The capital of the United Kingdom is London. The capital of the United States is Washington, D.C. The capital of Canada is Ottawa. The capital of Australia is Canberra. The capital of Japan is Tokyo

| Device | Prefill (5 tok) | Decode (63 tok) | Load | Notes |
|---|---|---|---|---|
| cpu | 2177.8 ms | 5.10 tok/s | 0.87 s | |
| vulkan | 67.4 ms | 64.91 tok/s | 33.4 s (cold, shader/weights upload) | compute buffers 3861 MiB |

Both finish with `length | 5 prompt, 64 generated`, KV cache 19.4 MiB (69 slots). Full captured output: `scratch/run-cpu.txt`, `scratch/run-vulkan.txt`.
Text is byte-identical across CPU and Vulkan, so top tokens agree for all 64 steps. Single-run timings, not benchmarks.
