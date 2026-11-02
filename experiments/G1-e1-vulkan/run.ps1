# Phase G Task 3 / G1: E1 (full prefill vs naive chunk-KV concatenation vs exact prefix reuse) on the dotLLM Vulkan backend
# (Radeon 8060S iGPU), Qwen3-4B-Instruct-2507 Q4_K_M, on the pinned E1/E2 corpus (git archive 4a781829 src of dotLLM), with an
# in-process CPU cross-check of naive concatenation (--cross-check cpu). One `ChunkKvLab e1 --backend vulkan` process per size group;
# each writes results-<group>.csv (+ -details, -timing, -kv, -xcheck), renamed from *.partial only when the run finished.
# The dotLLM GPU lock is held per group and refreshed every 10 minutes.
# Usage:
#   ./run.ps1 -Corpus <dir holding git-archive 4a781829 src> [-Groups small,16k,32k] [-Seeds 3] [-Smoke]
#   then: uv run summarize.py
param(
    [Parameter(Mandatory = $true)] [string] $Corpus,
    [string[]] $Groups = @('small', '16k', '32k'),
    [int] $Seeds = 3,
    [string] $OutDir = $PSScriptRoot,
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-vulkan',
    [string] $LockName = 'chunk-vulkan-t3',
    [string] $CorpusCommit = '4a7818290766b69a3bae0999874154185c7fa587',
    [string] $ExpectHash = 'b02b1e6e44ebbf82169f29a42d7847d7ba69203fc52f9d07bef60335c90dc800',
    [switch] $Smoke,
    [switch] $NoBuild
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'
$gitBash = 'C:\Program Files\Git\bin\bash.exe'   # never WSL bash (scripts/gpu-lock.sh refuses it; the lock dir would differ)
$lock = Join-Path $Worktree 'scripts\gpu-lock.sh'
$groupSizes = @{ 'small' = '2048,4096,8192'; '16k' = '16384'; '32k' = '32768' }

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
$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -like '*Radeon*' } | Select-Object -First 1
$vk = (vulkaninfo --summary 2>$null | Select-String -Pattern 'deviceName|driverName|driverInfo|apiVersion' | Select-Object -First 4 |
    ForEach-Object { $_.Line.Trim() -replace '\s+=\s+', '=' }) -join '; '
$sdk = (dotnet --version)
$wtHead = (git -C $Worktree rev-parse HEAD)
$wtBranch = (git -C $Worktree rev-parse --abbrev-ref HEAD)

foreach ($group in $Groups) {
    & $gitBash $lock acquire $LockName "ChunkedkvCache G1 E1 on Vulkan $group (Phase G Task 3), Qwen3-4B" 7200
    if ($LASTEXITCODE -ne 0) { throw "GPU lock not acquired" }
    try {
        $sizes = if ($Smoke) { '2048' } else { $groupSizes[$group] }
        $seeds = if ($Smoke) { 1 } else { $Seeds }
        $stem = if ($Smoke) { "results-smoke" } else { "results-$group" }
        $labArgs = @('e1', '--backend', 'vulkan', '--cross-check', 'cpu', '--model', $model, '--corpus', $Corpus,
            '--expect-hash', $ExpectHash, '--sizes', $sizes, '--seeds', $seeds, '--out', (Join-Path $OutDir "$stem.csv"))
        $logPath = Join-Path $logDir "$stem.log"
        $wtDirty = @(git -C $Worktree status --porcelain)
        $holder = (& $gitBash $lock status) -join ' '
        @(
            "# provenance"
            "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
            "command: ChunkKvLab $($labArgs -join ' ')"
            "hardware: $($cpu.Name.Trim()) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T), RAM $ramGb GB; $env:COMPUTERNAME"
            "gpu: $($gpu.Name), Windows driver $($gpu.DriverVersion); vulkaninfo: $vk"
            "gpu lock: $holder"
            "os: $($os.Caption) $($os.Version)"
            "dotnet sdk: $sdk"
            "dotLLM worktree: $Worktree @ $wtHead (branch $wtBranch); dirty files: $($wtDirty.Count)"
            "corpus: $Corpus = git archive $CorpusCommit src of C:\Development\dotLLM (frozen snapshot); expected chunk-id sha256 $ExpectHash"
            "model: $repo @ $($modelFile.Directory.Name) / $($modelFile.Name) ($($modelFile.Length) bytes)"
            "# end provenance"
        ) | Set-Content -Path $logPath -Encoding utf8
        if ($wtDirty.Count -gt 0) { Write-Warning "dotLLM worktree has $($wtDirty.Count) uncommitted changes: $stem is not reproducible from the commit alone" }
        $argLine = ($labArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { "$_" } }) -join ' '
        $cmd = "dotnet run -c Release --no-build --project `"$project`" -- $argLine >> `"$logPath`" 2>&1"
        $sw = [Diagnostics.Stopwatch]::StartNew()
        Write-Output "start $stem"
        $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd -NoNewWindow -PassThru
        $null = $proc.Handle   # cache the handle so ExitCode is available after exit
        $lastRefresh = $sw.Elapsed.TotalMinutes
        while (-not $proc.HasExited) {
            Start-Sleep -Seconds 20
            if ($sw.Elapsed.TotalMinutes - $lastRefresh -ge 10) {
                & $gitBash $lock refresh $LockName | Out-Null
                $lastRefresh = $sw.Elapsed.TotalMinutes
            }
        }
        $proc.WaitForExit()
        "# exit code $($proc.ExitCode) after $([math]::Round($sw.Elapsed.TotalMinutes, 1)) min" | Add-Content -Path $logPath -Encoding utf8
        Write-Output ("{0}: exit {1} in {2:F1} min" -f $stem, $proc.ExitCode, $sw.Elapsed.TotalMinutes)
        if ($proc.ExitCode -ne 0) { throw "$stem failed (exit $($proc.ExitCode)); see $logPath" }
    }
    finally {
        & $gitBash $lock release $LockName | Out-Null
    }
}
