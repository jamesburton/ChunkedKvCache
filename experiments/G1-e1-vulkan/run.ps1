# Phase G Task 3 / G1: E1 (full prefill vs naive chunk-KV concatenation vs exact prefix reuse) on the dotLLM Vulkan backend
# (Radeon 8060S iGPU), Qwen3-4B-Instruct-2507 Q4_K_M, on the pinned E1/E2 corpus (git archive 4a781829 src of dotLLM), with an
# in-process CPU cross-check of naive concatenation (--cross-check cpu). One `ChunkKvLab e1 --backend vulkan` process per size group;
# each writes results-<group>.csv (+ -details, -timing, -kv, -xcheck), renamed from *.partial only when the run finished.
# The dotLLM GPU lock is held per group and refreshed every 10 minutes. While a group runs, this script holds
# SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED), and the lab process holds
# PowerRequestExecutionRequired / SystemRequired / DisplayRequired (KeepAwake.cs; check with an elevated `powercfg /requests`).
# On this Modern Standby box an idle display-off starts standby and the process is suspended: ES_SYSTEM_REQUIRED alone did NOT
# prevent it (the S4 control run stalled 05:18-05:54 with it held). G1's first 32K run lost ~74 min this way, and the lock refresher
# froze with it (a standby longer than the lock's 90-min staleness would have let another agent take the GPU mid-run). The display
# stays on while a group runs. The lab logs a heartbeat every 5 min, so a stall shows as a gap.
# Group 'control' (2K/4K/8K) adds --cross-check cpu+full: CPU vs Vulkan on the full prefill of the same contexts (review S4).
# Usage:
#   ./run.ps1 -Corpus <dir holding git-archive 4a781829 src> [-Groups small,16k,32k|control] [-Seeds 3] [-Smoke]
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
$groupSizes = @{ 'small' = '2048,4096,8192'; '16k' = '16384'; '32k' = '32768'; 'control' = '2048,4096,8192' }

# Keep the system awake while this script runs (the waiting loop runs on this thread, so the request lasts the whole run).
Add-Type -Namespace G1Power -Name Native -MemberDefinition '[System.Runtime.InteropServices.DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$esContinuous = [uint32]2147483648   # ES_CONTINUOUS
$esSystemAndDisplayRequired = [uint32]3   # ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED (system-required alone does not stop Modern Standby)

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
        $crossCheck = if ($group -eq 'control') { 'cpu+full' } else { 'cpu' }
        $labArgs = @('e1', '--backend', 'vulkan', '--cross-check', $crossCheck, '--model', $model, '--corpus', $Corpus,
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
        $null = [G1Power.Native]::SetThreadExecutionState($esContinuous -bor $esSystemAndDisplayRequired)
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
        $null = [G1Power.Native]::SetThreadExecutionState($esContinuous)   # clear the system-required request
        & $gitBash $lock release $LockName | Out-Null
    }
}
