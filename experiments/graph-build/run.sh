#!/usr/bin/env bash
# Task 9: Roslyn reference-graph build time and edge statistics for the Task 8 corpora (tokenizer only, CPU, no weights run).
# Usage: ./run.sh <scratch dir holding the t8-corpus-* snapshots>   (see ../corpus.md for the snapshots and their hashes)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
snap="$1"
wt='C:/Development/dotLLM/.claude/worktrees/chunk-kv-reuse'
model="$(find ~/.cache/huggingface/hub/models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF/snapshots -name '*Q4_K_M.gguf' | head -1)"
dotnet build "$wt/benchmarks/ChunkKvLab/ChunkKvLab.csproj" -c Release > /dev/null
lab="$wt/benchmarks/ChunkKvLab/bin/Release/net10.0/ChunkKvLab.exe"
run() { # name dir chunker hash
  local log="$here/$1-$3.log"
  {
    echo "# provenance"
    echo "utc: $(date -u '+%Y-%m-%d %H:%M:%S')"
    echo "dotLLM: $(git -C "$wt" rev-parse HEAD) dirty=$(git -C "$wt" status --porcelain | wc -l)"
    echo "model (tokenizer only): $model"
    echo "command: graph-info --corpus $2 --chunker $3 --chunk 512 --repeat 3 --plans 100 --seed 0 --expect-hash $4"
    echo
    "$lab" graph-info --model "$model" --corpus "$snap/$2" --chunker "$3" --chunk 512 --repeat 3 --plans 100 --seed 0 --expect-hash "$4"
  } > "$log" 2>&1
  echo "done $1 $3"
}
run afclaude t8-corpus-AFClaude-b3f29c30-20261101111141 symbol 2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938
run afclaude t8-corpus-AFClaude-b3f29c30-20261101111141 fixed b90ef5fa2bbaae8fafbc08c27d19d8259465898c412609e7c31e06076f69cbb6
run docagent t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016 symbol 5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7
run docagent t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016 fixed 8d083a63d5c1db7514596aec9bdabf880695ded868a45459f6c8be21a354f2b4
run codesharp t8-corpus-codesharp-8e2adbd8-20261101111016 symbol bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb
run codesharp t8-corpus-codesharp-8e2adbd8-20261101111016 fixed cde11b22a9d64764f3043bf1d7be6035190465e8d4ec03a7c22e765faa19dceb
