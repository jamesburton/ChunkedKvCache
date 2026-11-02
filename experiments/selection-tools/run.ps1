# Phase S Task 6: ContextSelector on the dotLLM solution itself (tokenizer only, CPU, no weights run).
# Scans the solution (Configuration=Release), chunks the authored files with symbol-512, builds the per-project reference
# graph and runs `ChunkKvLab select` for three requests. Each request is printed without and with the budget.
# Usage: pwsh ./run.ps1 [-Worktree <dotLLM worktree>]
param([string]$Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-cache')
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$model = (Get-ChildItem "$env:USERPROFILE\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots" -Recurse -Filter '*Q4_K_M.gguf' | Select-Object -First 1).FullName
$sln = Join-Path $Worktree 'dotLLM.slnx'
dotnet restore $sln --nologo -v q | Out-Null
dotnet build (Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj') -c Release --nologo -v q | Out-Null
$lab = Join-Path $Worktree 'benchmarks\ChunkKvLab\bin\Release\net10.0\ChunkKvLab.exe'
$runs = [ordered]@{
    'symbol-2hops-20k'         = @('--symbol', 'ChunkIndex.Update', '--hops', '2', '--budget', '20000')
    'symbol-2hops-20k-no-tests' = @('--symbol', 'ChunkIndex.Update', '--hops', '2', '--budget', '20000', '--exclude', 'tests/**,benchmarks/**')
    'symbol-2hops-20k-cap25'   = @('--symbol', 'ChunkIndex.Update', '--hops', '2', '--budget', '20000', '--max-per-hop', '25')
    # 69eb5772 = merge of the scanner fix round into feature/chunk-cache (pinned, so the example does not drift with HEAD).
    'paths-since-20k'          = @('--paths', 'src/DotLLM.ChunkReuse/Tooling/,src/DotLLM.ChunkReuse/Store/ChunkRef.cs', '--since', '69eb5772', '--budget', '20000')
    # dev has moved on since this branch forked: two-dot sweeps in dev's own changes, the merge base does not.
    'since-dev-two-dot'        = @('--since', 'dev', '--budget', '20000')
    'since-dev-merge-base'     = @('--since', 'dev', '--since-merge-base', '1', '--budget', '20000')
}
foreach ($name in $runs.Keys) {
    $log = Join-Path $here "$name.log"
    $dirty = (git -C $Worktree status --porcelain | Measure-Object -Line).Lines
    $args = @('select', '--model', $model, '--solution', $sln, '--configuration', 'Release', '--chunker', 'symbol', '--chunk', '512', '--show', '15') + $runs[$name]
    @(
        '# provenance'
        "utc: $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss'))"
        "dotLLM: $(git -C $Worktree rev-parse HEAD) dirty=$dirty (scanned solution = this worktree)"
        "dev: $(git -C $Worktree rev-parse dev); merge-base(dev, HEAD): $(git -C $Worktree merge-base dev HEAD)"
        "git: $(git --version)"
        "sdk: $(dotnet --version)"
        "model (tokenizer only): $model"
        "command: ChunkKvLab $($args[0]) $(($args[3..($args.Length - 1)]) -join ' ')"
        ''
    ) | Set-Content $log
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $lab @args *>> $log
    "exit $LASTEXITCODE; wall $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s" | Add-Content $log
    "done $name"
}
