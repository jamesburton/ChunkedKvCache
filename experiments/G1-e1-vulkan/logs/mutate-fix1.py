"""Phase G Task 3 mutation runs in a git-archive scratch copy (never the live worktree).
usage: python -I mutate3.py <scratch-root> [mutant ids...]
Each mutant: (id, file, old, new, occurrence index or None = must be unique)."""
import subprocess, sys, os, re

ROOT = sys.argv[1]
ONLY = set(sys.argv[2:])
SRC = 'src/DotLLM.ChunkReuse/'
A, E, V, C = SRC + 'ChunkAssembler.cs', SRC + 'ChunkEncoder.cs', SRC + 'Backends/VulkanChunkBackend.cs', SRC + 'Backends/CpuChunkBackend.cs'
SHIFT = '_backend.ShiftKeys(destination, offset, n, offset, _rope);'
MUTANTS = [
    ('F1-host-no-rollback', A, 'destination.Rollback(start);', '', 0),
    ('F2-resident-no-rollback', A, 'destination.Rollback(start);', '', 1),
    ('F3-no-rope-check', A, 'if (backend.Rope is RopeParameters bound && bound != _rope)', 'if (backend.Rope is RopeParameters bound && false)', None),
    ('F4-assembler-no-disposed-check', A, 'ObjectDisposedException.ThrowIf(chunk.IsDisposed, chunk);', '', None),
    ('F5-cache-getter-no-guard', SRC + 'ResidentChunkKvEntry.cs', 'ObjectDisposedException.ThrowIf(IsDisposed, this);', '', None),
    ('F6-no-self-destination-check', A, 'if (ReferenceEquals(chunk.Cache, destination))', 'if (false)', None),
    ('F7-no-short-source-check', A, 'if (chunk.Cache.CurrentLength < chunk.Length)', 'if (false)', None),
    ('F8-dispose-never-flags', SRC + 'ResidentChunkKvEntry.cs', 'IsDisposed = true;', '', None),
    ('F9-vk-shift-delta0-early-return', V, 'int headDim = _config.HeadDim;', 'if (delta == 0) return;  int headDim = _config.HeadDim;', None),
    ('F10-cpu-rope-not-null', C, 'public RopeParameters? Rope => null;', 'public RopeParameters? Rope => RopeParameters.FromConfig(_config);', None),
]
FILTER = 'FullyQualifiedName~VulkanAssemblyTests|FullyQualifiedName~BackendSeamTests'

def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, shell=False)
    return p.returncode, p.stdout + p.stderr

def apply(text, old, new, occ):
    for o, n in ((old, new), (old.replace('\r\n', '\n'), new.replace('\r\n', '\n'))):
        cnt = text.count(o)
        if occ is None and cnt == 1:
            return text.replace(o, n)
        if occ is not None and cnt > occ:
            i = -1
            for _ in range(occ + 1):
                i = text.index(o, i + 1)
            return text[:i] + n + text[i + len(o):]
    return None

for mid, rel, old, new, occ in MUTANTS:
    if ONLY and mid not in ONLY:
        continue
    path = os.path.join(ROOT, rel)
    orig = open(path, 'rb').read()
    mutated = apply(orig.decode('utf-8'), old, new, occ)
    if mutated is None:
        print(f'{mid}: PATTERN NOT FOUND', flush=True)
        continue
    open(path, 'wb').write(mutated.encode('utf-8'))
    try:
        rc, out = run(['dotnet', 'build', 'tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj', '-v', 'q', '-nologo'])
        if rc != 0:
            errs = sorted(set(l.split('[')[0].strip() for l in out.splitlines() if ' error ' in l))
            print(f'{mid}: BUILD FAILED {errs[:3]}', flush=True)
            continue
        rc, out = run(['dotnet', 'test', 'tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj', '--no-build', '--filter', FILTER])
        failed = sorted(set(re.findall(r'^\s*Failed (\S+)', out, re.M)))
        summary = [l.strip() for l in out.splitlines() if 'Passed!' in l or 'Failed!' in l]
        verdict = 'KILLED' if failed else 'SURVIVED'
        print(f'{mid}: {verdict} {summary} {[f.split(".")[-1] for f in failed]}', flush=True)
    finally:
        open(path, 'wb').write(orig)
        assert open(path, 'rb').read() == orig, f'{mid}: restore failed'
