# chunkcache demo (Phase S Task 7, Step 5): the CLI on the dotLLM solution itself with Qwen3-4B-Instruct-2507 Q4_K_M, CPU.
# A full encode is infeasible on CPU and on this disk (~8 M tokens x 288 KiB/token), so the build indexes the whole solution
# (tokenizer only) and encodes a budgeted symbol neighbourhood; the dry run reports the full-tree cost.
#
#   pwsh run.ps1 -Exe <chunkcache.exe> -Solution <dotLLM.slnx> -Store <dir> [-Threads 8] [-Budget 24000]
param(
    [Parameter(Mandatory)] [string] $Exe,
    [Parameter(Mandatory)] [string] $Solution,
    [Parameter(Mandatory)] [string] $Store,
    [string] $Model = "$env:USERPROFILE\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots\ae44f08e1392f39c0e474af10c3ff8355c8b6688\Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    [int] $Threads = 8,
    [int] $Budget = 24000,
    [string] $Symbol = "ChunkIndex.Update",
    [int] $ContextBudget = 4096
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$logs = Join-Path $here 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null

function Step([string] $name, [string[]] $cliArgs) {
    $log = Join-Path $logs "$name.log"
    $json = Join-Path $logs "$name.json"
    "== $name : chunkcache $($cliArgs -join ' ')" | Tee-Object -FilePath $log
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $Exe @cliArgs --json 2>> $log | Set-Content -Encoding utf8 $json
    $code = $LASTEXITCODE
    "exit $code in $([math]::Round($sw.Elapsed.TotalSeconds, 1)) s" | Tee-Object -FilePath $log -Append
    if ($code -ne 0) { throw "$name failed with exit $code (see $log)" }
}

$common = @('--model', $Model, '--threads', "$Threads")
"provenance: solution $Solution; dotLLM commit $(git -C (Split-Path $Solution) rev-parse HEAD) dirty=$((git -C (Split-Path $Solution) status --porcelain | Measure-Object).Count); model $Model; threads $Threads; $(Get-Date -Format o)" |
    Tee-Object -FilePath (Join-Path $logs 'provenance.txt')

# 1. What a full encode would cost (nothing written).
Step '1-dry-run-full' (@('build', '--store', (Join-Path $Store 'dry'), '--solution', $Solution, '--configuration', 'Release', '--dry-run') + $common)
# 2. Index the whole solution (symbol-512) and encode the budgeted neighbourhood of $Symbol (2 hops).
Step '2-build-symbol' (@('build', '--store', $Store, '--solution', $Solution, '--configuration', 'Release', '--symbol', $Symbol, '--hops', '2', '--budget', "$Budget") + $common)
# 3. Rerun: all hits, nothing encoded.
Step '3-build-symbol-rerun' (@('build', '--store', $Store, '--solution', $Solution, '--configuration', 'Release', '--symbol', $Symbol, '--hops', '2', '--budget', "$Budget") + $common)
# 4. Fixed-512 index, encoding only the compare context.
Step '4-build-fixed' (@('build', '--store', $Store, '--solution', $Solution, '--configuration', 'Release', '--chunker', 'fixed', '--symbol', $Symbol, '--hops', '1', '--budget', "$ContextBudget", '--exclude', 'tools/DotLLM.ChunkCache/BuildCommand.cs') + $common)
# 5. Status (store only) and a selection.
Step '5-status' (@('status', '--store', $Store, '--no-scan') + $common)
Step '6-select' (@('select', '--store', $Store, '--symbol', $Symbol, '--hops', '1', '--budget', "$ContextBudget", '--exclude', 'tools/DotLLM.ChunkCache/BuildCommand.cs') + $common)
# 6. Compare: the context is the 1-hop neighbourhood of $Symbol under $ContextBudget tokens, without the query's own file; the
#    query is the code before BuildCommand's call to index.Update, the expected continuation is that call.
$task = Join-Path $logs 'task.json'
@{
    name = 'buildcommand-update-call'
    select = @{ symbol = $Symbol; hops = 1; budget = $ContextBudget; exclude = @('tools/DotLLM.ChunkCache/BuildCommand.cs') }
    query_from = @{ path = 'tools/DotLLM.ChunkCache/BuildCommand.cs'; start_line = 155; end_line = 166 }
    continuation = "        IndexDiff diff = index.Update(tree.Files, chunker);`n"
    continuation_tokens = 16
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $task
Step '7-compare' (@('compare', '--task', $task, '--store', $Store, '--chunkers', 'symbol', '--chunkers', 'fixed', '--selectors', 'chunkstarts', '--selectors', 'queryrelevance', '--selectors', 'hybrid', '--budgets', '5', '--budgets', '10', '--budgets', '20') + $common)
# (The reported run, at dotLLM 94ed8630, used the earlier comma form `--chunkers symbol,fixed ...`; since fb351745 list options
#  repeat and a comma in a value is a usage error.)
# (with --json the compare table is printed to stderr, i.e. into logs/7-compare.log)
"store size after the run:" | Tee-Object -FilePath (Join-Path $logs 'store-size.txt')
(Get-ChildItem -Recurse -File $Store | Measure-Object -Property Length -Sum).Sum | Tee-Object -FilePath (Join-Path $logs 'store-size.txt') -Append
