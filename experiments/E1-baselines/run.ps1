# E1 baselines: full prefill vs naive chunk-KV concatenation vs exact prefix reuse (dotLLM CPU, Qwen3-4B-Instruct-2507 Q4_K_M).
# Usage (from anywhere):
#   ./run.ps1                                  # e1 at 2K/4K/8K, 3 seeds -> results.csv (+ results-details.csv, e1.log)
#   ./run.ps1 -Sizes 16384 -Seeds 1 -Out results-16k.csv -Log e1-16k.log
#   ./run.ps1 -Command rope-precision          # RoPE-shift error at large offsets -> rope-precision.csv
# Every log starts with a provenance block: UTC time, hardware, OS, .NET SDK, dotLLM commit (+ dirty files), corpus commit
# (+ dirty files under the corpus dir), model repo/revision/file/size. The lab then logs the corpus chunk-id SHA-256.
param(
    [ValidateSet('e1', 'rope-precision')] [string] $Command = 'e1',
    [string] $Sizes = '2048,4096,8192',
    [int] $Seeds = 3,
    [string] $Deltas = '1024,4096,8192,16384',
    [string] $Out = '',
    [string] $Log = '',
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse',
    [string] $Corpus = 'C:\Development\dotLLM\src'
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

if ($Command -eq 'e1') {
    if (-not $Out) { $Out = 'results.csv' }
    if (-not $Log) { $Log = 'e1.log' }
    $labArgs = @('e1', '--model', $model, '--corpus', $Corpus, '--seeds', $Seeds, '--sizes', $Sizes, '--out', (Resolve-Here $Out))
} else {
    if (-not $Out) { $Out = 'rope-precision.csv' }
    if (-not $Log) { $Log = 'rope-precision.log' }
    $labArgs = @('rope-precision', '--model', $model, '--corpus', $Corpus, '--deltas', $Deltas, '--out', (Resolve-Here $Out))
}
$logPath = Resolve-Here $Log

# Provenance ---------------------------------------------------------------------------------------------------------
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
$os = Get-CimInstance Win32_OperatingSystem
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$wtDirty = @(git -C $Worktree status --porcelain)
$corpusTop = git -C $Corpus rev-parse --show-toplevel 2>$null
$corpusHead = if ($corpusTop) { git -C $Corpus rev-parse HEAD } else { 'not a git checkout' }
$corpusDirty = if ($corpusTop) { @(git -C $Corpus status --porcelain -- .) } else { @() }
$prov = @(
    "# provenance"
    "utc: $([DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss'))"
    "command: $Command sizes=$Sizes seeds=$Seeds deltas=$Deltas"
    "hardware: $($cpu.Name.Trim()) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T), RAM $ramGb GB; $env:COMPUTERNAME"
    "os: $($os.Caption) $($os.Version)"
    "dotnet sdk: $(dotnet --version)"
    "dotLLM worktree: $Worktree @ $(git -C $Worktree rev-parse HEAD) (branch $(git -C $Worktree rev-parse --abbrev-ref HEAD)); dirty files: $($wtDirty.Count)"
    "corpus: $Corpus @ $corpusHead; dirty files under corpus: $($corpusDirty.Count)"
)
$prov += $wtDirty | ForEach-Object { "  worktree dirty: $_" }
$prov += $corpusDirty | ForEach-Object { "  corpus dirty: $_" }
$prov += "model: $repo @ $revision / $($modelFile.Name) ($($modelFile.Length) bytes)"
$prov += "# end provenance"
$prov | Tee-Object -FilePath $logPath
if ($corpusDirty.Count -gt 0) { Write-Warning 'corpus has uncommitted changes: this run is not reproducible from the commit alone' }

$sw = [Diagnostics.Stopwatch]::StartNew()
dotnet run -c Release --no-build --project $project -- @labArgs 2>&1 | Tee-Object -FilePath $logPath -Append
Write-Output ("wall time {0:F1} min" -f $sw.Elapsed.TotalMinutes) | Tee-Object -FilePath $logPath -Append
