# Phase I5 Task B2 report: engine seam `IPromptKvSeeder` and lineage wiring

**Status: DONE_WITH_CONCERNS.** The concerns are rulings asked for below; nothing blocks B3.
**The dotLLM session (engine / prefix-cache owner) must review the diff before B3 merges on top.**

## Where

- dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-seeder`, new branch `feature/chunk-apply-seeder`.
- **Base:** `origin/pr/chunkcache-lineage` `9188cfbc` (PR #1575: the 3 lineage commits on fork `origin/dev` `8729ed2f`).
  The branch was cut after `git fetch origin`. Fork `origin/dev` (`83183f3f`) is 4 commits ahead (LFM3 Vulkan, #1562). I did
  not merge it: the commits are unrelated, and a merge commit would make the upstream PR diff noisier. No upstream tracking.
  Nothing pushed, no issue or PR filed. No other worktree touched.
- **Commit:** `aceaf8ac` "Engine: IPromptKvSeeder seam for seeded prompt K/V rows, with snapshot lineage wiring (chunk-cache
  applied reuse)". 6 files, src + docs ≈ +330 / −15, under the plan's 400-line target:
  - `src/DotLLM.Core/Attention/IPromptKvSeeder.cs` (new)
  - `src/DotLLM.Core/Configuration/InferenceOptions.cs` (`KvSeeder`)
  - `src/DotLLM.Engine/InferenceTimings.cs` (6 fields)
  - `src/DotLLM.Engine/TextGenerator.cs`
  - `docs/KV_CACHE.md`
  - test `tests/DotLLM.Tests.Unit/Engine/PromptKvSeederTests.cs` (33 cases)
- **Files in this repo:**
  - issue draft `docs/release/chunk-cache-issues/i5-b2-engine-seeder.md`
  - mutant log and script `.superpowers/sdd/2026-11-01-phase-s/i5-b2-mutants.log`, `i5-b2-mutate.py`
  - this report

  These are staged with an explicit `git add`, not committed.

## What was built

- `IPromptKvSeeder` { `AcceptsApproximatePrefix`; `Seed(IModel, IKvCache, ReadOnlySpan<int> promptIds, int restoredRows,
  CancellationToken)` } returns `PromptSeedResult(SeededRows, FirstApproxRow, ChunkRows, ChunkRowsRecomputed, AssemblyMs,
  RecomputeMs, Forwards, FallbackReason)` (+ `PromptSeedResult.Fallback(reason)`). The signature is the plan's.
- **Supply:** per request, through `InferenceOptions.KvSeeder` (null = unchanged). No dependency on `DotLLM.ChunkReuse`.
- **`TextGenerator`, both blocking and streaming:**
  - `SeederFor` decides eligibility. The seeder is ignored with an adapter, a recurrent model, the prefix trie, a draft model,
    a hybrid strategy or an MTP decode.
  - `ResolveKvCache` takes `allowApprox` (= the seeder's opt-in) and returns the exact count. The old `cachedTokenCount` is
    split into `restoredTokenCount` (MTP / hybrid gating, prefill start) and `cachedTokenCount` (exact, for telemetry and
    timings). Without a seeder the two are identical.
  - `SeedPrompt` runs at the top of the `try`, before the prefill. The seeder is not called when the restore already covers
    the prompt.
  - `StoreInPrefixCache` passes the per-request `FirstApproxRow`. Per-request state lives in a field that `ResolveKvCache`
    resets, like `LastPrefixCacheTier`; the generation gate serialises requests.
- **Lineage:** stored approximate from `min(restored approximate start, FirstApproxRow ?? restoredRows)` (Task 12 caller
  contract). `FirstApproxRow` must lie in `[restored, seeded)`.
- **Fallback:**
  - Triggers: an exception (reported as `seeder_exception:<Type>`, never the message), a `FallbackReason` (codes only, free
    text becomes `seeder_fallback`), or a contract break (`invalid_seed_result`). The contract checks are: seeded below
    restored, seeded ≥ prompt length, cache length ≠ seeded, approximate row out of range.
  - Action: roll back to the **exact** restored rows, then prefill plain. If the cache cannot roll back, use a fresh cache;
    the old prefix entry is neutered to an empty sequence, or the cache is disposed if no entry holds it.
  - Cancellation propagates.
- **Entry narrowing (beyond the plan):** before seeding into a restored cache, its `PrefixCache` entry is re-stored as
  `promptIds[..restored]`. Without this, a failed or cancelled request leaves the entry claiming its old token sequence over
  rows the seeder overwrote. Mutant M16 shows the hole.
- **Timings:** `ApproxPrefixTokens`, `SeededTokens`, `ChunkReusedTokens`, `ChunkRecomputedTokens`, `SeedMilliseconds` (not
  in `PrefillTimeMs`) and `SeedFallbackReason`.
- **KV dtype (James's direction, folded in):**
  - The engine never reads, copies or converts rows, and assumes neither F32 nor `SupportsExactF32PrefixCopy`. The seeder
    writes through the cache's own path (`Update`, a forward, or `IPositionedHostKvCache`), so rows are in that cache's dtype.
  - Documented on the interface and in KV_CACHE.md.
  - Tested on CPU `QuantizedKvCache` Q8_0 and Q4_0 (head-dim-32 variant of the model). Seeded output is bit-identical to
    plain on the same dtype.
  - Mutant M25 (seam refuses non-F32 caches) is killed.

## Tests

CPU only; Release; `-m:2`; filter `FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU`.

**Fixture.** The test file builds a deterministic random-weight dense qwen3 in memory (3 layers, GQA 4:2, head dim 16 and a
32 variant, RoPE base 100, F32). It does not reuse `SyntheticDenseGguf`: that file is in PR #1577, and the
`feature/chunk-cache` copy differs from it, so a same-path add would conflict.

The approximate stand-in is K/V forwarded from shifted tokens. `Exact_AfterBalanced` asserts as a precondition that it
changes the greedy output.

**Red evidence:**
1. Tests written first: 8 compile errors (`IPromptKvSeeder` and `PromptSeedResult` missing). Log: scratch
   `i5b2\red-compile.log`.
2. API skeleton with a generator that never calls the seeder: **25 / 33 failed**; the 8 passing were the no-seeder pins and
   the "not called" cases. Log: `i5b2\red-runtime.log`.

   The two dtype cases failed at that point for a fixture reason: Q8_0 needs 32-element rows. After the fix, their red is
   shown by mutants M20 and M25.

**Green:**
- `PromptKvSeederTests` **33 / 33**.
- Unit `DotLLM.Tests.Unit.Engine` + `DotLLM.Tests.Unit.Server`: **1976 passed, 16 skipped, 0 failed**. This includes
  `PrefixLineageTests` and the PromptCache, TextGenerator and scheduler suites.
- Integration `PrefixTrieIntegration` + `PagedKvCacheIntegration`: **11 / 11**.
- `DotLLM.Cli` and the integration project build clean.

Plan test names are covered as follows:

| Plan name | Test(s) |
|---|---|
| `NoSeeder_BehaviourAndTokensUnchanged` | Same name, blocking + streaming. Covers tokens, `cached_tokens`, prefill start, zero new timings, all-exact stored lineage. |
| `Seeder_PrefillStartsAtSeededRows` | Same name, × prefix cache on/off × stream. |
| `Seeder_Throws_FallsBackToPlainPrefill_SameTokens` | Same name. |
| `Seeder_FallbackReason_TruncatesToRestored` | Same name. |
| `Seeder_StoresFirstApproxRowInPrefixCache` | Same name, plus `Seeder_WithoutFirstApproxRow_TagsEverySeededRow`. |
| `Exact_AfterBalanced_SameSlot_RestoresExactRowsOnly` | Same name, both paths. |
| `CachedTokens_CountExactRowsOnly_WhenApproxRestored` | Same name, plus `ApproxRows_NotRestored_ForSeederWithoutOptIn` and `Fallback_AfterApproxRestore_TruncatesToExactRows`. |
| `SeederNotCalled_OnHybridMtpDraftAdapterPaths` | Same name, end to end for draft, adapter, trie, recurrent and hybrid. MTP is covered by `SeederIgnored_WhenMtpWouldRun` against the internal `SeederFor`, because no CPU MTP fixture is cheap. |
| `Streaming_And_Blocking_BothCallSeeder` | Same name. |

Additional tests:
- `InvalidSeedResult_FallsBackToPlainPrefill` (4 cases)
- `Fallback_WhenCacheCannotReturnToExactRows_UsesFreshCache`
- `Seeder_Cancelled_Propagates_AndLeavesNoStaleRows`
- `Seeder_FallbackReason_WithFreeText_IsNotPassedThrough`
- `Seeder_NotCalled_WhenPromptFullyRestored`
- `Seeder_IsKvDtypeAgnostic_QuantizedCache_SameTokensAsPlainOnSameDtype` (Q8_0, Q4_0)

**Bounded work.** Every seeding test asserts that the seeder is called exactly once per request, with no retry, and that the
fallback never re-calls it. The engine does no seeder work of its own. **No text logging:** the engine logs nothing about the
seeder, and reasons are codes.

## Mutants

Run in a `git archive` copy of `aceaf8ac` in scratch `i5b2\repo`. Filter
`PromptKvSeederTests|PrefixLineage|Engine.PromptCache|Engine.TextGenerator`: 210 tests, green baseline.

**Result: 24 / 25 killed, 1 equivalent survivor.** The full table with killing tests is in the issue draft. The four plan
mutants are all killed:
- M1 / M2: approximate restore without the opt-in.
- M3: `firstApproxRow` dropped.
- M5 (plus M4): the fallback leaves the seeded length, or keeps the approximate rows.
- M6: `cached_tokens` = restored.

The others are killed too:
- M7–M12: eligibility, one per path.
- M13–M15: lineage.
- M16: entry narrowing.
- M17 / M18: no text in reasons.
- M19: result validation.
- M20: prefill start.
- M21: fresh-cache path.
- M23 / M24: streaming / blocking.
- M25: dtype.

**Survivor M22** (the explicit `OperationCanceledException` catch removed, so cancellation goes into the fallback) is
equivalent: the fallback's `ForwardPrefill` checks the same token before its first forward and throws, which leaves the same
outcome and cache state. The explicit catch avoids pointless fallback work.

**Run note:** M22–M24 first ran as constant-condition mutants that did not compile (CS0162 / CS8359, warnings as errors). The
harness had counted those as kills. I re-ran them in non-constant form, and the log records both runs.

## Deviations from the plan

1. `IPromptKvSeeder` / `PromptSeedResult` live in **`DotLLM.Core.Attention`**, not `DotLLM.Engine/PromptCache`: the per-request
   carrier `InferenceOptions` is in Core, and Core cannot reference Engine. They are still independent of ChunkReuse.
2. **Fallback truncates to the exact restored rows E, not to `restoredRows` R** as the plan's contract text says. If
   approximate rows were restored (R > E), keeping them would make the "plain" fallback depend on approximate K/V and differ
   from the plain request while reporting `exact`. Pinned by `Fallback_AfterApproxRestore_TruncatesToExactRows` and M4.
3. **Entry narrowing before seeding** (above): not in the plan; it closes a stale-snapshot hole that the seeder makes
   reachable with approximate data.
4. Extra timings fields beyond the plan's four: `SeededTokens` and `SeedFallbackReason`. The latter lets the server report the
   engine's own fallbacks (an exception it did not see, `invalid_seed_result`).
5. The seeder is also refused on the **prefix-trie** path (paged shared blocks: a mid-block write would land in a block the
   trie may share). This is consistent with decision 2 (`--no-paged`). The scheduler never reads `KvSeeder`; there is no
   scheduler test for that.
6. Not merged into `feature/chunk-cache-apply` (B0's branch). The brief asked for a standalone branch for the upstream PR;
   the merge into the integration branch is the controller's step.

## Concerns / questions for rulings

1. **`FirstApproxRow` trust.** Rows `[restored, FirstApproxRow)` are stored **exact** on the seeder's word, for example holes
   before the first placement recomputed over exact predecessors. The default (null) tags every seeded row approximate. The
   alternative is that the engine always tags from `restoredRows` and ignores the claim, which is safer but loses exact reuse
   of leading glue. Recommendation: keep it as built; B3's seeder should pass the first placed or recomputed-with-approximate
   row.
2. **`SeedMilliseconds` is outside `PrefillTimeMs`.** The server's `timings.prompt_ms` will under-report applied-reuse TTFT
   unless B3 adds them. Should the engine fold seed time into `PrefillTimeMs` instead? Recommendation: keep them separate in
   the engine; B3 reports `prompt_ms = seed + prefill`, and `timings_ms{assembly, recompute, prefill}` come from the seeder's
   own figures.
3. **Pre-existing engine hazard (not fixed here, upstream-issue candidate).** For a plain request that fails or is cancelled
   mid-prefill after a `PrefixCache` hit, the entry keeps claiming its old token sequence while rows past the match were
   overwritten. A later prompt that matches the old sequence restores wrong rows. A fresh cache allocated on a miss with a
   prefix cache present (`ownsKvCache = false`) also leaks on an exception, because it is never disposed. The seeder path is
   protected (entry narrowing); the plain path is unchanged, as required.
4. **API shape.** `InferenceOptions` is a record, so `KvSeeder` takes part in record equality (by reference). That is
   harmless, but the engine owner may prefer a `Generate` overload. The private `ResolveKvCache` gained `out` / optional
   parameters; there is no public API break apart from the additive members.
5. **Fork `origin/dev` is 4 commits ahead of the base.** The upstream PR will need a rebase onto `dev` after #1575 lands.

## Fix round (review `review-i5-b2-report.md`: ACCEPT, 4 should-fix): commit `b1257b86`

**Status after the fix round: DONE.**

**Rebase.** I fetched, then ran `git rebase --onto origin/dev 9188cfbc` locally. #1575 is on `dev`, so the branch is now on
fork `origin/dev` `8221d6ce`: `c5ecf32b` (seam, was `aceaf8ac`) and `b1257b86` (fixes). The PR diff is B2 only. Nothing was
pushed. The fix commit carries `Refs #1542 (#N)`; squash with an `(#N)` subject once the issue exists.

**Should-fixes:**

- **S1.** New `InferenceTimings.ComputedPromptTokenCount` = prompt − exact cached − approximate restored − seeded. It feeds
  `PrefillTokensPerSec`, the `RequestTimingLog` line and the OTel prefill-token counter and rate. For OTel,
  `TelemetryRecorder.Complete` subtracts the skipped rows; there is no public Telemetry API change.
  - Tests: assertions in `Seeder_PrefillStartsAtSeededRows` and `CachedTokens_*`, and a `MeterListener` test
    `Seeder_PrefillTokenMetric_CountsComputedRowsOnly`.
  - B3 follow-up is listed in the issue draft: the server's `prompt_n` / `prompt_per_token_ms` use the same formula, and
    `prompt_ms` needs `SeedMilliseconds` added.
- **S2.** `PromptSeedResult` is now a record struct with init-only named properties holding only what the engine reads:
  `SeededRows`, `FirstApproxRow`, `ChunkRows`, `ChunkRowsRecomputed`, `FallbackReason`. `AssemblyMs`, `RecomputeMs` and
  `Forwards` are dropped; diagnostics stay on the seeder object.
  - The seam, `InferenceOptions.KvSeeder` and the timing fields are documented as experimental (XML docs + KV_CACHE.md).
    The repo has no `[Experimental]` convention.
  - The issue draft notes that the maintainer may prefer a `Generate` parameter, like the adapter.
- **S3.** New internal `PrefixCache.Remove(IKvCache)`. The fresh-cache fallback removes and disposes the old entry before it
  allocates, so the peak never holds two caches and no empty most-recently-used entry is left behind.
  - Test: entry count in `Fallback_WhenCacheCannotReturnToExactRows_UsesFreshCache`. Mutant M28 is killed.
- **S4.** New test `Seeder_CancelledAfterApproxRestore_KeepsRestoredRows_ForLaterOptedInRequest` kills M22, so it is no
  longer called equivalent.

**Nits:**
- Fatal exceptions (OOM, access violation, stack, SEH) are rethrown from the seeder catch (test
  `Seeder_OutOfMemory_IsNotSwallowed`, M29). The rollback catch is now broad but never catches fatal exceptions.
- "Single-slot" is corrected to "multi-entry LRU" in the docs and the draft.
- The contract and docs now state that the tag is the seeder's promise that the rows below it are exact, and that it is
  set only when rows were seeded.
- The duplicated "1976 passed" line in the draft is fixed.
- Dtype on a restored cache: not reachable today, because a `QuantizedKvCache` is never a prefix hit. This is noted, and
  there is no test.

**Tests** (CPU only, same filter):
- `PromptKvSeederTests`: **37 / 37**.
- Unit Engine + Server + Telemetry: **2010 passed, 16 skipped, 0 failed**.
- `DotLLM.Cli` builds.

On test-first order: the new tests were written together with the fixes. Their red is shown by the targeted mutants
M22 and M26–M29, each of which reverts one fix.

**Mutants:** archive of `b1257b86`, 213 tests in the filter, baseline green: **29 / 29 killed**. The log
`i5-b2-mutants.log` now holds both rounds. M22 is killed; M26–M29 are new.
