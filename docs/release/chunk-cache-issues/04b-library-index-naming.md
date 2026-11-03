# Library: index files named by chunker, model and namespace; store registry (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Refs #1542. Umbrella: `00-umbrella.md`, PR row 2
> (library PR, Lane L; this draft is the Task 4b part and may be folded into the row-2 issue). Branch: `feature/chunk-cache`
> (local only). Plan: Phase I Task 4b (spec §14 L9). Builds on draft 04 (lock model).

**Suggested title:** `chunk-cache store: one index per chunker, model, producer and namespace, plus a chunkcache.json registry`

## Body

`ChunkIndex.DefaultPath(storeRoot, chunker)` is `index-<chunker>.json`: one index per chunker for every model and
namespace. Two models (or two tenants) sharing a store root load each other's index as empty (other producer), save over
it, and the next orphan eviction deletes the first one's entries. The Phase S CLI worked around it with
`index-<chunker>.<producer12>.json` and its own `chunkcache.json`. This change makes the per-model, per-namespace name the
library's and moves the registry into the library.

- **Index name** `ChunkIndex.DefaultPath(storeRoot, chunker, modelId, producer, ns)` =
  `<storeRoot>/index-<chunker>.<model12>.<p8>.<ns-or-default>.json` (review ruling S3): `p8` = first 8 lowercase hex of the
  producer identity `keyOf([]).Hex` (`ChunkIndex.ProducerTag`; it hashes model fingerprint, tokenizer, RoPE, backend, dtype,
  positioning and namespace, so a CPU and a Vulkan producer of one model keep separate indexes); `model12` = first 12 lowercase hex of SHA-256 over the
  UTF-8 content model id (`ChunkIndex.ModelTag`; `GgufIdentity.ModelId` form; a server-backed client uses the server's
  model id); the last part is the namespace, or `default` for `ChunkNamespace.Default`. The index lock follows
  (`index-<chunker>.<model12>.<p8>.<ns-or-default>.lock`, `AcquireIndexLock(storeRoot, chunker, modelId, producer, ns, timeout)`).
  **Task 14's `GET /v1/chunk-cache` must return the producer hash** (`keyOf([]).Hex`) with the content model id and tokenizer
  id, so a server-backed client (Task 17) names the index it reads.
  Chunker names must be `[a-z0-9_-]{1,64}`; the namespace is validated (`ChunkNamespace.Validate`) before it reaches a file
  name. **`default` becomes a reserved namespace** (`ChunkNamespace.IsValid("default")` is false), so the default namespace
  and a namespace named `default` can never share a file. `ChunkIndex.TryParseIndexFileName` parses a name back.
- **Producer collisions:** only 32 bits of the producer are in the name. `ChunkIndex.ProducerOf(path)` reads an index file's
  producer; `chunkcache build` writes its own file next to another producer's index, and refuses (exit 1) only a prefix
  collision (a file at its exact name recorded by another producer), never overwriting it.
- **Migration, read once.** `ChunkIndex.MigrateLegacyIndex(storeRoot, chunker, modelId, ns, keyOf, timeout)` (called under
  the new index lock; takes the store lock for the rename): when the new file does not exist, a legacy `index-<chunker>.json`
  or Phase S `index-<chunker>.<producer12>.json` or Task 4b `index-<chunker>.<model12>.<ns-or-default>.json` saved by this
  producer is renamed (not copied: its keys never lose
  protection) and its registry row moves with it. A legacy file of another producer, an unreadable one, or one beside an
  existing current file is left where it is: still an index (its keys stay protected) until someone deletes it.
  `ChunkIndex.ResolveIndexPath` gives read-only callers the current file, else this producer's legacy file read in place.
  The legacy two-argument `DefaultPath(storeRoot, chunker)` stays (it names the legacy file).
- **Registry** `StoreRegistry`, `<storeRoot>/chunkcache.json`, format 2, snake_case: `{"format_version": 2, "indexes":
  [{"file", "chunker", "model12", "producer8", "model_id", "tokenizer_id", "backend", "namespace", "producer", "updated", "tool": {...}}]}`
  (`tool`: tool-specific strings; unknown row properties are kept). `Find(chunker, modelId, ns)`, `Get`, `Upsert`,
  `Remove`, `EntryFor`, `Update(storeRoot, timeout, change)`.
  - **Advisory:** `ReferencedKeysUnder` / `StoreWideOrphans` still read every `index-*.json`, listed or not. `Load` never
    fails on content: a missing, corrupt or newer-format registry is rebuilt from the index file names (chunker, model tag,
    namespace); rows whose file is gone are dropped; unlisted current-form index files are added.
  - **Writes** only under the store lock (`Save` refuses otherwise), as load + change + save, atomically (temp file, flush,
    one rename), so concurrent writers never lose rows; `Save(handle)` takes the held store-lock handle as proof. A corrupt
    registry is copied to `chunkcache.json.bad-<utc time>` first (earlier copies kept); a read refused by a sharing
    violation is retried for 2 s; a
    newer-format registry is never overwritten. Rows naming anything but a plain `index-*.json` in the store root are refused
    on load (`InvalidRows`) and never reach a delete.
  - Reads the Phase S CLI's version-1 `chunkcache.json` and rewrites it as version 2 (the CLI's fields move into `tool`).
- **CLI:** `StoreLayout` sits on `StoreRegistry`; `build` uses the new names and migrates; `status`, `select` and
  `build --dry-run` read a legacy index in place; `evict --all-for-model` finds a model's indexes by model tag (any chunker,
  any namespace), legacy names by producer, and refuses while the registry has refused rows.

Not in this change: a server-backed CLI keying on the server's model identity (Task 17, using `GET /v1/chunk-cache` from
Task 14); per-render-profile names (`[-<render>]`, later).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit --filter FullyQualifiedName~ChunkReuse` passes.
- [ ] `StoreRegistryTests`: `TwoModelsSameChunker_TwoIndexFiles`, `TwoNamespaces_TwoIndexFilesAndLocks`,
  `Names_ValidatedBeforeTheyReachAFileName_AndParseBack`, `StoreWideOrphans_FromOneNamespace_NeverDeletesOtherNamespacesEntries`,
  `Orphans_CountKeysFromAllModelIndexes_RegistryIsNotAuthoritative`, `Registry_ListsEveryIndex_AndRebuildsWhenMissing`,
  `Registry_SaveIsAtomic_AndOnlyUnderTheStoreLock`, `Registry_Corrupt_IsRebuilt_KeptAsBad_AndNewerVersionIsNeverOverwritten`,
  `Registry_ConcurrentWriters_LoseNoRow`, `OldIndexName_MigratedWhenProducerMatches`,
  `OldIndexName_OtherProducer_LeftAndStillReferenced` pass (file names checked against SHA-256 computed in the test).
- [ ] `StoreRegistryTests.TwoProducersSameModelAndNamespace_TwoIndexFiles`, `Registry_RebuiltRow_RecordsTheIndexProducer`,
  `Registry_TransientReadError_IsRetried_PersistentOneBlocksOnlyThatSave` pass (fix round).
- [ ] `ChunkCacheCliTests.Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`,
  `Build_AnotherProducersIndex_IsLeftAlone_ThisProducerWritesItsOwn`, `Build_NeverOverwritesAProducerPrefixCollision`,
  `Evict_AllForModel_RefusesRegistryIndexNamesOutsideTheStore`
  pass; `ChunkStoreTests.Namespace_Invalid_IsRefusedEverywhere("default")` passes.
- [ ] `ChunkReuseJsonContextDefaultsTests` covers `StoreRegistryJsonContext`.
- [ ] The owning doc has an index-name and registry section: `experiments/store/README.md`, "Index names and the store
  registry (Phase I Task 4b, L9)" (research repo; moves to the dotLLM docs with the library PR).
- [x] The namespace rule change (`default` reserved) is reflected in issue draft 02 (fix round). The spec §5 `namespace`
  row and §14 L3/L9 rows, and the plan's Task 2 / Task 4 / Task 16 text, are updated by the controller before filing.
- [ ] Every correctness test shown to fail against a mutant (below).

## Mutant evidence

`git archive` copy of `0d3f9aaf` (N13 rerun with the `393b0e67` test), filter `StoreRegistryTests | StoreLockTests | ChunkCacheCliTests | ChunkIndexTests | ServerLedgerTests | ChunkStoreTests.Namespace | ChunkReuseJsonContextDefaultsTests`. **18 / 18 killed.** History: N13 (rows of deleted index files kept) first SURVIVED: the stale-row step ran after the registry file had been deleted, so no stale row existed; the test now saves the registry first and checks the load note (`393b0e67`), and N13 is killed. Driver and log: `.superpowers/sdd/2026-11-01-phase-s/phase-i-task-4b-mutate.py`, `phase-i-task-4b-mutants.log`.

| mutant | verdict | killed by |
|---|---|---|
| N1 model hash omitted from the name (plan) | KILLED | `Build_DryRun_WritesNothing_AndEstimatesFromTheModelGeometry`, `Build_EncodesEveryMissingChunk_StoreMatchesIndex`, `Build_MaxChunks_EncodesAtMostN_StatusListsTheRest`, `Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`, `Build_NeverOverwritesAnotherProducersIndexAtItsName`, `Build_OtherTreeRoot_IsRefusedWithoutReroot`, `Build_Rerun_IsAllHits`, `Build_Selection_EncodesASelectedChunkWhoseTextAlsoOccursInAnUnselectedEarlierFile`, `Build_SkippedProject_ExitsNonZeroOnlyWithStrictFlag`, `Build_StoreWriteFailure_ExitsOne`, `Build_WithSelection_EncodesOnlySelectedChunks_ButIndexesTheTree`, `Compare_PrintsTheTable_NamesThePathOfEachTiming_AndFullRecomputeEqualsFullPrefill`, `Evict_AllForModel_RefusesRegistryIndexNamesOutsideTheStore`, `Evict_AllForModel_RemovesOnlyThatModelsEntriesAndIndexes`, `Evict_Apply_KeepsEntriesReferencedByAnyIndex`, `Evict_DryRun_DoesNotDelete_ApplyDeletesOnlyOrphans`, `Evict_KeepsServerLedgerKeys_AndAnUnreadableLedgerBlocksIt_StatusReportsTheLedger`, `Json_UsesTheMcpToolSchemaNames`, `Lock_ConcurrentBuildAndEvict_LeaveTheStoreComplete`, `Lock_EachPutTakesTheStoreLock_AHeldLockFailsThePutsNotTheIndex`, `Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot`, `Paths_SpacesNonAsciiAndRelativeStore`, `Select_PathSymbolBudget_AndStoredFlags`, `Status_AfterEdit_ListsTheStaleFile_AndARebuildEncodesOnlyItsChangedChunks`, `Status_TextOutput_ListsMissingChunksByFileAndLineRange`, `SameChunkerIndexUpdates_Serialise`, `Names_ValidatedBeforeTheyReachAFileName_AndParseBack`, `OldIndexName_MigratedWhenProducerMatches`, `Orphans_CountKeysFromAllModelIndexes_RegistryIsNotAuthoritative`, `Registry_ConcurrentWriters_LoseNoRow`, `Registry_ListsEveryIndex_AndRebuildsWhenMissing`, `Registry_SaveIsAtomic_AndOnlyUnderTheStoreLock`, `TwoModelsSameChunker_TwoIndexFiles`, `TwoNamespaces_TwoIndexFilesAndLocks` |
| N2 namespace omitted from the name (plan) | KILLED | `Names_ValidatedBeforeTheyReachAFileName_AndParseBack`, `Registry_ListsEveryIndex_AndRebuildsWhenMissing`, `StoreWideOrphans_FromOneNamespace_NeverDeletesOtherNamespacesEntries`, `TwoNamespaces_TwoIndexFilesAndLocks` |
| N3 namespace omitted from the lock (plan) | KILLED | `TwoNamespaces_TwoIndexFilesAndLocks` |
| N4 registry treated as authoritative for orphans (plan) | KILLED | `Evict_Apply_KeepsEntriesReferencedByAnyIndex`, `Orphans_CountKeysFromAllModelIndexes_RegistryIsNotAuthoritative` |
| N5 migration ignores the producer | KILLED | `OldIndexName_OtherProducer_LeftAndStillReferenced` |
| N6 migration copies (legacy name stays) | KILLED | `Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`, `OldIndexName_MigratedWhenProducerMatches` |
| N7 migration does not move the registry row | KILLED | `Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`, `OldIndexName_MigratedWhenProducerMatches` |
| N8 'default' not reserved | KILLED | `Namespace_Invalid_IsRefusedEverywhere`, `Names_ValidatedBeforeTheyReachAFileName_AndParseBack` |
| N9 registry save without the store lock | KILLED | `Registry_SaveIsAtomic_AndOnlyUnderTheStoreLock` |
| N10 registry update | KILLED | `lock only around the save (lost updates): Registry_ConcurrentWriters_LoseNoRow` |
| N11 unreadable registry replaced without a .bad copy | KILLED | `Registry_Corrupt_IsRebuilt_KeptAsBad_AndNewerVersionIsNeverOverwritten` |
| N12 newer-format registry overwritten | KILLED | `Registry_Corrupt_IsRebuilt_KeptAsBad_AndNewerVersionIsNeverOverwritten` |
| N13 rows of deleted index files kept | KILLED | `Registry_ListsEveryIndex_AndRebuildsWhenMissing` |
| N14 registry rows with non-plain file names accepted | KILLED | `Evict_AllForModel_RefusesRegistryIndexNamesOutsideTheStore`, `Registry_Corrupt_IsRebuilt_KeptAsBad_AndNewerVersionIsNeverOverwritten` |
| N15 CLI build saves over another producer's index | KILLED | `Build_NeverOverwritesAnotherProducersIndexAtItsName` |
| N16 CLI build does not migrate | KILLED | `Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource` |
| N17 read-only verbs ignore a not-yet-migrated legacy index | KILLED | `Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`, `OldIndexName_MigratedWhenProducerMatches` |
| N18 name parser accepts an upper-case model tag | KILLED | `Names_ValidatedBeforeTheyReachAFileName_AndParseBack` |

### Fix round 1 (review `review-phase-i-task4-report.md`)

`git archive` copy of `08179bf5`, filter `StoreLockTests | StoreRegistryTests | ServerLedgerTests | ChunkCacheCliTests | StoredAssemblyTests | ChunkIndexTests`; driver / log `phase-i-task-4-fix-mutate.py`, `phase-i-task-4-fix-mutants.log`. **15 / 15 killed.**

| mutant | verdict | killed by |
|---|---|---|
| F1 S1 | KILLED | `lock timeout on put swallowed as a busy entry: Lock_EachPutTakesTheStoreLock_AHeldLockFailsTheBuildFast_StoreBusy`, `Assemble_StoreLockTimeoutOnPut_Propagates_NotCountedAsBusy` |
| F2 S1 | KILLED | `lock timeout on evict swallowed: Assemble_EvictFailsOnRejectedEntry_IsMissNotError` |
| F3 S2 | KILLED | `handle proof ignores the store root: StoreLockHandle_IsProofForItsLiveRootOnly_LedgerAndRegistry`, `Registry_SaveIsAtomic_AndOnlyUnderTheStoreLock` |
| F4 S2 | KILLED | `handle proof ignores disposal: ChildDisposesTheParentsHandle_ParentNoLongerHoldsIt`, `StoreLockHandle_IsProofForItsLiveRootOnly_LedgerAndRegistry`, `Registry_SaveIsAtomic_AndOnlyUnderTheStoreLock` |
| F5 S2 | KILLED | `ledger save without the lock check: StoreLockHandle_IsProofForItsLiveRootOnly_LedgerAndRegistry` |
| F6 S2 | KILLED | `order check process-wide (any root): LockOrder_IsPerStoreRoot` |
| F7 S2 | KILLED | `order check counts released handles: Build_MaxChunks_EncodesAtMostN_StatusListsTheRest`, `Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`, `Build_NeverOverwritesAProducerPrefixCollision`, `Build_OtherTreeRoot_IsRefusedWithoutReroot`, `Build_Rerun_IsAllHits`, `Build_StoreWriteFailure_ExitsOne`, `Compare_PrintsTheTable_NamesThePathOfEachTiming_AndFullRecomputeEqualsFullPrefill`, `Evict_AllForModel_RemovesOnlyThatModelsEntriesAndIndexes`, `Evict_Apply_KeepsEntriesReferencedByAnyIndex`, `Evict_DryRun_DoesNotDelete_ApplyDeletesOnlyOrphans`, `Evict_KeepsServerLedgerKeys_AndAnUnreadableLedgerBlocksIt_StatusReportsTheLedger`, `Lock_ConcurrentBuildAndEvict_LeaveTheStoreComplete`, `Lock_EachPutTakesTheStoreLock_AHeldLockFailsTheBuildFast_StoreBusy`, `Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot`, `Status_AfterEdit_ListsTheStaleFile_AndARebuildEncodesOnlyItsChangedChunks`, `ChildDisposesTheParentsHandle_ParentNoLongerHoldsIt`, `ChildFlowStartedInsideAScope_IsNotRefusedAfterTheScopeEnds`, `CrashedHolder_ItsLockIsFreedByTheOs`, `LockOrder_IndexLockWhileHoldingStoreLock_IsRefused`, `Lock_IsExclusive_EvenAgainstReaders`, `StaleLockFile_IsNotAHeldLock_AndIsNeverDeleted`, `StoreLock_ReleasedOnDispose_EvenAfterException` |
| F8 S3 | KILLED | `producer omitted from the name: Build_AnotherProducersIndex_IsLeftAlone_ThisProducerWritesItsOwn`, `Build_DryRun_WritesNothing_AndEstimatesFromTheModelGeometry`, `Build_EncodesEveryMissingChunk_StoreMatchesIndex`, `Build_MaxChunks_EncodesAtMostN_StatusListsTheRest`, `Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`, `Build_NeverOverwritesAProducerPrefixCollision`, `Build_OtherTreeRoot_IsRefusedWithoutReroot`, `Build_Rerun_IsAllHits`, `Build_Selection_EncodesASelectedChunkWhoseTextAlsoOccursInAnUnselectedEarlierFile`, `Build_SkippedProject_ExitsNonZeroOnlyWithStrictFlag`, `Build_StoreWriteFailure_ExitsOne`, `Build_WithSelection_EncodesOnlySelectedChunks_ButIndexesTheTree`, `Compare_PrintsTheTable_NamesThePathOfEachTiming_AndFullRecomputeEqualsFullPrefill`, `Evict_AllForModel_RefusesRegistryIndexNamesOutsideTheStore`, `Evict_AllForModel_RemovesOnlyThatModelsEntriesAndIndexes`, `Evict_Apply_KeepsEntriesReferencedByAnyIndex`, `Evict_DryRun_DoesNotDelete_ApplyDeletesOnlyOrphans`, `Evict_KeepsServerLedgerKeys_AndAnUnreadableLedgerBlocksIt_StatusReportsTheLedger`, `Json_UsesTheMcpToolSchemaNames`, `Lock_ConcurrentBuildAndEvict_LeaveTheStoreComplete`, `Lock_EachPutTakesTheStoreLock_AHeldLockFailsTheBuildFast_StoreBusy`, `Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot`, `Paths_SpacesNonAsciiAndRelativeStore`, `Select_PathSymbolBudget_AndStoredFlags`, `Status_AfterEdit_ListsTheStaleFile_AndARebuildEncodesOnlyItsChangedChunks`, `Status_TextOutput_ListsMissingChunksByFileAndLineRange`, `SameChunkerIndexUpdates_Serialise`, `Names_ValidatedBeforeTheyReachAFileName_AndParseBack`, `OldIndexName_MigratedWhenProducerMatches`, `Orphans_CountKeysFromAllModelIndexes_RegistryIsNotAuthoritative`, `Registry_ConcurrentWriters_LoseNoRow`, `Registry_ListsEveryIndex_AndRebuildsWhenMissing`, `Registry_RebuiltRow_RecordsTheIndexProducer`, `TwoModelsSameChunker_TwoIndexFiles`, `TwoNamespaces_TwoIndexFilesAndLocks`, `TwoProducersSameModelAndNamespace_TwoIndexFiles` |
| F9 S3 | KILLED | `Task 4b names not migrated: Build_AnotherProducersIndex_IsLeftAlone_ThisProducerWritesItsOwn`, `OldIndexName_MigratedWhenProducerMatches` |
| F10 S3 | KILLED | `CLI saves over a producer-prefix collision: Build_NeverOverwritesAProducerPrefixCollision` |
| F11 N2 | KILLED | `rebuilt row without the producer: Registry_RebuiltRow_RecordsTheIndexProducer` |
| F12 N3 | KILLED | `registry read not retried: Registry_TransientReadError_IsRetried_PersistentOneBlocksOnlyThatSave` |
| F13 N4 | KILLED | `.bad copy overwritten: Registry_Corrupt_IsRebuilt_KeptAsBad_AndNewerVersionIsNeverOverwritten` |
| F14 N5 | KILLED | `access denied on a lock open not retried: LockFile_AccessDenied_IsRetriedWithinTheTimeout_ThenBusy` |
| F15 N9 | KILLED | `registry failure after a migration rename not explained: OldIndexName_MigratedWhenProducerMatches` |
