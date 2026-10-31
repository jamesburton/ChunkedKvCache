# E1 baselines: full prefill vs naive chunk-KV concatenation vs exact prefix reuse (dotLLM CPU, Qwen3-4B-Instruct-2507 Q4_K_M).
# Usage (from anywhere):
#   ./run.ps1                                  # e1 at 2K/4K/8K, 3 seeds -> results.csv (+ results-details.csv, e1.log)
#   ./run.ps1 -Sizes 16384 -Out results-16k.csv -Log e1-16k.log
#   ./run.ps1 -Command rope-precision          # RoPE-shift error at large offsets -> rope-precision.csv
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

# Model is read in place from the HF hub cache (never copied).
$hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots'
$model = (Get-ChildItem -Path $hub -Recurse -Filter 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf' | Select-Object -First 1).FullName
if (-not $model) { throw "Qwen3-4B-Instruct-2507 Q4_K_M not found under $hub (hf download bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF --include '*Q4_K_M*')" }

$project = Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj'
dotnet build $project -c Release | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
Write-Output "dotLLM commit: $(git -C $Worktree rev-parse HEAD)"

if ($Command -eq 'e1') {
    if (-not $Out) { $Out = 'results.csv' }
    if (-not $Log) { $Log = 'e1.log' }
    $labArgs = @('e1', '--model', $model, '--corpus', $Corpus, '--seeds', $Seeds, '--sizes', $Sizes, '--out', (Join-Path $here $Out))
} else {
    if (-not $Out) { $Out = 'rope-precision.csv' }
    if (-not $Log) { $Log = 'rope-precision.log' }
    $labArgs = @('rope-precision', '--model', $model, '--corpus', $Corpus, '--deltas', $Deltas, '--out', (Join-Path $here $Out))
}
$sw = [Diagnostics.Stopwatch]::StartNew()
dotnet run -c Release --no-build --project $project -- @labArgs 2>&1 | Tee-Object -FilePath (Join-Path $here $Log)
Write-Output ("wall time {0:F1} min" -f $sw.Elapsed.TotalMinutes) | Tee-Object -FilePath (Join-Path $here $Log) -Append
