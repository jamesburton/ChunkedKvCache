# E4c: the E4 fixed-chunk arms with TEXT-FIRST fixed chunks (TextFirstFixedChunker, fixed-text-512: the file text is cut at
# the last line end that fits 512 tokens, else at a character boundary, and each piece is tokenised alone), on E4's random
# contexts (same kept Task 8 call sites, same --contexts per cell, same seed- and chunker-independent context order), dotLLM
# CPU, Qwen3-4B-Instruct-2507 Q4_K_M, 2K contexts. One job = one corpus x seed. Jobs run in parallel (-Parallel) with
# -Threads each (8 threads in total on a shared box); every log starts with a provenance block written when the job starts.
# Resumable: a job whose CSV exists is skipped; `ChunkKvLab e4` resumes its own <out>.partial by whole contexts (the time cap
# counts the minutes of earlier runs), and a rerun appends a new provenance block to the log.
# Usage:
#   ./run.ps1 -Snapshots <dir holding the t8-corpus-* snapshots> -Jobs <jobs.csv> [-OutDir <dir>] [-Parallel 2] [-Threads 4]
#   jobs.csv columns: name,chunker,seed,mode,contexts,maxminutes,arms,budgets,lightarms,lightbudgets
#   then: uv run summarize.py <OutDir>
param(
    [Parameter(Mandatory = $true)] [string] $Snapshots,
    [Parameter(Mandatory = $true)] [string] $Jobs,
    [string] $OutDir = (Join-Path $PSScriptRoot 'raw'),
    [int] $Parallel = 2,
    [int] $Threads = 4,
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse',
    [switch] $NoBuild
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'   # read-only git: never refresh another checkout's index
$corpusDir = Join-Path (Split-Path $here -Parent) 'corpus'
$logDir = Join-Path $here 'logs'
$queueLog = Join-Path $logDir 'queue.log'

# name -> snapshot dir, source repo, commit, fixed-text-512 chunk-id hash (printed by `ChunkKvLab roundtrip`; roundtrip.md)
$corpora = @{
    'afclaude'  = @('t8-corpus-AFClaude-b3f29c30-20261101111141', 'C:\Development\AFClaude', 'b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c',
        '7f78203a68cfad98bccb02da3c5709b25bd3a93d0cfd88dbda4c0cb0efb2e423')
    'docagent'  = @('t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016', 'C:\Development\CSharpDocAgentFrameworkMCP', '6683823880bc2a7d62708907c725d9eaedf3a016',
        'bb49fec66b3a0743b110b6476ddb5e8352df5f5305856b71431e26da6b164d91')
    'codesharp' = @('t8-corpus-codesharp-8e2adbd8-20261101111016', 'C:\Development\codesharp', '8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2',
        'e2c32d7d13f23bce78168619a3360d7e02e5e18ae46efb57a13b927073fee30a')
}

$repo = 'bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF'
$hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots'
$modelFile = Get-ChildItem -Path $hub -Recurse -Filter 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf' | Select-Object -First 1
if (-not $modelFile) { throw "Qwen3-4B-Instruct-2507 Q4_K_M not found under $hub (hf download $repo --include '*Q4_K_M*')" }
$model = $modelFile.FullName

$project = Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj'
if (-not $NoBuild) {
    dotnet build $project -c Release -m:4 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'build failed' }
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
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
    $snap, $src, $commit, $hash = $corpora[$j.name]
    $stem = "$($j.name)-$($j.chunker)-s$($j.seed)-$($j.mode)"
    $outCsv = Join-Path $OutDir "$stem.csv"
    if (Test-Path $outCsv) {
        $line = ("[{0:F1} min] {1:u} skip {2} (complete)" -f $all.Elapsed.TotalMinutes, [DateTime]::UtcNow, $stem)
        Write-Output $line
        Add-Content -Path $queueLog -Value $line
        continue
    }
    $labArgs = @('e4', '--model', $model, '--corpus', (Join-Path $Snapshots $snap), '--name', $j.name, '--chunker', $j.chunker,
        '--chunk', 512, '--seed', $j.seed, '--count', 100, '--context', 2048, '--mode', $j.mode, '--contexts', $j.contexts,
        '--max-minutes', $j.maxminutes, '--threads', $Threads, '--expect-hash', $hash, '--out', $outCsv,
        '--kept', (Join-Path $corpusDir "$($j.name).validation.csv"), '--plans-jsonl', (Join-Path $corpusDir "$($j.name).plans.jsonl"))
    if ($j.arms) { $labArgs += @('--arms', ($j.arms -replace ';', ',')) }
    if ($j.budgets) { $labArgs += @('--budgets', ($j.budgets -replace ';', ',')) }
    if ($j.lightarms) { $labArgs += @('--light-arms', ($j.lightarms -replace ';', ',')) }
    if ($j.lightbudgets) { $labArgs += @('--light-budgets', ($j.lightbudgets -replace ';', ',')) }
    while (@($running | Where-Object { -not $_.HasExited }).Count -ge $Parallel) { Start-Sleep -Seconds 5 }
    $logPath = Join-Path $logDir "$stem.log"
    $resumed = Test-Path "$outCsv.partial"
    $wtDirty = @(git -C $Worktree status --porcelain)
    $srcDirty = @(git -C $src status --porcelain)
    @(
        $(if ($resumed) { "# provenance (resumed run: $outCsv.partial exists)" } else { "# provenance" })
        "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
        "command: ChunkKvLab $($labArgs -join ' ')"
        "hardware: $($cpu.Name.Trim()) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T), RAM $ramGb GB; $env:COMPUTERNAME; CPU only (deviceId -1); $Parallel jobs in parallel x $Threads threads"
        "os: $($os.Caption) $($os.Version); last boot $($os.LastBootUpTime.ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')) UTC"
        "dotnet sdk: $sdk"
        "dotLLM worktree: $Worktree @ $wtHead (branch $wtBranch); dirty files: $($wtDirty.Count)"
        "corpus: $snap = git archive $commit src of $src; source repo HEAD $(git -C $src rev-parse HEAD), dirty files now: $($srcDirty.Count); expected chunk-id sha256 ($($j.chunker)-512) $hash"
        "model: $repo @ $($modelFile.Directory.Name) / $($modelFile.Name) ($($modelFile.Length) bytes)"
        "# end provenance"
    ) | Add-Content -Path $logPath -Encoding utf8
    if ($wtDirty.Count -gt 0) { Write-Warning "dotLLM worktree has $($wtDirty.Count) uncommitted changes: $stem is not reproducible from the commit alone" }
    $argLine = ($labArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { "$_" } }) -join ' '
    $cmd = "dotnet run -c Release --no-build --project `"$project`" -- $argLine >> `"$logPath`" 2>&1"
    $line = ("[{0:F1} min] {1:u} {2} {3}" -f $all.Elapsed.TotalMinutes, [DateTime]::UtcNow, $(if ($resumed) { 'resume' } else { 'start' }), $stem)
    Write-Output $line
    Add-Content -Path $queueLog -Value $line
    $running += Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd -NoNewWindow -PassThru
}
$running | ForEach-Object { $_.WaitForExit() }
$line = ("all jobs finished in {0:F1} min ({1:u})" -f $all.Elapsed.TotalMinutes, [DateTime]::UtcNow)
Write-Output $line
Add-Content -Path $queueLog -Value $line
