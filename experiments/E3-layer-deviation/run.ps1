# Task 10 / E3: per-layer K/V deviation (full prefill vs assembled chunk KV) by token role, dotLLM CPU,
# Qwen3-4B-Instruct-2507 Q4_K_M. Contexts are the Task 8 cross-file plans (2K) of the three frozen corpora (../corpus.md),
# both chunkers, generator seeds 0-2: the first -Contexts plans of each (seeded) plan list, plus, for symbol/seed 0, every plan
# holding a task the Task 8 validation kept. Raw per-run CSVs go to -OutDir (large, not committed); summarize.py merges them
# into this folder. Every log starts with a provenance block.
# Usage:
#   ./run.ps1 -Snapshots <dir holding the t8-corpus-* snapshots> [-OutDir <dir>] [-Contexts 8] [-Seeds 0,1,2] [-Chunkers symbol,fixed]
#             [-Context 2048] [-MaxMinutes 14] [-Raw 1]
#   then: uv run summarize.py <OutDir>   and   uv run plot.py
param(
    [Parameter(Mandatory = $true)] [string] $Snapshots,
    [string] $OutDir = (Join-Path $PSScriptRoot 'raw'),
    [int] $Contexts = 8,
    [int[]] $Seeds = @(0, 1, 2),
    [string[]] $Chunkers = @('symbol', 'fixed'),
    [int] $Context = 2048,
    [double] $MaxMinutes = 14,
    [int] $Raw = 1,
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'   # read-only git: never refresh another checkout's index
$corpusDir = Join-Path (Split-Path $here -Parent) 'corpus'

# name, snapshot dir, source repo, commit, symbol-512 hash, fixed-512 hash (../corpus.md)
# Codesharp hashes are the post-Phase-I-Task-5b values (dotLLM 9fe6eb19+: chunk text tokenised as the chat path does;
# ../corpus.md "Re-pin after Phase I Task 5b"). Runs recorded in this experiment used the pre-5b values (dotLLM <= 63d17b87):
# symbol-512 bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb, fixed-512 cde11b22a9d64764f3043bf1d7be6035190465e8d4ec03a7c22e765faa19dceb.
$corpora = @(
    @('afclaude', 't8-corpus-AFClaude-b3f29c30-20261101111141', 'C:\Development\AFClaude', 'b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c',
        '2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938', 'b90ef5fa2bbaae8fafbc08c27d19d8259465898c412609e7c31e06076f69cbb6'),
    @('docagent', 't8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016', 'C:\Development\CSharpDocAgentFrameworkMCP', '6683823880bc2a7d62708907c725d9eaedf3a016',
        '5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7', '8d083a63d5c1db7514596aec9bdabf880695ded868a45459f6c8be21a354f2b4'),
    @('codesharp', 't8-corpus-codesharp-8e2adbd8-20261101111016', 'C:\Development\codesharp', '8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2',
        '364db68b1b21f7969dbf7d55e92277164ca23826954e794cac4bb065a28d8d2f', 'fb35a894dc2b43c31a14617c191c4512688c228e796a82c09caccf581710fc37')
)

$repo = 'bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF'
$hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots'
$modelFile = Get-ChildItem -Path $hub -Recurse -Filter 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf' | Select-Object -First 1
if (-not $modelFile) { throw "Qwen3-4B-Instruct-2507 Q4_K_M not found under $hub (hf download $repo --include '*Q4_K_M*')" }
$model = $modelFile.FullName

$project = Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj'
dotnet build $project -c Release | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$logDir = Join-Path $here 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
$os = Get-CimInstance Win32_OperatingSystem
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$all = [Diagnostics.Stopwatch]::StartNew()
foreach ($seed in $Seeds) {
    foreach ($chunker in $Chunkers) {
        foreach ($c in $corpora) {
            $name, $snap, $src, $commit, $hSym, $hFix = $c
            $hash = if ($chunker -eq 'symbol') { $hSym } else { $hFix }
            $labArgs = @('e3', '--model', $model, '--corpus', (Join-Path $Snapshots $snap), '--name', $name, '--chunker', $chunker,
                '--chunk', 512, '--seed', $seed, '--count', 100, '--context', $Context, '--contexts', $Contexts, '--query', 1,
                '--raw', $Raw, '--max-minutes', $MaxMinutes, '--expect-hash', $hash, '--out-dir', $OutDir)
            if ($chunker -eq 'symbol' -and $seed -eq 0 -and $Context -eq 2048) {
                $labArgs += @('--kept', (Join-Path $corpusDir "$name.validation.csv"), '--plans-jsonl', (Join-Path $corpusDir "$name.plans.jsonl"))
            }
            $logPath = Join-Path $logDir "$name-$chunker-s$seed-ctx$Context.log"
            $wtDirty = @(git -C $Worktree status --porcelain)
            $srcDirty = @(git -C $src status --porcelain)
            $prov = @(
                "# provenance"
                "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
                "command: ChunkKvLab $($labArgs -join ' ')"
                "hardware: $($cpu.Name.Trim()) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T), RAM $ramGb GB; $env:COMPUTERNAME; CPU only (deviceId -1)"
                "os: $($os.Caption) $($os.Version)"
                "dotnet sdk: $(dotnet --version)"
                "dotLLM worktree: $Worktree @ $(git -C $Worktree rev-parse HEAD) (branch $(git -C $Worktree rev-parse --abbrev-ref HEAD)); dirty files: $($wtDirty.Count)"
                "corpus: $snap = git archive $commit src of $src; source repo HEAD $(git -C $src rev-parse HEAD), dirty files now: $($srcDirty.Count); expected chunk-id sha256 ($chunker-512) $hash"
                "model: $repo @ $($modelFile.Directory.Name) / $($modelFile.Name) ($($modelFile.Length) bytes)"
                "# end provenance"
            )
            $prov | Tee-Object -FilePath $logPath
            if ($wtDirty.Count -gt 0) { Write-Warning 'dotLLM worktree has uncommitted changes: this run is not reproducible from the commit alone' }
            $sw = [Diagnostics.Stopwatch]::StartNew()
            dotnet run -c Release --no-build --project $project -- @labArgs 2>&1 | Tee-Object -FilePath $logPath -Append
            $exit = $LASTEXITCODE
            Write-Output ("wall time {0:F1} min; exit {1}; total {2:F1} min" -f $sw.Elapsed.TotalMinutes, $exit, $all.Elapsed.TotalMinutes) |
                Tee-Object -FilePath $logPath -Append
            if ($exit -ne 0) { throw "e3 failed for $name $chunker seed $seed" }
        }
    }
}
