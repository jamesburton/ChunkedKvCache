"""Phase G Task 4 mutation runs in a git-archive scratch copy (never the live worktree).
usage: python -I mutate4.py <scratch-root> [mutant ids...]
Each mutant: (id, file, old, new, occurrence index or None = must be unique). Run under the dotLLM GPU lock (the filter includes GPU tests)."""
import subprocess, sys, os, re

ROOT = sys.argv[1]
ONLY = set(sys.argv[2:])
R = 'src/DotLLM.ChunkReuse/SelectiveRecomputer.cs'
MUTANTS = [
    ('M1-auto-is-per-run-on-vulkan', R, 'mode = onVulkan ? RecomputeMode.SinglePass : RecomputeMode.PerRun;', 'mode = RecomputeMode.PerRun;', None),
    ('M2-cpu-single-pass-allowed', R, 'if (mode == RecomputeMode.SinglePass && !onVulkan)', 'if (false)', None),
    ('M3-no-qpos-guard', R, 'if (!tight && ran != vulkan.Config.NumLayers)', 'if (false)', None),
    ('M4-single-pass-wrong-token-ids', R, 'ids[i] = tokens[positions[i]];', 'ids[i] = tokens[positions[0] + i];', None),
    ('M5-single-pass-contiguous-positions', R, 'qpos += Forward(model, model, cache, ids, positions,',
     'int[] cp = new int[count]; for (int i = 0; i < count; i++) cp[i] = positions[0] + i; qpos += Forward(model, model, cache, ids, cp,', None),
    ('M6-batch-skips-a-row', R, 'start += maxRowsPerForward)', 'start += maxRowsPerForward + 1)', None),
    ('M7-no-last-logits', R, 'if (positions[^1] == total - 1)', 'if (positions[^1] == total)', None),
    ('M8-no-require-cache', R, '        backend.RequireCache(cache);\r\n', '', None),
    ('M9-cpu-backend-accepts-vulkan-model', R, 'if (!onVulkan && vulkan is not null)', 'if (false)', None),
    ('M10-qpos-count-not-reported', R, 'return new SelectiveRecomputeResult(calls, selectedIndices.Length, lastLogits, qpos);',
     'return new SelectiveRecomputeResult(calls, selectedIndices.Length, lastLogits);', 1),
    ('M11-contiguous-run-counts-as-tight', R, 'positions[^1] + 1 == length;', 'positions[^1] + 1 <= length;', None),
    ('M12-recompute-skips-validation', R, '        Validate(cache, contextTokens.Length, selectedIndices);\r\n        if (selectedIndices.IsEmpty)\r\n            return new SelectiveRecomputeResult(0, 0, null);\r\n\r\n        return mode',
     '        if (selectedIndices.IsEmpty)\r\n            return new SelectiveRecomputeResult(0, 0, null);\r\n\r\n        return mode', None),
    ('M13-no-row-cap-check', R, '        ArgumentOutOfRangeException.ThrowIfLessThan(maxRowsPerForward, 1);\r\n', '', None),
    ('M14-vulkan-backend-accepts-host-model', R, 'if (onVulkan && vulkan is null)', 'if (false)', None),
    ('M15-per-run-merges-runs', R, 'while (end < selectedIndices.Length && selectedIndices[end] == selectedIndices[end - 1] + 1) end++;',
     'end = selectedIndices.Length;', None),
    ('M16-no-length-guard', R, 'if (cache.CurrentLength != length)', 'if (false)', None),
]
FILTER = 'FullyQualifiedName~ChunkReuse'

def run(cmd, timeout=None):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, shell=False, timeout=timeout)
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
        rc, out = run(['dotnet', 'build', 'tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj', '-c', 'Release', '-v', 'q', '-nologo'])
        if rc != 0:
            errs = sorted(set(l.split('[')[0].strip() for l in out.splitlines() if ' error ' in l))
            print(f'{mid}: BUILD FAILED {errs[:3]}', flush=True)
            continue
        try:
            rc, out = run(['dotnet', 'test', 'tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj', '-c', 'Release', '--no-build',
                           '--filter', FILTER, '--blame-hang-timeout', '5m'], timeout=900)
        except subprocess.TimeoutExpired:
            print(f'{mid}: KILLED (test run timed out: hang)', flush=True)
            continue
        failed = sorted(set(re.findall(r'^\s*Failed (\S+)', out, re.M)))
        summary = [l.strip() for l in out.splitlines() if 'Passed!' in l or 'Failed!' in l]
        aborted = 'aborted' in out.lower() or 'hang' in out.lower()
        verdict = 'KILLED' if failed or (rc != 0 and aborted) else ('SURVIVED' if rc == 0 else f'KILLED? rc={rc}')
        print(f'{mid}: {verdict} {summary} {[f.split(".")[-1] for f in failed]}', flush=True)
    finally:
        open(path, 'wb').write(orig)
        assert open(path, 'rb').read() == orig, f'{mid}: restore failed'
