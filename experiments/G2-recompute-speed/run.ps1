# Phase G Task 4 / G2: single-pass selective recompute on the dotLLM Vulkan backend (Radeon 8060S iGPU), Qwen3-4B-Instruct-2507 Q4_K_M,
# on the E4 contexts (symbol chunker, seed 0; the G0 corpus snapshots). One `ChunkKvLab recompute` process per group; each writes
# timing-<label>.csv (and with eval: tasks-, kv-, kvpooled-), renamed from *.partial only when the run finished.
# Timing groups never request all-row logits (Vulkan's all-row limit is grow-only and would add the LM head to every short forward);
# eval groups (--eval 1, one repeat) measure quality and numerics and their timings are not used.
# The dotLLM GPU lock is held per group and refreshed every 10 minutes. While a group runs this script holds
# SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED) and the lab process holds power requests (KeepAwake.cs).
# Usage:
#   ./run.ps1 -Snapshots <dir holding the t8-corpus-* snapshots> [-Groups 2k-timing,8k-timing,2k-eval,8k-eval] [-Smoke]
#   then: uv run summarize.py
param(
    [Parameter(Mandatory = $true)] [string] $Snapshots,
    [string[]] $Groups = @('2k-timing', '2k-cap128', '2k-eval', '8k-timing', '8k-eval', '16k-point'),
    [string] $OutDir = $PSScriptRoot,
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-vulkan',
    [string] $LockName = 'chunk-vulkan-t4',
    [switch] $Smoke,
    [switch] $NoBuild
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'
$corpusDir = Join-Path (Split-Path $here -Parent) 'corpus'
$gitBash = 'C:\Program Files\Git\bin\bash.exe'   # never WSL bash (scripts/gpu-lock.sh refuses it; the lock dir would differ)
$lock = Join-Path $Worktree 'scripts\gpu-lock.sh'

Add-Type -Namespace G2Power -Name Native -MemberDefinition '[System.Runtime.InteropServices.DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$esContinuous = [uint32]2147483648   # ES_CONTINUOUS
$esSystemRequired = [uint32]3        # ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED

$corpora = [ordered]@{
    'afclaude'  = @('t8-corpus-AFClaude-b3f29c30-20261101111141', 'C:\Development\AFClaude', 'b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c',
        '2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938')
    'docagent'  = @('t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016', 'C:\Development\CSharpDocAgentFrameworkMCP', '6683823880bc2a7d62708907c725d9eaedf3a016',
        '5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7')
    'codesharp' = @('t8-corpus-codesharp-8e2adbd8-20261101111016', 'C:\Development\codesharp', '8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2',
        'bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb')
}
# maxRows caps one single-pass forward (one GPU submit; TdrDelay is 10 s on this box). The 2K smoke showed ~15-17 ms per recomputed row at 2K
# through the per-query-position attention (a 2045-row submit took 30 s and survived), so 8K/16K submits are capped (README).
$groupSpec = @{
    '2k-timing'  = @{ label = '2k';  context = 2048;  mode = 'kept';       contexts = '3,3,2'; maxRows = 0; extra = @('--repeats', 3, '--eval', 0) }
    '2k-cap128'  = @{ label = '2k-cap128'; context = 2048; mode = 'kept';  contexts = '1,1,0'; maxRows = 128; extra = @('--repeats', 3, '--eval', 0, '--budgets', 20) }
    '8k-probe'   = @{ label = '8k-probe'; context = 8192; mode = 'unfiltered'; contexts = '1,0,0'; maxRows = 256; extra = @('--repeats', 1, '--eval', 0, '--budgets', 5, '--selectors', 'chunk_starts', '--full-blocks', 512) }
    '8k-timing'  = @{ label = '8k';  context = 8192;  mode = 'unfiltered'; contexts = '1,1,0'; maxRows = 128; extra = @('--repeats', 3, '--eval', 0) }
    '16k-point'  = @{ label = '16k'; context = 16384; mode = 'unfiltered'; contexts = '1,0,0'; maxRows = 64; extra = @('--repeats', 1, '--eval', 0, '--budgets', 5, '--selectors', 'chunk_starts', '--full-blocks', 512) }
    '2k-eval'    = @{ label = '2k-eval'; context = 2048; mode = 'kept';    contexts = '7,7,6'; maxRows = 512; extra = @('--repeats', 1, '--eval', 1, '--cpu-contexts', 6, '--full-blocks', 512) }
    '8k-eval'    = @{ label = '8k-eval'; context = 8192; mode = 'unfiltered'; contexts = '1,1,0'; maxRows = 128; extra = @('--repeats', 1, '--eval', 1, '--full-blocks', 512) }
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

foreach ($group in $Groups) {
    $s = $groupSpec[$group]
    if (-not $s) { throw "unknown group $group" }
    & $gitBash $lock acquire $LockName "ChunkedkvCache G2 recompute $group (Phase G Task 4), Qwen3-4B" 7200
    if ($LASTEXITCODE -ne 0) { throw "GPU lock not acquired" }
    $null = [G2Power.Native]::SetThreadExecutionState($esContinuous -bor $esSystemRequired)
    try {
        $label = if ($Smoke) { "$($s.label)-smoke" } else { $s.label }
        $contexts = if ($Smoke) { '1,0,0' } else { $s.contexts }
        $labArgs = @('recompute', '--model', $model,
            '--names', ($corpora.Keys -join ','),
            '--corpus-dirs', (($corpora.Values | ForEach-Object { Join-Path $Snapshots $_[0] }) -join ','),
            '--hashes', (($corpora.Values | ForEach-Object { $_[3] }) -join ','),
            '--contexts', $contexts, '--kept-dir', $corpusDir, '--mode', $s.mode, '--context', $s.context,
            '--max-rows', $s.maxRows, '--label', $label, '--out-dir', $OutDir) + $s.extra
        $logPath = Join-Path $logDir "recompute-$label.log"
        $wtDirty = @(git -C $Worktree status --porcelain)
        $holder = (& $gitBash $lock status) -join ' '
        @(
            "# provenance"
            "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
            "group: $group"
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
        if ($wtDirty.Count -gt 0) { Write-Warning "dotLLM worktree has $($wtDirty.Count) uncommitted changes: $label is not reproducible from the commit alone" }
        $argLine = ($labArgs | ForEach-Object { if ("$_" -match '\s') { '"' + $_ + '"' } else { "$_" } }) -join ' '
        $cmd = "dotnet run -c Release --no-build --project `"$project`" -- $argLine >> `"$logPath`" 2>&1"
        $sw = [Diagnostics.Stopwatch]::StartNew()
        Write-Output "start $group ($label)"
        $proc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cmd -NoNewWindow -PassThru
        $null = $proc.Handle
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
        Write-Output ("{0}: exit {1} in {2:F1} min" -f $group, $proc.ExitCode, $sw.Elapsed.TotalMinutes)
        if ($proc.ExitCode -ne 0) { throw "$group failed (exit $($proc.ExitCode)); see $logPath" }
    }
    finally {
        $null = [G2Power.Native]::SetThreadExecutionState($esContinuous)
        & $gitBash $lock release $LockName | Out-Null
    }
}
