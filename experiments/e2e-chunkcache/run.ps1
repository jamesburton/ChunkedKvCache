# Phase I5 Part A: end-to-end run of the chunk cache (CLI-built store -> dotllm serve --chunk-cache -> annotated requests).
#
#   pwsh run.ps1 -Backend cpu    -ServerCommit ea2279cf -ClientCommit 5f003693 -Model <gguf> [-Only A3,A4]
#   pwsh run.ps1 -Backend vulkan -ServerCommit ea2279cf -ClientCommit 5f003693 -Model <gguf> -Only V1,V2,V3,VOH -StoreFrom <cpu run id>
#
# Exit 0 only when every selected check passes. Ports 18080+ (never 8080). Locks are NOT taken here: the caller holds
# ResourceLock cpu-bench (cpu) or gpu + scripts/gpu-lock.sh (vulkan) around the call. Builds come from `git archive`
# exports under C:\Development\dotLLM-e2e\<sha8>\ (never from a live worktree).
param(
    [Parameter(Mandatory)][ValidateSet('cpu', 'vulkan')][string] $Backend,
    [Parameter(Mandatory)][string] $ServerCommit,
    [Parameter(Mandatory)][string] $ClientCommit,
    [Parameter(Mandatory)][string] $Model,
    [string[]] $Only = @(),
    [string] $RunId = '',
    [string] $StoreFrom = '',          # vulkan: run id whose CPU-built store to use (read-only checks; copy of it for V3)
    [string] $DotllmRepo = 'C:\Development\dotLLM',
    [string] $E2eRoot = 'C:\Development\dotLLM-e2e',
    [int] $Threads = 8,
    [int] $CtxSize = 8192,
    [int] $BasePort = 18080,
    [string] $LockHolder = ''
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$py = 'python'
if (-not $RunId) { $RunId = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$Backend" }
$out = Join-Path $here "results\$RunId"
New-Item -ItemType Directory -Force $out | Out-Null
$runWork = Join-Path $E2eRoot "runs\$RunId"          # stores and server logs: scratch, never committed
New-Item -ItemType Directory -Force $runWork | Out-Null
$store = Join-Path $runWork 'store'
$store2 = Join-Path $runWork 'store2'
$timeline = [ordered]@{}
$runSw = [Diagnostics.Stopwatch]::StartNew()

function Short([string] $sha) { $sha.Substring(0, 8) }

function Export-Tree([string] $branchOrSha, [string] $dest) {
    if (Test-Path (Join-Path $dest 'dotLLM.slnx')) { return }
    New-Item -ItemType Directory -Force $dest | Out-Null
    $tar = Join-Path $runWork 'export.tar'
    git -C $DotllmRepo archive --format=tar -o $tar $branchOrSha
    if ($LASTEXITCODE -ne 0) { throw "git archive $branchOrSha failed" }
    tar -xf $tar -C $dest
    Remove-Item $tar
}

$srvDir = Join-Path $E2eRoot (Short $ServerCommit)
$cliDir = Join-Path $E2eRoot "client-$(Short $ClientCommit)"
Export-Tree $ServerCommit $srvDir
Export-Tree $ClientCommit $cliDir

$dotllm = Join-Path $srvDir 'src\DotLLM.Cli\bin\Release\net10.0\DotLLM.Cli.exe'
$cc = Join-Path $srvDir 'tools\DotLLM.ChunkCache\bin\Release\net10.0\chunkcache.exe'
if (-not (Test-Path $dotllm)) { dotnet build (Join-Path $srvDir 'src\DotLLM.Cli') -c Release -m:2 -p:UseSharedCompilation=false | Out-Null; if ($LASTEXITCODE) { throw 'build dotllm failed' } }
if (-not (Test-Path $cc)) { dotnet build (Join-Path $srvDir 'tools\DotLLM.ChunkCache') -c Release -m:2 -p:UseSharedCompilation=false | Out-Null; if ($LASTEXITCODE) { throw 'build chunkcache failed' } }
$smokeProj = Join-Path $here 'ClientSmoke\ClientSmoke.csproj'
dotnet build $smokeProj -c Release -p:ClientRoot=$cliDir | Out-Null
if ($LASTEXITCODE) { throw 'build ClientSmoke failed' }
$smokeDll = Join-Path $here 'ClientSmoke\bin\Release\net10.0\ClientSmoke.dll'

# Fixture repo: git archive <S_A> src/DotLLM.ChunkReuse/Store (frozen by commit)
$repo = Join-Path $E2eRoot 'e2e-repo'
if (-not (Test-Path (Join-Path $repo 'src\DotLLM.ChunkReuse\Store\ChunkKey.cs'))) {
    New-Item -ItemType Directory -Force $repo | Out-Null
    $tar = Join-Path $runWork 'repo.tar'
    git -C $DotllmRepo archive --format=tar -o $tar $ServerCommit src/DotLLM.ChunkReuse/Store
    tar -xf $tar -C $repo
}

# Provenance
$snap = ($Model -split 'snapshots\\')[1] -split '\\' | Select-Object -First 1
$gpu = Get-CimInstance Win32_VideoController | Select-Object -First 1
$meta = [ordered]@{
    run_id = $RunId; backend = $Backend; date = (Get-Date -Format o)
    server_commit = $ServerCommit; client_commit = $ClientCommit; export_dirty = 0
    research_repo_commit = (git -C $here rev-parse HEAD); research_repo_dirty_in_e2e_dir = ((git -C $here status --porcelain -- . | Measure-Object).Count)
    model_file = (Split-Path $Model -Leaf); model_hf_revision = $snap; model_path = $Model
    driver = "$($gpu.Name) $($gpu.DriverVersion)"; lock_holder = $LockHolder
    server_args_base = "serve <model> --no-warmup --no-browser --no-ui --threads $Threads --ctx-size $CtxSize"
    kv_note = 'server branch has no F16-default Vulkan KV (PR #1597): on Vulkan its KV is F32'
}
$metaPath = Join-Path $out 'meta.json'

$wantAll = ($Only.Count -eq 0)
function Want([string] $id) { return $wantAll -or ($Only -contains $id) }
function WantAny([string[]] $ids) { foreach ($i in $ids) { if (Want $i) { return $true } }; return $false }

$script:fail = 0
$script:port = $BasePort
function Py { param([string[]] $a) & $py -I (Join-Path $here 'e2e.py') @a | Out-Host; return $LASTEXITCODE }

function Start-Server([string] $name, [string[]] $extra) {
    $script:port++
    $log = Join-Path $runWork "server-$name.log"
    $errlog = Join-Path $runWork "server-$name.err.log"
    $args1 = @('serve', $Model, '--port', "$script:port", '--host', '127.0.0.1', '--no-warmup', '--no-browser', '--no-ui',
               '--threads', "$Threads", '--ctx-size', "$CtxSize") + $extra
    if ($Backend -eq 'vulkan') { $args1 += @('--device', 'vulkan') }
    $p = Start-Process -FilePath $dotllm -ArgumentList $args1 -PassThru -NoNewWindow -RedirectStandardOutput $log -RedirectStandardError $errlog
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $base = "http://127.0.0.1:$script:port"
    while ($sw.Elapsed.TotalSeconds -lt 300) {
        if ($p.HasExited) { throw "server $name exited early (code $($p.ExitCode)); see $errlog" }
        try { $r = Invoke-WebRequest -UseBasicParsing "$base/ready" -TimeoutSec 3; if ($r.StatusCode -eq 200) { break } } catch { }
        Start-Sleep -Milliseconds 1000
    }
    if ($sw.Elapsed.TotalSeconds -ge 300) { Stop-Process -Id $p.Id -Force; throw "server $name not ready in 300 s" }
    $m = (Invoke-RestMethod "$base/v1/models").data[0].id
    "server $name pid $($p.Id) ready in $([math]::Round($sw.Elapsed.TotalSeconds,1)) s on $base (model id '$m')" | Tee-Object -FilePath (Join-Path $out 'run.log') -Append
    return [pscustomobject]@{ Proc = $p; Base = $base; Model = $m; Log = $log; ErrLog = $errlog; Name = $name }
}

function Stop-Server($s) {
    if ($null -eq $s) { return }
    try { Stop-Process -Id $s.Proc.Id -Force -ErrorAction SilentlyContinue; $s.Proc.WaitForExit(20000) | Out-Null } catch { }
    Start-Sleep -Seconds 2
}

function Run-Checks([string] $phase, $srv, [string[]] $ids, [string[]] $more = @()) {
    $ids = @($ids | Where-Object { Want $_ })
    if ($ids.Count -eq 0) { return }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $a = @('check') + $ids + @('--base-url', $srv.Base, '--model-name', $srv.Model, '--store', $store, '--store2', $store2, '--out', $out,
        '--model', $Model, '--cc-exe', $cc, '--repo', $repo, '--threads', "$Threads", '--smoke-dll', $smokeDll,
        '--server-log', $srv.ErrLog, '--phase', $phase) + $more
    $rc = Py $a
    if ($rc -ne 0) { $script:fail++ }
    $timeline["phase_$phase"] = [math]::Round($sw.Elapsed.TotalSeconds, 1)
}

function Server-Phase([string] $phase, [string[]] $extra, [string[]] $ids, [string[]] $more = @()) {
    if (-not (WantAny $ids)) { return }
    $s = Start-Server $phase $extra
    try { Run-Checks $phase $s $ids $more } finally { Stop-Server $s }
}

try {
    $rc = Py @('prep', '--model', $Model, '--cc-exe', $cc, '--repo', $repo, '--out', $out)
    if ($rc -ne 0) { throw 'prep failed' }

    if ($Backend -eq 'cpu') {
        # A0: CLI build (no server)
        if (Want 'A0') {
            if (Test-Path $store) { Remove-Item -Recurse -Force $store }
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $rc = Py @('check', 'A0', '--store', $store, '--out', $out, '--model', $Model, '--cc-exe', $cc, '--repo', $repo, '--threads', "$Threads", '--phase', 'build')
            if ($rc -ne 0) { $script:fail++ }
            $timeline['A0_build'] = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        }
        # A1: flag off
        Server-Phase 'off' @() @('A1')
        # read-only store, chunk cache on (default paged/scheduler path)
        Server-Phase 'ro' @('--chunk-cache', '--chunk-store', $store) @('A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A12')
        # warm-slot neutrality on the prefix-cache path (--no-paged)
        Server-Phase 'nopaged' @('--no-paged', '--chunk-cache', '--chunk-store', $store) @('A4b')
        # sole writer
        Server-Phase 'write' @('--chunk-cache', '--chunk-store', $store, '--chunk-store-write', '--chunk-store-budget', '4GB') @('A8', 'A9', 'A10', 'A12')
        # auth + namespaces
        if (WantAny @('A11')) {
            $ka = & $py -I -c "import secrets;print(secrets.token_urlsafe(32))"
            $kb = & $py -I -c "import secrets;print(secrets.token_urlsafe(32))"
            $keys = Join-Path $runWork 'keys.txt'
            "$ka admin`n$kb`n" | Set-Content -Encoding ascii $keys
            Server-Phase 'auth' @('--chunk-cache', '--chunk-store', $store, '--chunk-store-write', '--chunk-store-budget', '4GB', '--chunk-cache-api-keys', $keys) @('A11', 'A12') @('--key-a', $ka, '--key-b', $kb)
        }
    } else {
        if ($StoreFrom) {
            $src = Join-Path $E2eRoot "runs\$StoreFrom\store"
            if (-not (Test-Path $src)) { throw "no CPU store at $src" }
            if (Test-Path $store) { Remove-Item -Recurse -Force $store }
            New-Item -ItemType Directory -Force $store | Out-Null
            # hardlinks, never copies of the entry files (V3 must see the same bytes the CPU run wrote)
            Get-ChildItem $src -Recurse -File | ForEach-Object {
                $rel = $_.FullName.Substring($src.Length + 1)
                $dst = Join-Path $store $rel
                New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
                if ($_.Name -like '*.ckv') { New-Item -ItemType HardLink -Path $dst -Target $_.FullName | Out-Null } else { Copy-Item $_.FullName $dst }
            }
        }
        Server-Phase 'vk-ro' @('--chunk-cache', '--chunk-store', $store) @('V1', 'V2', 'VOH')
        Server-Phase 'vk-write' @('--chunk-cache', '--chunk-store', $store, '--chunk-store-write', '--chunk-store-budget', '1GB') @('V3')
    }
}
finally {
    $timeline['total'] = [math]::Round($runSw.Elapsed.TotalSeconds, 1)
    $meta['wall_s'] = $timeline
    $meta | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $metaPath
    Py @('summarize', '--out', $out, '--meta', $metaPath) | Out-Null
}
Get-Content (Join-Path $out 'summary.md') | Select-Object -First 60
exit ([int]($script:fail -gt 0))
