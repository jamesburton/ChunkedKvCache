#!/usr/bin/env bash
# Phase G Task 4 review fix round: mutants M17/M18 (git-archive copy) and one GPU-profiled control-arm run at 2K and at 16K
# (DOTLLM_VULKAN_PREFILL_PROFILE=gpu), under the dotLLM GPU lock (FIFO), after a >= 30 GB free-RAM check. Git bash only.
set -u
WT=/c/Development/dotLLM/.claude/worktrees/chunk-vulkan
EXP=/c/Development/ChunkedkvCache/experiments/G2-recompute-speed
LOCK=$WT/scripts/gpu-lock.sh
SNAP='C:\Users\james\AppData\Local\Temp\claude\C--Development-ChunkedkvCache\e3a311cd-21c5-4c45-8a8a-705944ca30fb\scratchpad'
MODEL='C:\Users\james\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots\ae44f08e1392f39c0e474af10c3ff8355c8b6688\Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
KEPT='C:\Development\ChunkedkvCache\experiments\corpus'
OUT='C:\Development\ChunkedkvCache\experiments\G2-recompute-speed'
NAMES=afclaude,docagent,codesharp
DIRS="$SNAP\\t8-corpus-AFClaude-b3f29c30-20261101111141,$SNAP\\t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016,$SNAP\\t8-corpus-codesharp-8e2adbd8-20261101111016"
HASHES=2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938,5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7,bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb

echo "# fix round GPU job, $(date -u), dotLLM $(git -C $WT rev-parse --short HEAD), dirty $(git -C $WT status --porcelain | wc -l)"
bash $LOCK acquire chunk-vulkan-t4 "ChunkedkvCache G2 review fix round: 2 mutants + profiled 2K/16K control (~20 min)" 3600 || { echo "lock not acquired"; exit 1; }
( while true; do sleep 600; bash $LOCK refresh chunk-vulkan-t4 >/dev/null; done ) & REFRESH=$!
trap 'kill $REFRESH 2>/dev/null; bash $LOCK release chunk-vulkan-t4' EXIT
while true; do
  free=$(powershell.exe -NoProfile -Command "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB)" | tr -d '\r')
  [ "$free" -ge 30 ] && break
  echo "$(date -u) free RAM ${free} GB < 30; waiting"; sleep 60
done
echo "free RAM ${free} GB"

# 1. Mutants M17, M18 in a git-archive copy of HEAD.
S=/c/Users/james/AppData/Local/Temp/claude/C--Development-ChunkedkvCache/e3a311cd-21c5-4c45-8a8a-705944ca30fb/scratchpad/mut4c
rm -rf $S && mkdir -p $S && git -C $WT archive HEAD | tar -x -C $S
( cd $S && dotnet build tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release -v q -nologo 2>&1 | grep -E " error |Elapsed" | head -3
  echo "BASE:"; dotnet test tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release --no-build --filter "FullyQualifiedName~ChunkReuse" 2>&1 | grep -E "Passed!|Failed!"
  python -I $EXP/logs/mutate4.py $S M17-guard-only-catches-zero M18-descending-batches ) 2>&1 | tee $EXP/logs/mutants-t4-round3.log

# 2. Profiled control-arm runs (control only: --selectors =; full prefill once; repeats 1; no eval).
cd $WT
run_profile() { # label context mode contexts budgets maxrows
  local label=$1
  rm -f "$EXP/logs/profile-$label.txt"
  DOTLLM_VULKAN_PREFILL_PROFILE=gpu DOTLLM_VULKAN_PREFILL_PROFILE_OUT="$OUT\\logs\\profile-$label.txt" \
    dotnet run -c Release --no-build --project benchmarks/ChunkKvLab/ChunkKvLab.csproj -- recompute --model "$MODEL" --names $NAMES \
    --corpus-dirs "$DIRS" --hashes $HASHES --contexts $4 --kept-dir "$KEPT" --mode $3 --context $2 --budgets $5 --max-rows $6 \
    --selectors = --repeats 1 --eval 0 --full-blocks 512 --label $label --out-dir "$OUT" > $EXP/logs/recompute-$label.log 2>&1
  echo "$label exit $?"
}
dotnet build benchmarks/ChunkKvLab/ChunkKvLab.csproj -c Release -v q -nologo 2>&1 | grep -E " error " | head -3
run_profile 2k-profile 2048 kept 1,0,0 10 128
run_profile 16k-profile 16384 unfiltered 0,0,1 5 64
echo "done $(date -u)"
