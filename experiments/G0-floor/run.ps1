# Phase G Task 2 / G0: numerical floor of the dotLLM Vulkan path (CPU vs Vulkan, Vulkan row-count batching, Vulkan rerun) on
# Qwen3-4B-Instruct-2507 Q4_K_M, E4 contexts. One `ChunkKvLab floor` process per size; each loads the model on the CPU and on
# Vulkan and writes floor-<label>.csv, contexts-<label>.csv, tasks-<label>.csv, timing-<label>.csv (renamed from *.partial only
# when every context finished). The dotLLM GPU lock is held per size and refreshed every 10 minutes.
# Usage:
#   ./run.ps1 -Snapshots <dir holding the t8-corpus-* snapshots> [-OutDir <dir>] [-Sizes 2k,8k] [-Smoke]
#   then: uv run summarize.py <OutDir>
param(
    [Parameter(Mandatory = $true)] [string] $Snapshots,
    [string] $OutDir = $PSScriptRoot,
    [string[]] $Sizes = @('2k', '8k'),
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-vulkan',
    [string] $LockName = 'chunk-vulkan-t2',
    [switch] $Smoke,
    [switch] $NoBuild
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'
$corpusDir = Join-Path (Split-Path $here -Parent) 'corpus'
$gitBash = 'C:\Program Files\Git\bin\bash.exe'   # never WSL bash (scripts/gpu-lock.sh refuses it; the lock dir would differ)
$lock = Join-Path $Worktree 'scripts\gpu-lock.sh'

# name -> snapshot dir, source repo, commit, symbol-512 chunk-id hash (../corpus.md)
$corpora = [ordered]@{
    'afclaude'  = @('t8-corpus-AFClaude-b3f29c30-20261101111141', 'C:\Development\AFClaude', 'b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c',
        '2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938')
    'docagent'  = @('t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016', 'C:\Development\CSharpDocAgentFrameworkMCP', '6683823880bc2a7d62708907c725d9eaedf3a016',
        '5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7')
    'codesharp' = @('t8-corpus-codesharp-8e2adbd8-20261101111016', 'C:\Development\codesharp', '8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2',
        'bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb')
}
# label -> context tokens, mode, contexts per corpus (afclaude, docagent, codesharp), Vulkan block sizes compared with 512.
# 2K: the E4 symbol/seed-0 kept contexts (the first 6 per corpus are E4's own, same StableKey order) plus one more for two corpora.
# 8K: unfiltered generator plans (no 8K task validation exists); the largest Vulkan block is 2048 rows (an 8192-row single submit
# risks the Windows TDR, which resets the GPU for every process on the box, so it is not attempted).
$sizeSpec = @{
    '2k' = @{ context = 2048; mode = 'kept'; contexts = '7,7,6'; blocks = '2048,96,64,8,1' }
    '8k' = @{ context = 8192; mode = 'unfiltered'; contexts = '2,2,1'; blocks = '2048,96,64,8' }
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
$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -like '*Radeon*' } | Select-Object -First 1
$vk = (vulkaninfo --summary 2>$null | Select-String -Pattern 'deviceName|driverName|driverInfo|apiVersion' | Select-Object -First 4 |
    ForEach-Object { $_.Line.Trim() -replace '\s+=\s+', '=' }) -join '; '
$sdk = (dotnet --version)
$wtHead = (git -C $Worktree rev-parse HEAD)
$wtBranch = (git -C $Worktree rev-parse --abbrev-ref HEAD)

foreach ($label in $Sizes) {
    # One lock hold per size, so other GPU work can run between the sizes.
    & $gitBash $lock acquire $LockName "ChunkedkvCache G0 floor $label (Phase G Task 2): CPU vs Vulkan prefill floor, Qwen3-4B" 7200
    if ($LASTEXITCODE -ne 0) { throw "GPU lock not acquired" }
    try {
        $s = $sizeSpec[$label]
        $contexts = if ($Smoke) { '1,0,0' } else { $s.contexts }
        $stem = if ($Smoke) { "floor-$label-smoke" } else { "floor-$label" }
        $labArgs = @('floor', '--model', $model,
            '--names', ($corpora.Keys -join ','),
            '--corpus-dirs', (($corpora.Values | ForEach-Object { Join-Path $Snapshots $_[0] }) -join ','),
            '--hashes', (($corpora.Values | ForEach-Object { $_[3] }) -join ','),
            '--contexts', $contexts, '--kept-dir', $corpusDir, '--mode', $s.mode, '--context', $s.context,
            '--ref-block', 512, '--blocks', $s.blocks, '--label', $(if ($Smoke) { "$label-smoke" } else { $label }), '--out-dir', $OutDir)
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
            ($corpora.Keys | ForEach-Object { $c = $corpora[$_]; "corpus $($_): $($c[0]) = git archive $($c[2]) of $($c[1]); expected chunk-id sha256 (symbol-512) $($c[3])" })
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
