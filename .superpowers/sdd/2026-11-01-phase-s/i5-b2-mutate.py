"""Mutation run for Task I5-B2 (engine IPromptKvSeeder). Runs in a git-archive copy, never the live worktree.

usage: python -I mutate.py <repo-copy> <log>
"""
import subprocess, sys, re, time, pathlib

repo = pathlib.Path(sys.argv[1])
log = open(sys.argv[2], 'a', encoding='utf-8')
TG = repo / 'src/DotLLM.Engine/TextGenerator.cs'
FILTER = ('(FullyQualifiedName~PromptKvSeederTests|FullyQualifiedName~PrefixLineage|FullyQualifiedName~Engine.PromptCache'
          '|FullyQualifiedName~Engine.TextGenerator)&FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU')

# (id, description, old, new, occurrence) occurrence: 'all' or 0-based index
MUTANTS = [
    ('M1', 'approximate restore without the seeder opt-in (any seeder)',
     'allowApprox: seeder?.AcceptsApproximatePrefix == true', 'allowApprox: seeder is not null', 'all'),
    ('M2', 'approximate restore for every request (no opt-in at all)',
     'allowApprox: seeder?.AcceptsApproximatePrefix == true', 'allowApprox: true', 'all'),
    ('M3', 'firstApproxRow dropped from PrefixCache.Store',
     '_prefixCache.Store(fullSequence, kvCache, _requestSeed.FirstApproxRow);', '_prefixCache.Store(fullSequence, kvCache);', 0),
    ('M4', 'fallback truncates to the restored rows (approximate restored rows kept)',
     'if (kvCache.CurrentLength >= exactRows && TryRollback(kvCache, exactRows))',
     'if (kvCache.CurrentLength >= restoredRows && TryRollback(kvCache, exactRows = restoredRows))', 0),
    ('M5', 'fallback leaves the seeded length (no rollback, prefill from the current length)',
     'if (kvCache.CurrentLength >= exactRows && TryRollback(kvCache, exactRows))\r\n        {\r\n            if (entryBacked)\r\n                _prefixCache!.Store(promptIds[..exactRows], kvCache);\r\n            return (kvCache, ownsKvCache, exactRows, exactRows);',
     'if (kvCache.CurrentLength >= exactRows)\r\n        {\r\n            return (kvCache, ownsKvCache, Math.Min(kvCache.CurrentLength, promptLen - 1), exactRows);', 0),
    ('M6', 'cached_tokens = restored rows (approximate counted)',
     'exactCachedTokens = resolved.CachedTokenCount - approxRows;', 'exactCachedTokens = resolved.CachedTokenCount;', 0),
    ('M7', 'seeder not ignored on the MTP path', '\r\n           && !ShouldUseMtp(captureLogprobs)', '', 0),
    ('M8', 'seeder not ignored on the prefix-trie path', '\r\n           && _prefixTrieManager is null', '', 0),
    ('M9', 'seeder not ignored with a LoRA adapter', '\r\n           && adapter is null', '', 0),
    ('M10', 'seeder not ignored with a draft model', '\r\n           && _draftModel is null', '', 0),
    ('M11', 'seeder not ignored with a hybrid strategy', '\r\n           && _hybridStrategy is null', '', 0),
    ('M12', 'seeder not ignored for a recurrent model', '\r\n           && !_model.RequiresPerSequenceState', '', 0),
    ('M13', 'seeded rows stored exact (tag at SeededRows)',
     'int seededApproxFrom = result.FirstApproxRow ?? restoredRows;', 'int seededApproxFrom = result.SeededRows;', 0),
    ('M14', 'null FirstApproxRow treated as all-exact',
     'int seededApproxFrom = result.FirstApproxRow ?? restoredRows;', 'int seededApproxFrom = result.FirstApproxRow ?? result.SeededRows;', 0),
    ('M15', 'restored approximate lineage not carried forward',
     '_requestSeed.FirstApproxRow = restoredApproxFrom;\r\n        _requestSeed.ApproxPrefixTokens', '_requestSeed.FirstApproxRow = null;\r\n        _requestSeed.ApproxPrefixTokens', 0),
    ('M16', 'restored entry not narrowed before seeding',
     '            _prefixCache!.Store(promptIds[..restoredRows], kvCache, restoredApproxFrom);\r\n', '', 0),
    ('M17', 'exception message (may quote prompt) in the fallback reason',
     '"seeder_exception:" + ex.GetType().Name', '"seeder_exception:" + ex.Message', 0),
    ('M18', 'free-text seeder reason passed through',
     'IsReasonCode(reason) ? reason : "seeder_fallback"', 'reason', 0),
    ('M19', 'seed result not validated',
     'if (result.SeededRows < restoredRows || result.SeededRows >= promptLen || cacheLength != result.SeededRows)\r\n            return "invalid_seed_result";\r\n        if (result.FirstApproxRow is int first && (first < restoredRows || first >= result.SeededRows))\r\n            return "invalid_seed_result";\r\n', '', 0),
    ('M20', 'prefill ignores the seeded rows (starts at the restored rows)',
     'return (kvCache, ownsKvCache, result.SeededRows, exactRows);', 'return (kvCache, ownsKvCache, restoredRows, exactRows);', 0),
    ('M21', 'no fresh cache when the rollback is impossible',
     'int maxLength = kvCache.MaxLength;', 'if (exactRows >= 0) return (kvCache, ownsKvCache, exactRows, exactRows);\r\n        int maxLength = kvCache.MaxLength;', 0),
    ('M22', 'cancellation swallowed into the fallback',
     'catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)', 'catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested && promptLen < 0)', 0),
    ('M23', 'streaming path does not seed', 'if (seeder is not null)\r\n            {', 'if (seeder is not null && promptLen < 0)\r\n            {', 0),
    ('M24', 'blocking path does not seed', 'if (seeder is not null)\r\n                (kvCache', 'if (seeder is not null && promptLen < 0)\r\n                (kvCache', 0),
    ('M26', 'S1: computed prompt tokens include seeded/approximate rows (timings, log)',
     'Math.Max(0, PrefillTokenCount - CachedTokenCount - ApproxPrefixTokens - SeededTokens)', 'Math.Max(0, PrefillTokenCount - CachedTokenCount)', 0,
     'src/DotLLM.Engine/InferenceTimings.cs'),
    ('M27', 'S1: OTel prefill-token metric counts seeded rows',
     'promptTokens - skippedPromptTokens, cachedTokens', 'promptTokens, cachedTokens', 0, 'src/DotLLM.Engine/TelemetryRecorder.cs'),
    ('M28', 'S3: fresh-cache fallback keeps the dead entry (Store([]) instead of Remove)',
     'if (!entryBacked || !_prefixCache!.Remove(kvCache))\r\n            kvCache.Dispose();',
     'if (entryBacked) _prefixCache!.Store([], kvCache);\r\n        else kvCache.Dispose();', 0),
    ('M29', 'nit: fatal exceptions swallowed into the fallback',
     'catch (Exception ex) when (!IsFatal(ex))\r\n        {\r\n            // The type only',
     'catch (Exception ex)\r\n        {\r\n            // The type only', 0),
    ('M25', 'seam assumes an F32 SimpleKvCache (other dtypes refused)',
     'int promptLen = promptIds.Length;\r\n        int? restoredApproxFrom',
     'int promptLen = promptIds.Length;\r\n        if (kvCache is not KvCache.SimpleKvCache) return (kvCache, ownsKvCache, restoredRows, exactRows);\r\n        int? restoredApproxFrom', 0),
]


def run(cmd):
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding='utf-8', errors='replace')


def test():
    r = run(['dotnet', 'test', 'tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj', '-c', 'Release', '-m:2', '-nologo',
             '--filter', FILTER])
    out = r.stdout + r.stderr
    failed = sorted(set(re.findall(r'^\s+Failed (DotLLM\.\S+?)(?:\(| \[)', out, re.M)))
    summary = [l for l in out.splitlines() if 'Passed!' in l or 'Failed!' in l or 'error CS' in l][:5]
    return r.returncode, failed, summary


MUTANTS = [m if len(m) == 6 else m + ('src/DotLLM.Engine/TextGenerator.cs',) for m in MUTANTS]
originals = {}


def source(rel):
    if rel not in originals:
        originals[rel] = (repo / rel).read_bytes().decode('utf-8')
    return originals[rel]


def fit(text, pat):
    return pat if '\r\n' in text else pat.replace('\r\n', '\n')


only = set(sys.argv[3:])
if not only:
    rc, failed, summary = test()
    log.write(f'BASELINE rc={rc} failed={failed} {summary}\n'); log.flush()
for mid, desc, old, new, occ, rel in MUTANTS:
    if only and mid not in only:
        continue
    path = repo / rel
    original = source(rel)
    old, new = fit(original, old), fit(original, new)
    if original.count(old) == 0:
        log.write(f'{mid} NOT APPLIED (pattern missing): {desc}\n'); log.flush(); continue
    if occ == 'all':
        mutated = original.replace(old, new)
    else:
        idx = -1
        for _ in range(occ + 1):
            idx = original.index(old, idx + 1)
        mutated = original[:idx] + new + original[idx + len(old):]
    path.write_bytes(mutated.encode('utf-8'))
    t0 = time.time()
    try:
        rc, failed, summary = test()
    finally:
        path.write_bytes(original.encode('utf-8'))
    status = 'KILLED' if failed else ('COMPILE-ERROR (invalid)' if rc != 0 else 'SURVIVED')
    short = [f.replace('DotLLM.Tests.Unit.Engine.', '') for f in failed]
    log.write(f'{mid} {status} ({time.time()-t0:.0f}s) {desc}\n    killed by: {short}\n    {summary}\n'); log.flush()
log.write('DONE\n')
