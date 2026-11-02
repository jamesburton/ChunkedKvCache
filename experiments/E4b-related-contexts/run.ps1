# Phase S Task 1 / E4b: the E4 arms on RELATED-chunk contexts (RelatedContextBuilder: half of the distractors from files
# within two reference-graph hops of the calling files, the rest random), same kept Task 8 call sites, dotLLM CPU,
# Qwen3-4B-Instruct-2507 Q4_K_M, 2K contexts. One job = one corpus x chunker x seed x context kind (x shard). Jobs run in
# parallel (-Parallel) with -Threads each; every log starts with a provenance block written when the job starts.
# Usage:
#   ./run.ps1 -Snapshots <dir holding the t8-corpus-* snapshots> -Jobs <jobs.csv> [-OutDir <dir>] [-Parallel 2] [-Threads 16]
#   jobs.csv columns: name,chunker,seed,mode,kind,fraction,contexts,maxminutes,arms,budgets,lightarms,lightbudgets,shard
#   then: uv run summarize.py <OutDir>   (E4b has no plot script)
param(
    [Parameter(Mandatory = $true)] [string] $Snapshots,
    [Parameter(Mandatory = $true)] [string] $Jobs,
    [string] $OutDir = (Join-Path $PSScriptRoot 'raw'),
    [int] $Parallel = 2,
    [int] $Threads = 16,
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse',
    [switch] $NoBuild
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'   # read-only git: never refresh another checkout's index
$corpusDir = Join-Path (Split-Path $here -Parent) 'corpus'
$queueLog = Join-Path $here 'logs\queue.log'

# name -> snapshot dir, source repo, commit, symbol-512 hash, fixed-512 hash (../corpus.md)
$corpora = @{
    'afclaude'  = @('t8-corpus-AFClaude-b3f29c30-20261101111141', 'C:\Development\AFClaude', 'b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c',
        '2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938', 'b90ef5fa2bbaae8fafbc08c27d19d8259465898c412609e7c31e06076f69cbb6')
    'docagent'  = @('t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016', 'C:\Development\CSharpDocAgentFrameworkMCP', '6683823880bc2a7d62708907c725d9eaedf3a016',
        '5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7', '8d083a63d5c1db7514596aec9bdabf880695ded868a45459f6c8be21a354f2b4')
    'codesharp' = @('t8-corpus-codesharp-8e2adbd8-20261101111016', 'C:\Development\codesharp', '8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2',
        'bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb', 'cde11b22a9d64764f3043bf1d7be6035190465e8d4ec03a7c22e765faa19dceb')
}

$repo = 'bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF'
$hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots'
$modelFile = Get-ChildItem -Path $hub -Recurse -Filter 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf' | Select-Object -First 1
if (-not $modelFile) { throw "Qwen3-4B-Instruct-2507 Q4_K_M not found under $hub (hf download $repo --include '*Q4_K_M*')" }
$model = $modelFile.FullName

$project = Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj'
if (-not $NoBuild) {
    dotnet build $project -c Release | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'build failed' }
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
$logDir = Join-Path $here 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
$os = Get-CimInstance Win32_OperatingSystem
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$sdk = (dotnet --version)
$wtHead = (git -C $Worktree rev-parse HEAD)
$wtBranch = (git -C $Worktree rev-parse --abbrev-ref HEAD)

$queue = Import-Csv $Jobs
$running = @()
$all = [Diagnostics.Stopwatch]::StartNew()
foreach ($j in $queue) {
    $snap, $src, $commit, $hSym, $hFix = $corpora[$j.name]
    $hash = if ($j.chunker -eq 'symbol') { $hSym } else { $hFix }
    $stem = "$($j.name)-$($j.chunker)-s$($j.seed)-$($j.mode)-$($j.kind)" + $(if ($j.shard -and $j.shard -ne '0/1') { '-sh' + ($j.shard -replace '/', 'of') } else { '' })
    $labArgs = @('e4', '--model', $model, '--corpus', (Join-Path $Snapshots $snap), '--name', $j.name, '--chunker', $j.chunker,
        '--chunk', 512, '--seed', $j.seed, '--count', 100, '--context', 2048, '--mode', $j.mode, '--contexts', $j.contexts,
        '--max-minutes', $j.maxminutes, '--threads', $Threads, '--expect-hash', $hash, '--out', (Join-Path $OutDir "$stem.csv"),
        '--kept', (Join-Path $corpusDir "$($j.name).validation.csv"), '--plans-jsonl', (Join-Path $corpusDir "$($j.name).plans.jsonl"),
        '--context-kind', $j.kind, '--related-fraction', $j.fraction)
    if ($j.arms) { $labArgs += @('--arms', ($j.arms -replace ';', ',')) }
    if ($j.budgets) { $labArgs += @('--budgets', ($j.budgets -replace ';', ',')) }
    if ($j.lightarms) { $labArgs += @('--light-arms', ($j.lightarms -replace ';', ',')) }
    if ($j.lightbudgets) { $labArgs += @('--light-budgets', ($j.lightbudgets -replace ';', ',')) }
    if ($j.shard) { $labArgs += @('--shard', $j.shard) }
    while (@($running | Where-Object { -not $_.HasExited }).Count -ge $Parallel) { Start-Sleep -Seconds 5 }
    $logPath = Join-Path $logDir "$stem.log"
    $wtDirty = @(git -C $Worktree status --porcelain)
    $srcDirty = @(git -C $src status --porcelain)
    @(
        "# provenance"
        "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
        "command: ChunkKvLab $($labArgs -join ' ')"
        "hardware: $($cpu.Name.Trim()) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T), RAM $ramGb GB; $env:COMPUTERNAME; CPU only (deviceId -1); $Parallel jobs in parallel x $Threads threads"
        "os: $($os.Caption) $($os.Version)"
        "dotnet sdk: $sdk"
        "dotLLM worktree: $Worktree @ $wtHead (branch $wtBranch); dirty files: $($wtDirty.Count)"
        "corpus: $snap = git archive $commit src of $src; source repo HEAD $(git -C $src rev-parse HEAD), dirty files now: $($srcDirty.Count); expected chunk-id sha256 ($($j.chunker)-512) $hash"
        "model: $repo @ $($modelFile.Directory.Name) / $($modelFile.Name) ($($modelFile.Length) bytes)"
        "# end provenance"
    ) | Set-Content -Path $logPath -Encoding utf8
    if ($wtDirty.Count -gt 0) { Write-Warning "dotLLM worktree has $($wtDirty.Count) uncommitted changes: $stem is not reproducible from the commit alone" }
    $argLine = ($labArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { "$_" } }) -join ' '
    $cmd = "dotnet run -c Release --no-build --project `"$project`" -- $argLine >> `"$logPath`" 2>&1"
    $line = ("[{0:F1} min] {1:u} start {2}" -f $all.Elapsed.TotalMinutes, [DateTime]::UtcNow, $stem)
    Write-Output $line
    Add-Content -Path $queueLog -Value $line
    $running += Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd -NoNewWindow -PassThru
}
$running | ForEach-Object { $_.WaitForExit() }
$line = ("all jobs finished in {0:F1} min ({1:u})" -f $all.Elapsed.TotalMinutes, [DateTime]::UtcNow)
Write-Output $line
Add-Content -Path $queueLog -Value $line
