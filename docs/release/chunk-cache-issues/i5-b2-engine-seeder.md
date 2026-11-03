# Engine: `IPromptKvSeeder`, a per-request seam for seeded prompt K/V rows (draft)

> **Status: DRAFT, not filed.** Phase I5 Task B2 (plan `docs/superpowers/plans/2026-11-03-phase-i5-applied-reuse.md`), PR
> slice I5-2. Refs #1542 (umbrella). Our side files nothing and pushes nothing; the user decides when and whether it is
> filed. **The dotLLM session owns the engine (`TextGenerator`, prefix cache) and must review this diff** before the server
> applied path (B3) is merged on top.
> Branch: `feature/chunk-apply-seeder` in worktree `C:\Development\dotLLM\.claude\worktrees\chunk-seeder`, first cut
> from `origin/pr/chunkcache-lineage` `9188cfbc`; #1575 has since merged into `dev`, so the branch was rebased onto fork
> `origin/dev` `8221d6ce` (local only): the PR diff is B2 only. Commits: `c5ecf32b` (seam), `b1257b86` (review fixes).
> Squash with subject `... (#N)` once the issue number exists.
> Depends on: #1575 (merged). Does **not** depend on `DotLLM.ChunkReuse`.

## Title

Engine: let a request's prefill start from externally seeded K/V rows (`IPromptKvSeeder`), tagged approximate in the prefix cache

## Body

Chunk-level KV reuse (#1542) assembles a prompt's K/V from stored, position-independent chunk entries and recomputes a
selection of rows, then prefills the rest. The engine needs one seam for that: something supplied **per request** that
writes prompt rows after the prefix restore and before the prefill, with the lineage from #1575 applied so those rows can
never be restored by an exact request or counted as `cached_tokens`. This PR adds that seam and nothing else; the chunk
logic stays in the server / `DotLLM.ChunkReuse` (later PR).

- **API (experimental).** `DotLLM.Core.Attention.IPromptKvSeeder` (`AcceptsApproximatePrefix`; `Seed(model, cache,
  promptIds, restoredRows, ct) -> PromptSeedResult`), set through `InferenceOptions.KvSeeder` (null by default).
  `PromptSeedResult` is a record struct with init-only named properties holding only what the engine reads
  (`SeededRows`, `FirstApproxRow`, `ChunkRows`, `ChunkRowsRecomputed`, `FallbackReason`), so fields can be added later
  without breaking callers; seeder diagnostics stay on the seeder object. The seam, the option and the six timing fields
  are documented as experimental (XML docs + `KV_CACHE.md`; the repo has no `[Experimental]` convention). It lives in
  `DotLLM.Core` because `InferenceOptions` does and Core cannot reference Engine.
- **Maintainer choice.** The seeder is a behaviour object inside the `InferenceOptions` record (it takes part in equality
  and `with` copies). The LoRA adapter is a `Generate` parameter instead; if the maintainer prefers that form, the seeder
  becomes a `Generate` / `GenerateStreamingTokensAsync` parameter and the interface can move to `DotLLM.Engine`.
- **Where it runs.** `TextGenerator`, blocking and streaming, plain dense path with the `PrefixCache` (multi-entry LRU,
  not the trie) or no prefix cache. Ignored (never called) with a LoRA adapter, a recurrent model, the prefix trie, a draft model, a hybrid
  prefill strategy or an MTP decode, and by the batch scheduler (it never reads the field). Not called when the restore
  already covers the prompt.
- **Contract.** On entry `cache.CurrentLength == restoredRows`; on success `restoredRows <= SeededRows < promptLen` and
  `CurrentLength == SeededRows`; the generator prefills `[SeededRows, promptLen)` (always at least one token: the
  first-token logits come from the normal prefill).
- **Restore and counting.** `AcceptsApproximatePrefix` turns on `PrefixCache.FindMatch(..., allowApprox: true, ...)`.
  `InferenceTimings.CachedTokenCount` stays exact; approximate restored rows go to the new `ApproxPrefixTokens`. Inside
  the generator the old `cachedTokenCount` is split into "restored" (MTP / hybrid gating, prefill start) and "exact"
  (telemetry, timings); without a seeder they are equal.
- **Lineage.** The stored snapshot is approximate from `min(restored entry's first approximate row, FirstApproxRow ??
  restoredRows)` (#1575 caller contract). Setting `FirstApproxRow` is the seeder's promise that the seeded rows below
  it are exact (the engine cannot check it). Before seeding into a restored cache, its prefix-cache entry is narrowed to the
  restored rows, so a failed or cancelled request cannot leave a snapshot claiming rows the seeder overwrote.
- **Fallback.** An exception (reported as `seeder_exception:<Type>`, never the message), a `FallbackReason`, or a result
  that breaks the contract (`invalid_seed_result`) rolls the cache back to the **exact** restored rows (approximate
  restored rows are dropped too, so the fallback equals the plain request) and the request runs as today; a cache that
  cannot roll back is replaced by a fresh one, after the old cache's entry is removed and disposed
  (`PrefixCache.Remove`), so the peak never holds two caches. Fatal exceptions (out of memory, access violation) are
  rethrown, not turned into a fallback. Cancellation propagates and is not a fallback. Reasons are codes only (`[A-Za-z0-9_.:-]{1,64}`,
  anything else becomes `seeder_fallback`).
- **KV dtype.** The engine never reads, copies or converts rows; the seeder writes through the cache's own write path
  (`Update`, a model forward, `IPositionedHostKvCache`), so the rows are in that cache's dtype (F32, F16, quantised).
  Nothing assumes F32 or `SupportsExactF32PrefixCopy`. Tested on the CPU quantised caches (Q8_0, Q4_0).
- **Timings.** `InferenceTimings` gains `ApproxPrefixTokens`, `SeededTokens`, `ChunkReusedTokens`,
  `ChunkRecomputedTokens`, `SeedMilliseconds` (not part of `PrefillTimeMs`), `SeedFallbackReason`, and
  `ComputedPromptTokenCount` (prompt minus exact cached, approximate restored and seeded rows). Prefill tok/s
  (`PrefillTokensPerSec`), the request timing log and the OTel `dotllm.engine.tokens.prefill` counter / rate now count
  computed rows only, so a seeded request does not report inflated prefill speed. Without a seeder nothing changes.
- **Follow-up for the server PR (B3), not in this PR.** The server's `timings.prompt_n` / `prompt_per_token_ms`
  (`ChatCompletionChunk.cs`, `TimingsDto.From`) use the same `PrefillTokenCount - CachedTokenCount` formula; B3 must
  switch them to `ComputedPromptTokenCount` and add `SeedMilliseconds` into `prompt_ms`.
- **Docs.** `docs/KV_CACHE.md`, new subsection "Seeded prompt rows: `IPromptKvSeeder`" under the lineage section.

Not in scope: the chunk assembler / planner / server path (I5-1, I5-3), the paged / trie / scheduler paths (applied reuse
on CPU requires `--no-paged`), Vulkan (I5-5).

**Review order for the engine owner.** `SeedPrompt` (fallback and entry narrowing), then the `restoredTokenCount` /
`cachedTokenCount` split in both generation paths, then `SeederFor` (eligibility).

## Acceptance criteria

- [ ] PR targets `dev`; `Refs #1542`; after #1575.
- [ ] `KvSeeder = null`: behaviour, tokens, counters and stored lineage unchanged (pinned by tests; existing Engine and
      Server unit suites green).
- [ ] Owning doc `docs/KV_CACHE.md` updated. No server flag, endpoint or DTO; no JSON context change.
- [ ] `tests/DotLLM.Tests.Unit/Engine/PromptKvSeederTests.cs` (deterministic random-weight dense qwen3 on the CPU).
- [ ] Correctness tests shown to fail against mutants (table below).

## Tests run (CPU, Release, `-m:2`, filter `FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU`)

- Red first: tests written before the API (8 compile errors); then the API skeleton with the generator not calling the
  seeder: 25 of 33 failed (the 8 passing are the no-seeder pins and the "not called" cases).
- `PromptKvSeederTests`: 37 / 37 pass (33 + review round: computed-token metric, cancellation after an approximate
  restore, out-of-memory rethrow; the fresh-cache test also asserts the entry count).
- Unit `DotLLM.Tests.Unit.Engine` + `Server` + `Telemetry` on the rebased branch: 2010 passed, 16 skipped, 0 failed;
  integration `PrefixTrieIntegration` + `PagedKvCacheIntegration` 11 / 11 (first round); `DotLLM.Cli` builds.
- The dtype tests seed into fresh caches only: a `QuantizedKvCache` is never a prefix-cache hit today
  (`ResolveKvCache` treats it as a miss), so restore plus quantised rollback is unreachable.

## Mutant evidence

`git archive` copy of `b1257b86` (review fix round, on fork `origin/dev`), filter
`PromptKvSeederTests|PrefixLineage|Engine.PromptCache|Engine.TextGenerator` (213 tests, baseline green). **29 / 29 killed**
(first round on `aceaf8ac`: 24 / 25, M22 survived; killed now by a dedicated test) (log
`.superpowers/sdd/2026-11-01-phase-s/i5-b2-mutants.log`, script `i5-b2-mutate.py`). Test-class prefix omitted.

| mutant | change | killed by |
|---|---|---|
| M1 | approximate restore for any seeder (opt-in ignored) | `ApproxRows_NotRestored_ForSeederWithoutOptIn` |
| M2 | approximate restore for every request | `Exact_AfterBalanced_SameSlot_RestoresExactRowsOnly`, `ApproxRows_NotRestored_ForSeederWithoutOptIn` |
| M3 | `firstApproxRow` dropped from `PrefixCache.Store` | 7 tests (`Exact_AfterBalanced_*`, `Seeder_StoresFirstApproxRowInPrefixCache`, …) |
| M4 | fallback keeps approximate restored rows | `Fallback_AfterApproxRestore_TruncatesToExactRows` |
| M5 | fallback leaves the seeded length (no rollback) | `Seeder_Throws_*`, `Seeder_FallbackReason_TruncatesToRestored`, `InvalidSeedResult_*`, `Fallback_AfterApproxRestore_*` |
| M6 | `cached_tokens` = restored rows | `CachedTokens_CountExactRowsOnly_WhenApproxRestored`, `Fallback_AfterApproxRestore_*` |
| M7–M12 | seeder not ignored on MTP / trie / adapter / draft / hybrid / recurrent | `SeederIgnored_WhenMtpWouldRun`, `SeederNotCalled_OnHybridMtpDraftAdapterPaths` (one case each) |
| M13 | seeded rows stored exact | 7 tests (lineage) |
| M14 | null `FirstApproxRow` = all exact | `Seeder_WithoutFirstApproxRow_TagsEverySeededRow` |
| M15 | restored approximate lineage not carried forward | `CachedTokens_CountExactRowsOnly_WhenApproxRestored` |
| M16 | restored entry not narrowed before seeding | `Seeder_Cancelled_Propagates_AndLeavesNoStaleRows` |
| M17 | exception message in the reason | `Seeder_Throws_FallsBackToPlainPrefill_SameTokens` |
| M18 | free-text reason passed through | `Seeder_FallbackReason_WithFreeText_IsNotPassedThrough` |
| M19 | seed result not validated | `InvalidSeedResult_FallsBackToPlainPrefill` (4 cases) |
| M20 | prefill ignores the seeded rows | `Seeder_PrefillStartsAtSeededRows`, `Seeder_IsKvDtypeAgnostic_*`, `Exact_AfterBalanced_*` |
| M21 | no fresh cache when rollback is impossible | `Fallback_WhenCacheCannotReturnToExactRows_UsesFreshCache` |
| M22 | cancellation swallowed into the fallback (entry narrowed to the exact rows E instead of the restored R) | `Seeder_CancelledAfterApproxRestore_KeepsRestoredRows_ForLaterOptedInRequest` |
| M23 | streaming path does not seed | 4 streaming tests |
| M24 | blocking path does not seed | 15 tests |
| M25 | seam refuses non-F32 caches | `Seeder_IsKvDtypeAgnostic_QuantizedCache_*` (Q8_0, Q4_0) |
| M26 | computed prompt tokens include seeded / approximate rows (tok/s, timing log) | `Seeder_PrefillStartsAtSeededRows`, `CachedTokens_CountExactRowsOnly_WhenApproxRestored` |
| M27 | OTel prefill-token counter counts seeded rows | `Seeder_PrefillTokenMetric_CountsComputedRowsOnly` |
| M28 | fresh-cache fallback keeps the dead entry (`Store([])` instead of `Remove`) | `Fallback_WhenCacheCannotReturnToExactRows_UsesFreshCache` |
| M29 | fatal exceptions swallowed into the fallback | `Seeder_OutOfMemory_IsNotSwallowed` |

M22–M24 first ran as constant-condition mutants that did not compile (CS0162 / CS8359, warnings as errors); they were
re-run in non-constant form and the table shows those results.
