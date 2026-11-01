# Task 8: generate cross-file code tasks for one frozen corpus and (optionally) validate them with the full-prefill reference
# (dotLLM CPU, Qwen3-4B-Instruct-2507 Q4_K_M). See ../corpus.md for the corpora, their commits and expected hashes.
# Usage:
#   ./run.ps1 -Name codesharp -Corpus <dir> -SourceRepo C:\Development\codesharp -CorpusCommit <sha> -Paths src -ExpectHash <sha256>
#             [-Count 100] [-Seed 0] [-Validate 1] [-MaxMinutes 0] [-Context 2048] [-Continuation 32] [-Prefix 256] [-PerContext 4]
# <dir> is `git archive <sha> <Paths>` of the source repo extracted into a fresh directory. The lab refuses to run unless the
# symbol-512 chunk-id SHA-256 equals -ExpectHash. Outputs <Name>.plans.jsonl, <Name>.validation.csv and <Name>.log here; every
# log starts with a provenance block.
param(
    [Parameter(Mandatory = $true)] [string] $Name,
    [Parameter(Mandatory = $true)] [string] $Corpus,
    [Parameter(Mandatory = $true)] [string] $SourceRepo,
    [Parameter(Mandatory = $true)] [string] $CorpusCommit,
    [string] $Paths = 'src',
    [Parameter(Mandatory = $true)] [string] $ExpectHash,
    [int] $Count = 100,
    [int] $Seed = 0,
    [int] $Validate = 1,
    [double] $MaxMinutes = 0,
    [int] $Context = 2048,
    [int] $Continuation = 32,
    [int] $Prefix = 256,
    [int] $PerContext = 4,
    [string] $Chunker = 'symbol',
    [int] $Chunk = 512,
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'   # read-only git: never refresh another checkout's index

$repo = 'bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF'
$hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots'
$modelFile = Get-ChildItem -Path $hub -Recurse -Filter 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf' | Select-Object -First 1
if (-not $modelFile) { throw "Qwen3-4B-Instruct-2507 Q4_K_M not found under $hub (hf download $repo --include '*Q4_K_M*')" }
$model = $modelFile.FullName
$revision = $modelFile.Directory.Name

$project = Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj'
dotnet build $project -c Release | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'build failed' }

$outPrefix = Join-Path $here $Name
$logPath = "$outPrefix.log"
$labArgs = @('tasks', '--model', $model, '--corpus', $Corpus, '--out', $outPrefix, '--chunker', $Chunker, '--chunk', $Chunk,
    '--count', $Count, '--seed', $Seed, '--context', $Context, '--continuation', $Continuation, '--prefix', $Prefix,
    '--per-context', $PerContext, '--validate', $Validate, '--max-minutes', $MaxMinutes, '--expect-hash', $ExpectHash)

$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
$os = Get-CimInstance Win32_OperatingSystem
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$wtDirty = @(git -C $Worktree status --porcelain)
$srcDirty = @(git -C $SourceRepo status --porcelain)
$csFiles = @(Get-ChildItem -Path $Corpus -Recurse -Filter '*.cs' -File).Count
$prov = @(
    "# provenance"
    "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
    "command: tasks name=$Name count=$Count seed=$Seed validate=$Validate max-minutes=$MaxMinutes context=$Context continuation=$Continuation prefix=$Prefix per-context=$PerContext chunker=$Chunker-$Chunk"
    "hardware: $($cpu.Name.Trim()) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T), RAM $ramGb GB; $env:COMPUTERNAME"
    "os: $($os.Caption) $($os.Version)"
    "dotnet sdk: $(dotnet --version)"
    "dotLLM worktree: $Worktree @ $(git -C $Worktree rev-parse HEAD) (branch $(git -C $Worktree rev-parse --abbrev-ref HEAD)); dirty files: $($wtDirty.Count)"
    "corpus: $Corpus = git archive $CorpusCommit $Paths of $SourceRepo (frozen snapshot, $csFiles .cs files); source repo HEAD $(git -C $SourceRepo rev-parse HEAD), dirty files now: $($srcDirty.Count); expected chunk-id sha256 $ExpectHash"
)
$prov += $wtDirty | ForEach-Object { "  worktree dirty: $_" }
$prov += "model: $repo @ $revision / $($modelFile.Name) ($($modelFile.Length) bytes)"
$prov += "# end provenance"
$prov | Tee-Object -FilePath $logPath
if ($wtDirty.Count -gt 0) { Write-Warning 'dotLLM worktree has uncommitted changes: this run is not reproducible from the commit alone' }

$sw = [Diagnostics.Stopwatch]::StartNew()
dotnet run -c Release --no-build --project $project -- @labArgs 2>&1 | Tee-Object -FilePath $logPath -Append
$exit = $LASTEXITCODE
Write-Output ("wall time {0:F1} min; exit {1}" -f $sw.Elapsed.TotalMinutes, $exit) | Tee-Object -FilePath $logPath -Append
