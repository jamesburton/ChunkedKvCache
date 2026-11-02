# Task 7 mutants: run in a git-archive scratch copy of the worktree. Usage: python t7_mutants.py <copy-root> <log> [ids...]
import subprocess, sys, re, time, os

root = sys.argv[1]
log_path = sys.argv[2]
only = set(sys.argv[3:])
T = 'tools/DotLLM.ChunkCache/'
M = [
 ('M1', T+'BuildCommand.cs', 'List<ChunkRef> missing = status.Files.SelectMany(f => f.Missing).Where(r => seen.Add(r.KeyHex!)).ToList();',
        'List<ChunkRef> missing = diff.NeedsEncoding(layout.Store).ToList();', 'encoding driven by the diff, not Status'),
 ('M2', T+'BuildCommand.cs', 'using IDisposable? held = dryRun ? null : Common.Lock(ctx, storeRoot, lockTimeout);',
        'using IDisposable? held = null;', 'build takes no lock'),
 ('M3', T+'BuildCommand.cs', '            TestHookAfterIndexSave?.Invoke();',
        '            held?.Dispose();\n            TestHookAfterIndexSave?.Invoke();', 'build releases the lock after saving the index'),
 ('M4', T+'BuildCommand.cs', 'if (strict && tree.FailsStrict)', 'if (false && strict && tree.FailsStrict)', '--strict ignored'),
 ('M5', T+'SourceTree.cs', 'p.Reason != SkippedProject.ExtraTargetFramework', 'true', 'extra target framework fails --strict'),
 ('M6', T+'BuildCommand.cs', '        if (!dryRun)\n        {\n            index.Save(indexPath);', '        if (true)\n        {\n            index.Save(indexPath);', 'dry run saves the index'),
 ('M7', T+'BuildCommand.cs', 'missing = missing.Take(cap).ToList();', 'missing = missing.Take(cap + 1).ToList();', '--max-chunks off by one'),
 ('M8', T+'BuildCommand.cs', '&& !args.Flag("reroot"))', '&& false)', 'other root accepted silently'),
 ('M9', T+'BuildCommand.cs', 'missing = missing.Where(r => ids.Contains(r.Id)).ToList();', 'missing = missing.ToList();', 'selection does not restrict encoding'),
 ('M10', T+'ModelHandle.cs', 'bytes += 2L * Geometry.KvStrideOf(l) * sizeof(float);', 'bytes += 1L * Geometry.KvStrideOf(l) * sizeof(float);', 'estimate counts K only'),
 ('M11', T+'SourceTree.cs', 'if (ChunkIndex.PathComparer.Equals(a, b)) return projects;', 'return projects;', 'compilations not re-keyed when the root widens'),
 ('M12', T+'StoreLayout.cs', 'ChunkIndex.DefaultPath(Root, $"{chunker}.{producer[..12]}")', 'ChunkIndex.DefaultPath(Root, chunker)', 'one index per chunker (not per model)'),
 ('M13', T+'EvictCommand.cs', 'victims = ChunkIndex.StoreWideOrphans(store, storeRoot);',
        'victims = all.Where(k => !ChunkIndex.ReferencedKeysUnder(storeRoot, Directory.GetFiles(storeRoot, "index-*.json").OrderBy(f => File.GetLastWriteTimeUtc(f)).First()).Contains(k)).ToList();',
        'orphans ignore the oldest index'),
 ('M14', T+'EvictCommand.cs', '        if (apply)\n        {\n            if (dropIndexes.Count > 0)', '        if (true)\n        {\n            if (dropIndexes.Count > 0)', 'dry run deletes'),
 ('M15', T+'EvictCommand.cs', '&& fp == model.Fingerprint).OrderBy', ').OrderBy', '--all-for-model takes every entry'),
 ('M16', T+'EvictCommand.cs', '                foreach (string f in dropIndexes)\n                {', '                foreach (string f in Array.Empty<string>())\n                {', '--all-for-model keeps the index files'),
 ('M17', T+'EvictCommand.cs', 'using IDisposable? held = apply ? Common.Lock(ctx, storeRoot, lockTimeout) : null;', 'using IDisposable? held = null;', 'evict --apply takes no lock'),
 ('M18', T+'StatusCommand.cs', 'if (args.Flag("strict") && !report.IsUpToDate)', 'if (false)', 'status --strict never fails'),
 ('M19', T+'StatusCommand.cs', 'StatusReport report = index.Status(layout.Store, tree?.Files);', 'StatusReport report = index.Status(layout.Store, null);', 'status ignores the rescan'),
 ('M20', T+'SelectCommand.cs', 'bool? isStored = layout is null ? null : layout.Store.Contains(new ChunkKey(key));', 'bool? isStored = layout is null ? null : true;', 'select: stored always true'),
 ('M21', T+'SelectCommand.cs', 'IReadOnlyList<SelectedChunk> ordered = order == "rank" ? result.Selected : result.InDocumentOrder();', 'IReadOnlyList<SelectedChunk> ordered = result.InDocumentOrder();', 'select: --order rank ignored'),
 ('M22', T+'Common.cs', '"sha256:" + Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(text)))',
        '"sha256:" + Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.Unicode.GetBytes(text)))', 'wire hash over UTF-16'),
 ('M23', T+'CompareCommand.cs', 'double kl = Kl(p, q);', 'double kl = Kl(q, p);', 'KL direction swapped'),
 ('M24', T+'CompareCommand.cs', 'RecomputeOutcome rec = strategy.Recompute(model.Model, work, assembly.Entries, sel);', 'RecomputeOutcome rec = strategy.Recompute(model.Model, work, assembly.Entries, sel.Length > 0 ? [sel[0]] : sel);', 'recompute only the first selected position'),
 ('M25', T+'Recompute.cs', 'public void Put(ChunkKey key, ChunkKvEntry entry) => DroppedPuts++;', 'public void Put(ChunkKey key, ChunkKvEntry entry) => inner.Put(key, entry);', 'compare writes misses to the store'),
 ('M26', T+'CompareCommand.cs', '            CopyContext(stale, work, L);\n', '            if (work.CurrentLength == 0) CopyContext(stale, work, L);\n', 'arms reuse the previous arm\'s recomputed cache'),
 ('M27', T+'CliArgs.cs', 'list.AddRange(value.Split(\',\', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));', 'list.Add(value);', 'list options not split on commas'),
 ('M28', T+'ChunkCacheCli.cs', '            error.WriteLine(verb.Help);\n            return ExitCodes.Usage;', '            error.WriteLine(verb.Help);\n            return ExitCodes.Error;', 'usage errors exit 1'),
 ('M29', T+'ChunkCacheCli.cs', '            error.WriteLine($"error: store busy: {ex.Message}");\n            return ExitCodes.Error;', '            error.WriteLine($"error: store busy: {ex.Message}");\n            return ExitCodes.Usage;', 'busy lock exits 2'),
 ('M30', 'src/DotLLM.ChunkReuse/Store/FileChunkStore.cs', '            fingerprint = h.Fingerprint;\n', '            fingerprint = h.Fingerprint + "x";\n', 'header fingerprint misread'),
 ('M31', T+'BuildCommand.cs', 'if (!model.Tokenizer.EncodeRaw(Common.TextOf(file, r)).AsSpan().SequenceEqual(chunk.TokenIds)) ineligible++;', 'if (model.Tokenizer.EncodeRaw(Common.TextOf(file, r)).AsSpan().SequenceEqual(chunk.TokenIds)) ineligible++;', 'wire-eligibility inverted'),
 ('M32', T+'CliContext.cs', 'public string FullPath(string path) => Path.GetFullPath(Path.IsPathFullyQualified(path) ? path : Path.Combine(WorkingDirectory, path));', 'public string FullPath(string path) => Path.GetFullPath(path);', 'relative paths against the process directory'),
 ('M33', T+'CompareCommand.cs', 'ExactMatch = expected is null ? null : ExactMatch(armRows, expected, vocab),', 'ExactMatch = expected is null ? null : ExactMatch(refRows, expected, vocab),', 'arm exact match read from the reference rows'),
 ('M34', T+'SourceTree.cs', 'foreach (string d in scan.Diagnostics.Where(d => d.StartsWith("Failure", StringComparison.Ordinal)))', 'foreach (string d in Array.Empty<string>())', 'unattributed load failures do not fail --strict'),
 ('M35', T+'BuildCommand.cs', 'long header = 16 + 64 + 4 + model.Fingerprint.Length + 8 + 8L * model.Geometry.LayerCount + 8;', 'long header = 0;', 'estimate without headers'),
]

def sh(cmd, timeout=1800):
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout, shell=True)
    return p.returncode, p.stdout + p.stderr

def run_tests():
    code, out = sh('dotnet build tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release -m:2 -v q -nologo')
    if code != 0:
        errs = sorted(set(l.split('[')[0].strip() for l in out.splitlines() if ' error ' in l))
        return 'BUILD-ERROR', errs[:3]
    code, out = sh('dotnet test tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release --no-build --filter "FullyQualifiedName~ChunkCacheCliTests" --logger "console;verbosity=normal" --nologo')
    failed = re.findall(r'^\s+Failed (\S+)', out, re.M)
    total = re.search(r'Total tests: (\d+)', out)
    return ('PASS' if code == 0 else 'FAIL'), [f.split('.')[-1] for f in failed] + ([] if total else ['no total: ' + out[-300:]])

with open(log_path, 'a', encoding='utf-8') as log:
    def w(s):
        print(s, flush=True); log.write(s + '\n'); log.flush()
    w(f'== {time.strftime("%Y-%m-%d %H:%M:%S")} mutants in {root}')
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
