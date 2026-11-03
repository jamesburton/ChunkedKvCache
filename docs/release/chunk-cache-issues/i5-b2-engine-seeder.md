# Engine: `IPromptKvSeeder`, a per-request seam for seeded prompt K/V rows (draft)

> **Status: DRAFT, not filed.** Phase I5 Task B2 (plan `docs/superpowers/plans/2026-11-03-phase-i5-applied-reuse.md`), PR
> slice I5-2. Refs #1542 (umbrella). Our side files nothing and pushes nothing; the user decides when and whether it is
> filed. **The dotLLM session owns the engine (`TextGenerator`, prefix cache) and must review this diff** before the server
> applied path (B3) is merged on top.
> Branch: `feature/chunk-apply-seeder` in worktree `C:\Development\dotLLM\.claude\worktrees\chunk-seeder`, cut from
> `origin/pr/chunkcache-lineage` `9188cfbc` (PR #1575, the lineage change this builds on; fork `origin/dev` was 4 LFM3
> Vulkan commits ahead, not merged). Commit: `aceaf8ac`.
> Depends on: #1575 (snapshot lineage). Does **not** depend on `DotLLM.ChunkReuse`.

## Title

Engine: let a request's prefill start from externally seeded K/V rows (`IPromptKvSeeder`), tagged approximate in the prefix cache

## Body

Chunk-level KV reuse (#1542) assembles a prompt's K/V from stored, position-independent chunk entries and recomputes a
selection of rows, then prefills the rest. The engine needs one seam for that: something supplied **per request** that
writes prompt rows after the prefix restore and before the prefill, with the lineage from #1575 applied so those rows can
never be restored by an exact request or counted as `cached_tokens`. This PR adds that seam and nothing else; the chunk
logic stays in the server / `DotLLM.ChunkReuse` (later PR).

- **API.** `DotLLM.Core.Attention.IPromptKvSeeder` (`AcceptsApproximatePrefix`; `Seed(model, cache, promptIds,
  restoredRows, ct) -> PromptSeedResult(SeededRows, FirstApproxRow, ChunkRows, ChunkRowsRecomputed, AssemblyMs,
  RecomputeMs, Forwards, FallbackReason)`), set through `InferenceOptions.KvSeeder` (null by default). It lives in
  `DotLLM.Core` because `InferenceOptions` does and Core cannot reference Engine.
- **Where it runs.** `TextGenerator`, blocking and streaming, plain dense path with the single-slot `PrefixCache` or no
  prefix cache. Ignored (never called) with a LoRA adapter, a recurrent model, the prefix trie, a draft model, a hybrid
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
  restoredRows)` (#1575 caller contract). Before seeding into a restored cache, its prefix-cache entry is narrowed to the
  restored rows, so a failed or cancelled request cannot leave a snapshot claiming rows the seeder overwrote.
- **Fallback.** An exception (reported as `seeder_exception:<Type>`, never the message), a `FallbackReason`, or a result
  that breaks the contract (`invalid_seed_result`) rolls the cache back to the **exact** restored rows (approximate
  restored rows are dropped too, so the fallback equals the plain request) and the request runs as today; a cache that
  cannot roll back is replaced by a fresh one. Cancellation propagates. Reasons are codes only (`[A-Za-z0-9_.:-]{1,64}`,
  anything else becomes `seeder_fallback`).
- **KV dtype.** The engine never reads, copies or converts rows; the seeder writes through the cache's own write path
  (`Update`, a model forward, `IPositionedHostKvCache`), so the rows are in that cache's dtype (F32, F16, quantised).
  Nothing assumes F32 or `SupportsExactF32PrefixCopy`. Tested on the CPU quantised caches (Q8_0, Q4_0).
- **Timings.** `InferenceTimings` gains `ApproxPrefixTokens`, `SeededTokens`, `ChunkReusedTokens`,
  `ChunkRecomputedTokens`, `SeedMilliseconds` (not part of `PrefillTimeMs`), `SeedFallbackReason`.
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
- `PromptKvSeederTests`: 33 / 33 pass.
- Unit `DotLLM.Tests.Unit.Engine` + `DotLLM.Tests.Unit.Server`: 1976 passed, 16 skipped, 0 failed.

- Unit `DotLLM.Tests.Unit.Engine` + `DotLLM.Tests.Unit.Server` with the change: 1976 passed, 16 skipped, 0 failed;
  integration `PrefixTrieIntegration` + `PagedKvCacheIntegration` 11 / 11; `DotLLM.Cli` and the integration project build.

## Mutant evidence

`git archive` copy of `aceaf8ac`, filter `PromptKvSeederTests|PrefixLineage|Engine.PromptCache|Engine.TextGenerator`
(210 tests, baseline green). **24 / 25 killed, 1 equivalent survivor** (log
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
| M22 | cancellation swallowed into the fallback | **survived (equivalent)**: the fallback's prefill checks the same token before its first forward and throws, so the request still ends cancelled with the same cache state |
| M23 | streaming path does not seed | 4 streaming tests |
| M24 | blocking path does not seed | 15 tests |
| M25 | seam refuses non-F32 caches | `Seeder_IsKvDtypeAgnostic_QuantizedCache_*` (Q8_0, Q4_0) |

M22–M24 first ran as constant-condition mutants that did not compile (CS0162 / CS8359, warnings as errors); they were
re-run in non-constant form and the table shows those results.
