# E2 baseline selectors: quality vs recompute budget (dotLLM CPU, Qwen3-4B-Instruct-2507 Q4_K_M).
# Usage (from anywhere):
#   ./run.ps1 -Corpus <dir with git-archive 4a781829 src>                       # full grid -> results.csv, e2.log
#   ./run.ps1 -Corpus <dir> -Sizes 2048 -Seeds 1 -Selectors random -Budgets 5 -Contiguous none -Out smoke.csv -Log smoke.log
# The corpus is PINNED: `git archive 4a781829 src` of C:\Development\dotLLM extracted into a fresh directory (pass it as -Corpus).
# The lab refuses to run unless the corpus's chunk-id SHA-256 equals -ExpectHash (Task 5: 1086 docs, 7257 chunks at 4a781829).
# Every log starts with a provenance block: UTC time, hardware, OS, .NET SDK, dotLLM commit (+ dirty files), corpus commit and
# directory, model repo/revision/file/size. The lab then logs the corpus chunk-id SHA-256.
param(
    [string] $Sizes = '2048,4096',
    [int] $Seeds = 3,
    [int] $FirstSeed = 0,
    [string] $Budgets = '5,10,15,20',
    [string] $Selectors = 'first_k,chunk_starts,deviation,deviation_oracle,random,query,combined',
    [string] $Contiguous = 'first_k,chunk_starts,deviation,deviation_oracle,random,query,combined',
    [int] $Query = 16,
    [int] $Noise = 1,
    [string] $Out = 'results.csv',
    [string] $Log = 'e2.log',
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse',
    [Parameter(Mandatory = $true)] [string] $Corpus,
    [string] $CorpusCommit = '4a7818290766b69a3bae0999874154185c7fa587',
    [string] $ExpectHash = 'b02b1e6e44ebbf82169f29a42d7847d7ba69203fc52f9d07bef60335c90dc800'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'   # read-only git: never refresh another checkout's index
function Resolve-Here([string] $p) { if ([IO.Path]::IsPathRooted($p)) { $p } else { Join-Path $here $p } }

# Model is read in place from the HF hub cache (never copied).
$repo = 'bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF'
$hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots'
$modelFile = Get-ChildItem -Path $hub -Recurse -Filter 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf' | Select-Object -First 1
if (-not $modelFile) { throw "Qwen3-4B-Instruct-2507 Q4_K_M not found under $hub (hf download $repo --include '*Q4_K_M*')" }
$model = $modelFile.FullName
$revision = $modelFile.Directory.Name   # HF snapshot directory = full commit hash of the model repo

$project = Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj'
dotnet build $project -c Release | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'build failed' }

$contigArg = if ($Contiguous -eq 'none') { '' } else { $Contiguous }
$labArgs = @('e2', '--model', $model, '--corpus', $Corpus, '--seeds', $Seeds, '--first-seed', $FirstSeed, '--sizes', $Sizes,
    '--budgets', $Budgets, '--selectors', $Selectors, '--contiguous', "=$contigArg", '--query', $Query, '--noise', $Noise,
    '--expect-hash', $ExpectHash, '--out', (Resolve-Here $Out))
$logPath = Resolve-Here $Log

# Provenance ---------------------------------------------------------------------------------------------------------
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
$os = Get-CimInstance Win32_OperatingSystem
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$wtDirty = @(git -C $Worktree status --porcelain)
$csFiles = @(Get-ChildItem -Path $Corpus -Recurse -Filter '*.cs' -File).Count
$prov = @(
    "# provenance"
    "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
    "command: e2 sizes=$Sizes seeds=$Seeds first-seed=$FirstSeed budgets=$Budgets selectors=$Selectors contiguous=$Contiguous query=$Query noise=$Noise"
    "hardware: $($cpu.Name.Trim()) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T), RAM $ramGb GB; $env:COMPUTERNAME"
    "os: $($os.Caption) $($os.Version)"
    "dotnet sdk: $(dotnet --version)"
    "dotLLM worktree: $Worktree @ $(git -C $Worktree rev-parse HEAD) (branch $(git -C $Worktree rev-parse --abbrev-ref HEAD)); dirty files: $($wtDirty.Count)"
    "corpus: $Corpus = git archive $CorpusCommit src of C:\Development\dotLLM (frozen snapshot, $csFiles .cs files); expected chunk-id sha256 $ExpectHash"
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
