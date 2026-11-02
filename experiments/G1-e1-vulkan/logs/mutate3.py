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
    ('T1a-host-delta-sign', A, SHIFT, '_backend.ShiftKeys(destination, offset, n, -offset, _rope);', 0),
    ('T1b-resident-delta-sign', A, SHIFT, '_backend.ShiftKeys(destination, offset, n, -offset, _rope);', 1),
    ('T2-host-write-wrong-layer', A, '_backend.WriteRows(destination, l, offset,', '_backend.WriteRows(destination, (l + 1) % layers, offset,', None),
    ('T3-resident-copy-wrong-offset', A, '_backend.CopyRows(chunk.Cache, l, 0, destination, offset, n);', '_backend.CopyRows(chunk.Cache, l, 0, destination, start, n);', None),
    ('T4a-host-skip-shift', A, 'if (offset != 0)', 'if (offset < 0)', 0),
    ('T4b-resident-skip-shift', A, 'if (offset != 0)', 'if (offset < 0)', 1),
    ('T5-encode-reads-wrong-layer', E, 'backend.ReadRows(cache, l, 0, n, keys[l], values[l]);', 'backend.ReadRows(cache, (l + 1) % layers, 0, n, keys[l], values[l]);', None),
    ('T6-encode-no-tag', E, 'keys, values, backend.Tag);', 'keys, values);', None),
    ('T7-resident-cpu-tag', E, 'tokenIds, cache, backend.Tag);', 'tokenIds, cache, ChunkBackendTags.Cpu);', None),
    ('T8-vk-copy-swapped', V, 'Checked(destination).CopyRowsFrom(Checked(source), layer, srcStart, dstStart, count)',
     'Checked(destination).CopyRowsFrom(Checked(source), layer, dstStart, srcStart, count)', None),
    ('T9-vk-shift-never-submitted', V, '        _submit.SubmitAndWait();\r\n    }', '    }', None),
    ('T10-no-tag-check', A, 'if (!string.Equals(backend, _backend.Tag, StringComparison.Ordinal))', 'if (false)', None),
    ('T11-encode-cpu-device-id', E, 'backend.ForwardDeviceId, cache', '-1, cache', None),
    ('T12-resident-skips-source-gate', A, '_backend.RequireCache(chunk.Cache);', '', None),
    ('T13-vk-shift-first-layer-only', V, '_shift.Record(_submit.CommandBuffer, c, l,', '_shift.Record(_submit.CommandBuffer, c, 0,', None),
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
