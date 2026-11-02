# Phase S Task 5: SolutionScanner on the dotLLM solution itself (tokenizer only, CPU, no weights run).
# Restores the solution first (the scanner reads restored projects), builds ChunkKvLab, runs scan-info with both chunkers.
# Usage: pwsh ./run.ps1 [-Worktree <dotLLM worktree>]
param([string]$Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-scan')
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$model = (Get-ChildItem "$env:USERPROFILE\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots" -Recurse -Filter '*Q4_K_M.gguf' | Select-Object -First 1).FullName
$sln = Join-Path $Worktree 'dotLLM.slnx'
dotnet restore $sln --nologo -v q | Out-Null
dotnet build (Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj') -c Release --nologo -v q | Out-Null
$lab = Join-Path $Worktree 'benchmarks\ChunkKvLab\bin\Release\net10.0\ChunkKvLab.exe'
foreach ($chunker in 'symbol', 'fixed') {
    $log = Join-Path $here "dotllm-$chunker.log"
    $dirty = (git -C $Worktree status --porcelain | Measure-Object -Line).Lines
    @(
        '# provenance'
        "utc: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))"
        "dotLLM: $(git -C $Worktree rev-parse HEAD) dirty=$dirty (scanned solution = this worktree)"
        "sdk: $(dotnet --version)"
        "model (tokenizer only): $model"
        "command: scan-info --solution $sln --chunker $chunker --chunk 512"
        ''
    ) | Set-Content $log
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $lab scan-info --model $model --solution $sln --chunker $chunker --chunk 512 *>> $log
    "exit $LASTEXITCODE; wall $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s" | Add-Content $log
    "done $chunker"
}
