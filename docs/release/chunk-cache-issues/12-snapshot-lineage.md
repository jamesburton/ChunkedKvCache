# Prefix cache: snapshot lineage, exact vs approximate rows (draft)

> **Status: DRAFT, not filed.** Plan Task 12 (spec L7, blocking item B2), umbrella row 3. Refs #1542 (umbrella). Our
> side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed. It is its own issue
> (prefix cache, owned by the dotLLM session, which reviews this diff before it is merged into the server branch).
> Branch: `feature/chunk-cache-lineage` (off fork `origin/dev` at `857c55b9`), worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-server-lineage`. Commits `69ca538d`, `918bb68d`, review fix round `3b594dc2`.

## Title

Prefix cache: tag snapshot lineage (exact / approximate rows) so exact requests never restore approximate K/V

## Body

Chunk-level KV reuse (#1542) will put **approximate** K/V into a sequence: rows assembled from position-independent
chunk entries, or selectively recomputed. A prefix snapshot taken after such a request must not be restored by a later
`exact`, `shadow` or plain request, and its approximate rows must never be counted in
`usage.prompt_tokens_details.cached_tokens` / `timings.cache_n` (CodeSharp's cache-miss rule and Anthropic's cache
counts treat these as exact reads).

This PR adds the lineage to both KV prefix stores, additively. Nothing in the engine creates approximate rows yet, and
every existing caller uses the defaults, so behaviour is unchanged.

**Why it lands before anything creates approximate rows.** It is blocking item B2 of the chunk-cache spec: the
exact-counter invariant (exact / plain requests never restore approximate K/V, `cached_tokens` stays exact) has to be in
the prefix stores before any chunk path is allowed to write approximate K/V, so that the later producer PR (Phase I5,
applied reuse) cannot ship without it, and so the prefix-cache owner reviews the invariant on its own rather than buried
in a larger chunk-reuse diff.

- **Rule.** A snapshot is approximate from the first row whose K/V came from assembly or recompute; every later row
  attended to it, so it is approximate too. Rows before it are exact.
- **`PrefixCache` (live reuse, Step 54).** `PrefixCacheEntry.FirstApproxRow` (`int?`, `null` = all exact).
  `FindMatch(prompt)` caps the match at it (and picks the best entry by the capped length);
  `FindMatch(prompt, allowApprox, out approxRowsReused)` restores the full match **only when `allowApprox` is true**,
  reporting approximate rows separately (otherwise it is the capped exact lookup); on equal match length it prefers the
  entry with more exact rows. `Store(tokens, cache, firstApproxRow = null)` sets the tag; on the live-reuse path it replaces the old
  tag, so an exact recompute after an approximate snapshot is stored exact.
- **`PrefixTrie` / `PrefixTrieManager` (Step 37).** Nodes carry `IsApprox` under a salted child key, so an exact and an
  approximate node for the same tokens coexist as siblings. A block holding any approximate row is approximate.
  `Admit(prompt, maxSeqLen, allowApprox = false)`: an exact lookup never enters an approximate node; with
  `allowApprox` the walk prefers the exact child. `RecordCompletion(cache, tokens, firstApproxRow = null)` inserts
  blocks from the earlier of the first approximate block restored at admission and `firstApproxRow / BlockSize` as
  approximate (lineage propagates without the caller tracking it). Named prefixes pin exact paths only.
- **Counting.** `PrefixAdmission.CachedTokens` and `PrefixTrie.HitTokens` count exact rows only;
  `PrefixAdmission.ApproxRowsReused` carries approximate restored rows (for `chunk_cache.tokens.prefix_reused_approx`);
  prefill starts at `PrefixAdmission.RestoredTokens`. With approximate restores `HitTokens + MissTokens` is below the
  prompt length (approximate rows are in neither).
- **Known limitations (for I5).** An approximate trie node is not upgraded in place (the exact recompute is linked beside
  it; the approximate one ages out by LRU). With `allowApprox` the trie walk is greedy exact-first and never backtracks,
  so it can stop on a shorter exact branch when the approximate sibling's subtree is longer (lost reuse, not a
  correctness issue).
- **Docs.** `docs/KV_CACHE.md` gains "Snapshot lineage: exact vs approximate rows (chunk-cache L7)" under the Step 37
  prefix-sharing section.
- **API note for the PR body.** `PrefixTrie.Lookup` / `Insert` and `PrefixCache.FindMatch` gain overloads (binary
  compatible). `PrefixTrieManager.Admit` / `RecordCompletion` and `PrefixCache.Store` gain **optional parameters**: source
  compatible, but a binary break for already-compiled consumers of the public `PrefixTrieManager` (`MissingMethodException`
  until recompiled). Accepted pre-1.0; switch to overloads if the maintainer prefers.
- **Review order for the prefix-cache owner.** Start with the trie: salted sibling keys, the exact-first walk, and
  `AcquiredPrefix` carry-forward (mutant findings M6 / M10 below explain the design).

Not in scope: recurrent prefix snapshots (`RecurrentPrefixSnapshotCache`; chunk reuse rejects recurrent / hybrid
models with `chunk_model_unsupported`), and any caller that sets `allowApprox` (Phase I5, applied reuse).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Refs #1542`; `Closes #N` closed by hand.
- [ ] Owning doc `docs/KV_CACHE.md` updated in the same PR. No new server flag, endpoint or DTO (no
      `JsonSerializerContext` change; no source-gen guard needed).
- [ ] Flag-off / default identity: every existing caller passes no lineage and no `allowApprox`; existing PromptCache,
      scheduler and prefix-trie integration suites pass unchanged.
- [ ] `tests/DotLLM.Tests.Unit/Engine/PrefixLineageTests.cs` (24 test cases): `ExactLookup_StopsAtFirstApproxRow_*`,
      `ApproxAllowed_RestoresFullMatch_*`, `ApproxAllowed_PrefixCache_TieBreakPrefersMoreExactRows`,
      `CachedTokens_CountExactRowsOnly_*` (incl. lineage propagation through completion, exact recompute stored exact,
      seed-cap trim), `NamedPrefix_PinsExactPathOnly`, `NoApproxRows_BehaviourUnchanged_*`,
      `Eviction_PreservesLineageTag_*`.
- [ ] Correctness tests shown to fail against mutants, recorded below and in the PR body.

## Tests run (CPU, `DOTLLM_SKIP_VULKAN=1`, Release, `-m:2`)

- Red first: the new tests did not compile against `dev` (22 errors: `allowApprox`, `firstApproxRow`,
  `RestoredTokens`, `ApproxRowsReused` absent).
- `PrefixLineageTests`: 24 / 24 pass (the tie-break test failed first, before its one-line fix).
- Unit `DotLLM.Tests.Unit.Engine` + `Server.PromptCache`: 1086 passed, 3 skipped, 0 failed.
- Integration `PrefixTrieIntegration` + `PagedKvCacheIntegration`: 11 / 11 pass.

## Mutant evidence

Run in a `git archive` copy of `3b594dc2` (never the live worktree), `--filter
FullyQualifiedName~PrefixLineage|FullyQualifiedName~Engine.PromptCache`, Release, CPU, `DOTLLM_SKIP_VULKAN=1`.
Baseline passes. **15 / 15 killed.** (Prefix `PrefixLineageTests.` omitted.)

| mutant | change | killed by |
|---|---|---|
| M1 | `PrefixCacheEntry`: cap ignored (exact match runs past `FirstApproxRow`) | `ExactLookup_StopsAtFirstApproxRow_PrefixCache`, `..._PicksBestCappedEntry`, `CachedTokens_..._ExactRecomputeAfterApproxIsStoredExact_PrefixCache`, `Eviction_PreservesLineageTag_PrefixCache` |
| M2 | `PrefixTrie.Lookup`: cap ignored (exact lookup enters approximate nodes) | `ExactLookup_StopsAtFirstApproxRow_Trie`, `..._MidBlockRowTaintsItsBlock`, `..._LineagePropagatesThroughCompletion`, `..._LineagePropagatesWhenExactSiblingAppearsMidFlight`, `..._ExactRecomputeAfterApproxIsStoredExact_Trie`, `Eviction_PreservesLineageTag_Trie` |
| M3 | `PrefixTrieManager.Admit`: approximate rows counted in `CachedTokens` (`cache_n`) | `ApproxAllowed_RestoresFullMatch_Trie`, `..._Trie_HitTokensExactOnly`, both propagation tests, `Eviction_PreservesLineageTag_Trie` |
| M4 | `PrefixTrie.HitTokens` counts approximate rows | `CachedTokens_CountExactRowsOnly_Trie_HitTokensExactOnly` |
| M5 | `PrefixCache.FindMatch`: approximate rows not reported (counted as cached) | `ApproxAllowed_RestoresFullMatch_PrefixCache`, `CachedTokens_CountExactRowsOnly_PrefixCache`, `Eviction_PreservesLineageTag_PrefixCache` |
| M6 | `RecordCompletion`: lineage of approximate blocks restored at admission not propagated | `CachedTokens_CountExactRowsOnly_Trie_LineagePropagatesWhenExactSiblingAppearsMidFlight` |
| M7 | `RecordCompletion`: mid-block first approximate row rounds up (its block treated exact) | `ExactLookup_StopsAtFirstApproxRow_Trie_MidBlockRowTaintsItsBlock` |
| M8 | `PrefixCache.Store` live-reuse path keeps the old tag | `CachedTokens_..._ExactRecomputeAfterApproxIsStoredExact_PrefixCache` |
| M9 | `PrefixCache.Store` new entry drops the tag | 5 PrefixCache tests (`ExactLookup_*`, `ApproxAllowed_*`, `CachedTokens_*`, `Eviction_*`) |
| M10 | `PrefixTrie`: approximate key salt 0 (exact and approximate siblings collide; approximate node orphaned) | `CachedTokens_..._ExactRecomputeAfterApproxIsStoredExact_Trie` (drain-to-empty assertion) |
| M11 | `PrefixTrie.Insert` ignores `firstApproxBlock` (all blocks inserted exact) | 8 trie tests |
| M12 | `PrefixCache.FindMatch` picks the entry by the uncapped match, then caps | `ExactLookup_StopsAtFirstApproxRow_PrefixCache_PicksBestCappedEntry` |
| M13 | `PrefixCache.FindMatch`: no exact-rows tie-break (with `allowApprox`) | `ApproxAllowed_PrefixCache_TieBreakPrefersMoreExactRows` |
| M14 | `PrefixTrieManager` seed-cap trim: exact count not trimmed (`Math.Min(exactTokens, cachedTokens)` removed) | `CachedTokens_CountExactRowsOnly_Trie_SeedCapTrim` |
| M15 | `RegisterNamedPrefix` walks approximate children too | `NamedPrefix_PinsExactPathOnly` |

First run (on `69ca538d`, 15 tests): M6 and M10 survived. M6 is unobservable unless an exact sibling of the restored
approximate blocks is linked between admission and completion (the insert walk then follows the exact path); M10 only
leaks the orphaned approximate node. Both became tests in `918bb68d`.

Not targeted by a mutant: the `IsApprox` checks in `FindChild` / the insert dedup (redundant with the salted key except on
a 64-bit hash collision, so an equivalent mutant without a forced collision). Review fix round (`3b594dc2`) added M13-M15 with
their tests; M1-M12 rerun on the same commit, all still killed.

**PR cut re-run (2026-11-03, PR split Task 2):** branch `pr/chunkcache-lineage` (`94d2fcd3`, the 3 commits rebased onto
`origin/dev` `29567637`), archive copy, same filter and script: baseline passes, **M1-M15 15 / 15 killed by the same
tests** (log `.superpowers/sdd/2026-11-01-phase-s/pr-split-pr1-lineage-mutants.log`). PR body draft:
`pr-bodies/PR-01-lineage.md`.
