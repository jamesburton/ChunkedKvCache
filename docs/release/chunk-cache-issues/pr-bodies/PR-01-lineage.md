# PR 1 body draft: prefix cache snapshot lineage

> **DRAFT, not opened.** Branch `pr/chunkcache-lineage` (local, worktree
> `C:\Development\dotLLM\.claude\worktrees\pr-lineage`), 3 commits rebased onto `origin/dev` `29567637`. Issue: draft
> `../12-snapshot-lineage.md` (not filed yet; file it first and add its number to the title / `Refs`). Base: `dev`.

## Title

Prefix cache: tag snapshot lineage (exact / approximate rows) so exact requests never restore approximate K/V

## Body

Refs #1542 (umbrella: chunk-level KV reuse). Refs #1557 (snapshot lineage).

### Summary

Chunk-level KV reuse (#1542) will later put **approximate** K/V into a sequence (rows assembled from
position-independent chunk entries, or selectively recomputed). A prefix snapshot taken after such a request must never
be restored by a later exact / plain request, and its approximate rows must never be counted in
`usage.prompt_tokens_details.cached_tokens` / `timings.cache_n`.

This PR adds that lineage to both KV prefix stores, **additively**. Nothing in the engine creates approximate rows yet
and every existing caller uses the defaults, so behaviour is unchanged. It lands first so the exact-counter invariant
is in the prefix stores (and reviewed by the prefix-cache owner on its own) before any producer of approximate rows can
ship.

- **Rule.** A snapshot is approximate from the first row whose K/V came from assembly or recompute; every later row
  attended to it, so it is approximate too. Rows before it are exact.
- **`PrefixCache` (live reuse).** `PrefixCacheEntry.FirstApproxRow` (`int?`, `null` = all exact). The exact lookup caps
  the match at it and picks the best entry by the capped length; `FindMatch(prompt, allowApprox, out approxRowsReused)`
  restores the full match only when `allowApprox`, reporting approximate rows separately; on equal length it prefers
  the entry with more exact rows. `Store(tokens, cache, firstApproxRow)` replaces the tag on the live-reuse path, so an
  exact recompute after an approximate snapshot is stored exact.
- **`PrefixTrie` / `PrefixTrieManager`.** Nodes carry `IsApprox` under a salted child key, so exact and approximate
  nodes for the same tokens coexist as siblings; a block holding any approximate row is approximate. An exact lookup
  never enters an approximate node; with `allowApprox` the walk prefers the exact child. `RecordCompletion(...,
  firstApproxRow)` inserts from the earlier of the first approximate block restored at admission and
  `firstApproxRow / BlockSize` as approximate (lineage propagates without the caller tracking it). Named prefixes pin
  exact paths only.
- **Counting.** `PrefixAdmission.CachedTokens` and `PrefixTrie.HitTokens` count exact rows only;
  `PrefixAdmission.ApproxRowsReused` carries approximate restored rows; prefill starts at
  `PrefixAdmission.RestoredTokens`.
- **Known limitations (for the later applied-reuse PR).** An approximate trie node is not upgraded in place (the exact
  recompute is linked beside it; the approximate one ages out by LRU). With `allowApprox` the walk is greedy exact-first
  and never backtracks (lost reuse, not a correctness issue).
- **Not in scope:** recurrent prefix snapshots (chunk reuse rejects recurrent / hybrid models) and any caller that sets
  `allowApprox`.

**Review order suggestion:** start with the trie (salted sibling keys, the exact-first walk, `AcquiredPrefix`
carry-forward); mutants M6 / M10 below explain why those are designed as they are.

### Scope

`git diff --stat origin/dev` (6 files, +684 / -37):

```
 docs/KV_CACHE.md                                   |  39 ++
 src/DotLLM.Engine/PromptCache/PrefixCache.cs       |  37 +-
 src/DotLLM.Engine/PromptCache/PrefixCacheEntry.cs  |  26 +-
 src/DotLLM.Engine/PromptCache/PrefixTrie.cs        |  83 +++-
 src/DotLLM.Engine/PromptCache/PrefixTrieManager.cs |  67 ++-
 .../DotLLM.Tests.Unit/Engine/PrefixLineageTests.cs | 469 +++++++++++++++++++++
```

No new project, package, server flag, endpoint or DTO; no release-asset change.

### Public API note (binary compatibility)

- **Additive (binary compatible):** new overloads `PrefixTrie.Lookup(prompt, matchedBlocks, allowApprox, out
  exactTokens)` and `PrefixTrie.Insert(fullTokens, startTokenIndex, newBlocks, firstApproxBlock)`; new properties
  `PrefixAdmission.ApproxRowsReused`, `PrefixAdmission.RestoredTokens`.
- **Optional parameters added to existing public methods:** `PrefixTrieManager.Admit(prompt, maxSeqLen, allowApprox =
  false)` and `PrefixTrieManager.RecordCompletion(cache, fullTokens, firstApproxRow = null)`. Source compatible, but a
  **binary break** for already-compiled external consumers of `PrefixTrieManager` (`MissingMethodException` until
  recompiled). Accepted pre-1.0; happy to switch both to overloads if preferred.
- `PrefixCache.FindMatch` / `Store`, `PrefixCacheEntry`, `PrefixTrieNode` and the `PrefixAdmission` constructor are
  `internal`; their signature changes do not affect consumers.

### Tests (CPU, `DOTLLM_SKIP_VULKAN=1`, Release, `-m:2`, from the clean PR worktree)

| run | result |
|---|---|
| `dotnet build tests/DotLLM.Tests.Unit -c Release -m:2` | 0 errors |
| `--filter FullyQualifiedName~PrefixLineage` (new) | 24 passed, 0 failed |
| `--filter FullyQualifiedName~Prefix` | 243 passed, 25 skipped, 0 failed |
| `--filter "FullyQualifiedName~DotLLM.Tests.Unit.Engine\|FullyQualifiedName~Server.PromptCache"` | 1,086 passed, 3 skipped, 0 failed |
| Integration `PrefixTrieIntegration\|PagedKvCacheIntegration` | 11 passed, 0 failed |

Red first: the new tests did not compile against `dev` (22 errors: `allowApprox`, `firstApproxRow`, `RestoredTokens`,
`ApproxRowsReused` absent).

### Mutant evidence

Re-run on this exact cut (`git archive` of `pr/chunkcache-lineage` `94d2fcd3` into a throwaway copy, never the live
worktree), one mutant at a time, `--filter "FullyQualifiedName~PrefixLineage|FullyQualifiedName~Engine.PromptCache"`,
Release, CPU, `DOTLLM_SKIP_VULKAN=1`. Baseline passes. **15 / 15 killed**, each by the same tests as on the source
branch. (Test names omit the `PrefixLineageTests.` prefix.)

| mutant | change | killed by |
|---|---|---|
| M1 | `PrefixCacheEntry`: cap ignored (exact match runs past `FirstApproxRow`) | `ExactLookup_StopsAtFirstApproxRow_PrefixCache`, `..._PicksBestCappedEntry`, `CachedTokens_..._ExactRecomputeAfterApproxIsStoredExact_PrefixCache`, `Eviction_PreservesLineageTag_PrefixCache` |
| M2 | `PrefixTrie.Lookup`: cap ignored (exact lookup enters approximate nodes) | `ExactLookup_StopsAtFirstApproxRow_Trie`, `..._MidBlockRowTaintsItsBlock`, both lineage-propagation tests, `..._ExactRecomputeAfterApproxIsStoredExact_Trie`, `Eviction_PreservesLineageTag_Trie` |
| M3 | `PrefixTrieManager.Admit`: approximate rows counted in `CachedTokens` (`cache_n`) | `ApproxAllowed_RestoresFullMatch_Trie`, `..._Trie_HitTokensExactOnly`, both propagation tests, `..._SeedCapTrim`, `Eviction_PreservesLineageTag_Trie` |
| M4 | `PrefixTrie.HitTokens` counts approximate rows | `CachedTokens_CountExactRowsOnly_Trie_HitTokensExactOnly` |
| M5 | `PrefixCache.FindMatch`: approximate rows not reported (counted as cached) | `ApproxAllowed_RestoresFullMatch_PrefixCache`, `CachedTokens_CountExactRowsOnly_PrefixCache`, `Eviction_PreservesLineageTag_PrefixCache` |
| M6 | `RecordCompletion`: lineage of approximate blocks restored at admission not propagated | `CachedTokens_CountExactRowsOnly_Trie_LineagePropagatesWhenExactSiblingAppearsMidFlight` |
| M7 | `RecordCompletion`: mid-block first approximate row rounds up (its block treated exact) | `ExactLookup_StopsAtFirstApproxRow_Trie_MidBlockRowTaintsItsBlock` |
| M8 | `PrefixCache.Store` live-reuse path keeps the old tag | `CachedTokens_..._ExactRecomputeAfterApproxIsStoredExact_PrefixCache` |
| M9 | `PrefixCache.Store` new entry drops the tag | 6 PrefixCache tests (`ExactLookup_*`, `ApproxAllowed_*` incl. tie-break, `CachedTokens_*`, `Eviction_*`) |
| M10 | `PrefixTrie`: approximate key salt 0 (exact and approximate siblings collide; approximate node orphaned) | `CachedTokens_..._ExactRecomputeAfterApproxIsStoredExact_Trie` (drain-to-empty assertion) |
| M11 | `PrefixTrie.Insert` ignores `firstApproxBlock` (all blocks inserted exact) | 10 trie tests |
| M12 | `PrefixCache.FindMatch` picks the entry by the uncapped match, then caps | `ExactLookup_StopsAtFirstApproxRow_PrefixCache_PicksBestCappedEntry` |
| M13 | `PrefixCache.FindMatch`: no exact-rows tie-break (with `allowApprox`) | `ApproxAllowed_PrefixCache_TieBreakPrefersMoreExactRows` |
| M14 | `PrefixTrieManager` seed-cap trim: exact count not trimmed | `CachedTokens_CountExactRowsOnly_Trie_SeedCapTrim` |
| M15 | `RegisterNamedPrefix` walks approximate children too | `NamedPrefix_PinsExactPathOnly` |

History: on the first implementation M6 and M10 survived (M6 only shows when an exact sibling of the restored
approximate blocks is linked between admission and completion; M10 only leaks the orphaned approximate node); both
became tests in the second commit. Not targeted by a mutant: the `IsApprox` checks in `FindChild` / the insert dedup
(redundant with the salted key except on a 64-bit hash collision, so an equivalent mutant without a forced collision).

### Conventions checklist

- [x] Targets `dev`, not `main`. `Closes #N` does not auto-close on `dev`: the lineage issue is closed by hand after merge.
- [x] Owning doc updated in the same PR: `docs/KV_CACHE.md` gains "Snapshot lineage: exact vs approximate rows" under
      the Step 37 prefix-sharing section.
- [x] STJ source-gen DTO rule: n/a (no DTO, no `JsonSerializerContext` change, so no `JsonContextDefaultsTests` guard).
- [x] Correctness tests shown to fail against mutants (table above).
- [x] Flag-off / default identity: every existing caller passes no lineage and no `allowApprox`; the existing
      PromptCache, scheduler and prefix-trie integration suites pass unchanged (counts above).
- [x] No new server flag, project or package.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
