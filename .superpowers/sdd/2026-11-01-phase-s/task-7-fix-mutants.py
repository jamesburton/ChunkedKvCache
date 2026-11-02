# Task 7 fix-round mutants (review S1-S9). Usage: python t7_fix_mutants.py <copy-root> <log> [ids...]
import subprocess, sys, re, time, os

root = sys.argv[1]
log_path = sys.argv[2]
only = set(sys.argv[3:])
T = 'tools/DotLLM.ChunkCache/'
M = [
 ('F1', T+'BuildCommand.cs',
  '        if (selectedIds is not null) candidates = candidates.Where(r => selectedIds.Contains(r.Id));\n        var seen = new HashSet<string>(StringComparer.Ordinal);\n        List<ChunkRef> missing = candidates.Where(r => seen.Add(r.KeyHex!)).ToList();',
  '        var seen = new HashSet<string>(StringComparer.Ordinal);\n        List<ChunkRef> missing = candidates.Where(r => seen.Add(r.KeyHex!)).ToList();\n        if (selectedIds is not null) missing = missing.Where(r => selectedIds.Contains(r.Id)).ToList();',
  'S1: dedupe by key before the selection (old behaviour)'),
 ('F2', T+'EvictCommand.cs', 'string[] bad = dropIndexes.Where(f => !layout.IsIndexFileName(f)).ToArray();', 'string[] bad = [];', 'S2: registry index names not validated'),
 ('F3', T+'StoreLayout.cs', 'if (!name.StartsWith("index-", StringComparison.Ordinal) || !name.EndsWith(".json", StringComparison.OrdinalIgnoreCase)) return false;', '', 'S2: index-*.json pattern not required'),
 ('F4', T+'Program.cs', 'return ChunkCacheCli.Run(args, stdout, stderr);', 'return ChunkCacheCli.Run(args, Console.Out, Console.Error);', 'S4: console code page on stdout'),
 ('F5', T+'Program.cs', 'var utf8 = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);', 'var utf8 = new UTF8Encoding(encoderShouldEmitUTF8Identifier: true);', 'S4: BOM on stdout'),
 ('F6', T+'CliArgs.cs', "if (kind == OptionKind.List && value.Contains(',', StringComparison.Ordinal))", 'if (false)', 'S4: commas accepted in list values'),
 ('F7', T+'ChunkCacheCli.cs', '            if (json) ctx.WriteJson(new ErrorResult(new ErrorBody(code, exit, message)));\n', '', 'S5: no JSON error object'),
 ('F8', T+'BuildCommand.cs', '        if (failures > 0)\n', '        if (false)\n', 'S9: store-write failures exit 0'),
 ('F9', T+'BuildCommand.cs', 'StoreLayout layout = StoreLayout.Open(storeRoot, create: !dryRun);', 'StoreLayout layout = StoreLayout.Open(storeRoot, create: true);', 'S9: dry run creates the store'),
 ('F10', T+'StatusCommand.cs', 'StoreLayout layout = StoreLayout.Open(storeRoot, create: false);', 'StoreLayout layout = StoreLayout.Open(storeRoot, create: true);', 'S9: status creates the store (dead: the verb checks existence first)'),
 ('F11', T+'CompareCommand.cs', 'fullCalls = Calls(L, block) + Calls(query.Length, block);', 'fullCalls = 0;', 'S8: full row reports 0 forward calls'),
 ('F12', T+'CompareCommand.cs', 'double reuse = assembleMs + scoreMs + selectMs + rec.Elapsed.TotalMilliseconds + queryMs;', 'double reuse = assembleMs + scoreMs + selectMs + rec.Elapsed.TotalMilliseconds;', 'S8: reuse time without the query prefill'),
 ('F13', T+'CompareCommand.cs', 'double reuse = assembleMs + scoreMs + selectMs + rec.Elapsed.TotalMilliseconds + queryMs;', 'double reuse = scoreMs + selectMs + rec.Elapsed.TotalMilliseconds + queryMs;', 'S8: reuse time without assembly'),
 ('F14', 'src/DotLLM.ChunkReuse/Corpus/FixedSizeChunker.cs', '            while (p < text.Length && text[p] != c && text[p] == StrippedOnEncode) p++;\n', '', 'S7: stripped markers not skipped (interior drift)'),
 ('F15', 'src/DotLLM.ChunkReuse/Corpus/FixedSizeChunker.cs', 'int endOffset = last ? file.Text.Length : Advance(file.Text, startOffset, text);', 'int endOffset = Advance(file.Text, startOffset, text);', 'S7: last chunk not extended to the end of the text'),
 ('F16', T+'ChunkCacheCli.cs', '            if (verbose && ex is not null) error.WriteLine(ex.ToString());\n', '', 'S9: --verbose prints no stack trace'),
 ('F17', T+'ChunkCacheCli.cs', '            if (verbose && ex is not null) error.WriteLine(ex.ToString());\n', '            if (ex is not null) error.WriteLine(ex.ToString());\n', 'S9: stack trace without --verbose'),
]

def sh(cmd, timeout=1800):
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout, shell=True)
    return p.returncode, p.stdout + p.stderr

FILTER = 'FullyQualifiedName~ChunkCacheCliTests|FullyQualifiedName~FixedSizeChunker'

def run_tests():
    code, out = sh('dotnet build tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release -m:2 -v q -nologo')
    if code != 0:
        errs = sorted(set(l.split('[')[0].strip() for l in out.splitlines() if ' error ' in l))
        return 'BUILD-ERROR', errs[:3]
    code, out = sh(f'dotnet test tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release --no-build --filter "{FILTER}" --logger "console;verbosity=normal" --nologo')
    failed = re.findall(r'^\s+Failed (\S+)', out, re.M)
    total = re.search(r'Total tests: (\d+)', out)
    return ('PASS' if code == 0 else 'FAIL'), [f.split('.')[-1] for f in failed] + ([] if total else ['no total: ' + out[-300:]])

with open(log_path, 'a', encoding='utf-8') as log:
    def w(s):
        print(s, flush=True); log.write(s + '\n'); log.flush()
    w(f'== {time.strftime("%Y-%m-%d %H:%M:%S")} fix-round mutants in {root}')
    if not only or 'pristine' in only:
        r, f = run_tests(); w(f'pristine: {r} {f}')
    for mid, rel, old, new, desc in M:
        if only and mid not in only: continue
        path = os.path.join(root, rel)
        orig = open(path, encoding='utf-8', newline='').read()
        src = orig.replace('\r\n', '\n')
        if src.count(old) != 1:
            w(f'{mid} SKIP: pattern found {src.count(old)} times ({desc})'); continue
        mutated = src.replace(old, new)
        if '\r\n' in orig: mutated = mutated.replace('\n', '\r\n')
        open(path, 'w', encoding='utf-8', newline='').write(mutated)
        try:
            r, f = run_tests()
        finally:
            open(path, 'w', encoding='utf-8', newline='').write(orig)
        verdict = 'KILLED' if r == 'FAIL' else ('SURVIVED' if r == 'PASS' else r)
        w(f'{mid} {verdict}: {desc}; failing: {", ".join(f)}')
    r, f = run_tests(); w(f'pristine after: {r} {f}')
