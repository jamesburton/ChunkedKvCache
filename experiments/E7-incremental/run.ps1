# Phase S Task 4 / E7: incremental re-encode cost of single-method edits, symbol vs fixed-512 chunking (ChunkIndex).
# Tokenizer only (Qwen3-4B-Instruct-2507 GGUF's BPE); no model forward, CPU, one process.
# Usage:
#   ./run.ps1 -Snapshots <dir holding the t8-corpus-* snapshots> [-Name codesharp] [-Seeds 0,1,2] [-Edits 100] [-NoBuild]
#   then: uv run summarize.py raw/<name>.csv > summary.md
param(
    [Parameter(Mandatory = $true)] [string] $Snapshots,
    [string] $Name = 'codesharp',
    [string] $Seeds = '0,1,2',
    [int] $Edits = 100,
    [string] $Worktree = 'C:\Development\dotLLM\.claude\worktrees\chunk-index',
    [switch] $NoBuild
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$env:GIT_OPTIONAL_LOCKS = '0'

# name -> snapshot dir, source repo, commit, symbol-512 hash, fixed-512 hash (../corpus.md)
$corpora = @{
    'afclaude'  = @('t8-corpus-AFClaude-b3f29c30-20261101111141', 'C:\Development\AFClaude', 'b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c',
        '2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938', 'b90ef5fa2bbaae8fafbc08c27d19d8259465898c412609e7c31e06076f69cbb6')
    'docagent'  = @('t8-corpus-CSharpDocAgentFrameworkMCP-66838238-20261101111016', 'C:\Development\CSharpDocAgentFrameworkMCP', '6683823880bc2a7d62708907c725d9eaedf3a016',
        '5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7', '8d083a63d5c1db7514596aec9bdabf880695ded868a45459f6c8be21a354f2b4')
    'codesharp' = @('t8-corpus-codesharp-8e2adbd8-20261101111016', 'C:\Development\codesharp', '8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2',
        'bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb', 'cde11b22a9d64764f3043bf1d7be6035190465e8d4ec03a7c22e765faa19dceb')
}
$snap, $src, $commit, $hSym, $hFix = $corpora[$Name]

$hub = Join-Path $env:USERPROFILE '.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots'
$modelFile = Get-ChildItem -Path $hub -Recurse -Filter 'Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf' | Select-Object -First 1
if (-not $modelFile) { throw "Qwen3-4B-Instruct-2507 Q4_K_M not found under $hub" }

$project = Join-Path $Worktree 'benchmarks\ChunkKvLab\ChunkKvLab.csproj'
if (-not $NoBuild) {
    dotnet build $project -c Release -m:4 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'build failed' }
}
$exe = Join-Path $Worktree 'benchmarks\ChunkKvLab\bin\Release\net10.0\ChunkKvLab.exe'
New-Item -ItemType Directory -Force (Join-Path $here 'raw'), (Join-Path $here 'logs') | Out-Null
$log = Join-Path $here "logs\e7-$Name.log"
$out = Join-Path $here "raw\$Name.csv"

$dirty = @(git -C $Worktree status --porcelain).Count
@(
    "# E7 incremental re-encode, started $(Get-Date -Format o)"
    "dotLLM worktree $Worktree branch $(git -C $Worktree rev-parse --abbrev-ref HEAD) head $(git -C $Worktree rev-parse HEAD) dirty=$dirty"
    "corpus $Name snapshot $snap (git archive $src @ $commit); expect symbol-512 $hSym, fixed-512 $hFix"
    "model (tokenizer only) $($modelFile.FullName)"
    "seeds $Seeds, edits per seed $Edits; host $((Get-CimInstance Win32_Processor | Select-Object -First 1).Name), dotnet $(dotnet --version)"
) | Set-Content -Encoding utf8 $log

& $exe e7 --model $modelFile.FullName --corpus (Join-Path $Snapshots $snap) --seeds $Seeds --edits $Edits `
    --expect-hash-symbol $hSym --expect-hash-fixed $hFix --out $out 2>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { throw "e7 failed ($LASTEXITCODE)" }
