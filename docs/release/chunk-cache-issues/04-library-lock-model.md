# Library: store lock model with per-index locks and short store-lock scopes (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Refs #1542. Umbrella: `00-umbrella.md`, PR row 2
> (library PR, Lane L Tasks 1-5; this draft is the Task 4 part and may be folded into the row-2 issue). Branch:
> `feature/chunk-cache` (local only; the library PR is cut fresh from `dev` later). Plan: Phase I Task 4 (spec §14 L3).

**Suggested title:** `chunk-cache store: per-index locks and short store-lock scopes, so a long build never blocks the server`

## Body

Today every process that updates an index, puts entries or evicts holds the exclusive store lock (`.chunkstore.lock`,
`ChunkIndex.AcquireStoreLock`) from its index update through every encode and put to the end. A `chunkcache build` of a real
tree encodes for minutes to hours, and the server (the only K/V writer from spec §14 L1 on) would be locked out for that
whole time. This change narrows the store lock to short scopes and adds a per-index lock for index-only updates.

What it changes in `DotLLM.ChunkReuse`:

- **Index lock** (`ChunkIndex.AcquireIndexLock(storeRoot, chunker, modelId, producer, ns, timeout)`, or `AcquireIndexLockFor(indexPath,
  timeout)`): an exclusive (`FileShare.None`) `index-<...>.lock` next to each index file (its name follows the index name,
  see draft 04b). Held by every writer of that index from `Load` through `Update` to `Save`; different indexes never block
  each other and never wait for the store lock.
- **Store lock** (`AcquireStoreLock`, unchanged file): documented and used for **short scopes only**: one put batch, one
  ledger write (puts + `ServerLedger.Record` + `Save` of a batch in one scope), one registry save, one eviction pass.
  - `ChunkIndex.EvictStoreWideOrphans(store, root, timeout)`: one eviction pass (orphans computed and deleted in one
    store-lock scope).
  - `LockingChunkStore(inner, root, timeout)`: an `IChunkStore` whose `Put` / `Evict` take the store lock per call (for a
    writer that encodes between puts; the lock is never held across an encode).
- **Lock order:** index lock, then store lock; never an index lock while holding the store lock. Enforced per execution
  flow and per store root: an index lock of a store is refused (`InvalidOperationException`, at once, instead of a potential
  deadlock) while a live store-lock handle of the same store was acquired in this flow; released handles and other stores'
  handles do not count. Acquire and dispose a handle in one flow and do not start long-lived work inside a scope (a handle
  acquired in a child flow and handed back is not seen by the check). The store lock is not re-entrant.
- **Proof by handle:** `AcquireStoreLock` returns a `StoreLockHandle` (`StoreRoot`, `IsHeld`, `EnsureHeldFor(root)`).
  `StoreRegistry.Save(handle)` and `ServerLedger.Save(handle)` require the live handle of their own store root, whatever thread
  or async flow they run on.
- **Publication rule** (documented in the `ChunkIndex` remarks): a writer saves its index before putting the entries it
  references, and decides which referenced entries are already stored under the store lock after that save, so a
  concurrent eviction pass can never delete a key under a writer that relies on it (at worst a key evicted just before
  the check is a miss and is encoded again).
- **Timeouts:** `ChunkStoreLockTimeoutException` (new; derives from `ChunkStoreBusyException`, now unsealed, so callers that
  report "store unavailable" catch one type; names the lock file and the wait). `StoredContextAssembler` does **not**
  swallow it (unlike a busy entry, it is not counted as a store failure): a lock timeout on `Put` or on evicting a rejected
  entry propagates, so a writer stops after one timeout. Access denied while opening a lock file is retried like a sharing
  violation.
- **Stale lock files:** lock files are created on demand and never deleted; a file left on disk (crash, or any earlier
  holder) is not a held lock, only an open handle is, and the OS closes a dead holder's handle. Deleting a lock file would
  break the lock on POSIX (a new file is a new inode).
- **Platforms:** verified on Windows (NTFS), including a killed holder. On Linux / macOS .NET emulates `FileShare.None`
  with an advisory `flock` (honoured by other .NET processes, released at exit, disabled by
  `DOTNET_SYSTEM_IO_DISABLEFILELOCKING`, not binding on non-.NET programs): **not verified**; network file systems
  unsupported.

CLI (`tools/DotLLM.ChunkCache`): `build` holds the index lock for its index load / update / save, takes the store lock once
briefly for the registry save plus the publication check, then once per put (`LockingChunkStore`), never while encoding;
`evict --apply` is one eviction pass; a lock timeout (index lock, registry scope, or any put) stops the build at once with
exit 1 and JSON error code `store_busy`; `--lock-timeout` is the
wait for the index lock and for each store-lock scope.

Not in this change: the server's use of the locks (Task 15: put + record + save in one scope, budget eviction; Task 16
evict modes), and the CLI's `--offline` / ownership rules (Task 17).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit --filter FullyQualifiedName~ChunkReuse` passes.
- [ ] `StoreLockTests`: `IndexOnlyUpdate_DoesNotNeedStoreLock`, `SameChunkerIndexUpdates_Serialise` (timeout type, path,
  wait; six concurrent load-update-save writers lose no update), `DifferentChunkers_DoNotBlock`,
  `EvictionPass_HoldsStoreLock_PutTimesOut`, `StoreLock_ReleasedOnDispose_EvenAfterException` (store lock, index lock and
  a throwing put through `LockingChunkStore`), `LockOrder_IndexLockWhileHoldingStoreLock_IsRefused`,
  `Lock_IsExclusive_EvenAgainstReaders`, `StaleLockFile_IsNotAHeldLock_AndIsNeverDeleted`,
  `CrashedHolder_ItsLockIsFreedByTheOs` (Windows; a killed child process held the lock),
  `IndexLock_RefusesChunkerNamesThatAreNotAFileNamePart` pass.
- [ ] `StoredAssemblyTests.Assemble_StoreLockTimeoutOnPut_Propagates_NotCountedAsBusy` and the evict case in
  `Assemble_EvictFailsOnRejectedEntry_IsMissNotError`; `StoreLockTests` S2 cases (`StoreLockHandle_IsProofForItsLiveRootOnly_LedgerAndRegistry`,
  `LockOrder_IsPerStoreRoot`, `HandleFromAChildFlow_IsValidProof`, `ChildFlowStartedInsideAScope_IsNotRefusedAfterTheScopeEnds`,
  `ChildDisposesTheParentsHandle_ParentNoLongerHoldsIt`, `LockFile_AccessDenied_IsRetriedWithinTheTimeout_ThenBusy`) pass.
- [ ] `ChunkCacheCliTests.Lock_*`: a held store lock fails the build's registry save and puts with `store_busy` (the build
  stops after one timeout, `Lock_EachPutTakesTheStoreLock_AHeldLockFailsTheBuildFast_StoreBusy`) but not its
  index update; an eviction pass right after a build's index save keeps the re-referenced key and is not blocked; a held
  store lock during encoding fails every put (counted, exit 1, nothing written); a held index lock makes the build busy and
  leaves the index untouched; concurrent build and evict leave the store complete.
- [ ] The owning doc has a lock-model section: `experiments/store/README.md`, "Lock model (Phase I Task 4, L3)" (research
  repo; moves to the dotLLM docs that ship with the library PR).
- [ ] Every correctness test shown to fail against a mutant (below).

## Mutant evidence

`git archive` copy of `feature/chunk-cache` `80902e18`, unit tests built `-m:2`, filter `StoreLockTests |
ChunkCacheCliTests.Lock_ | ChunkIndexTests | ServerLedgerTests`, CPU (`DOTLLM_SKIP_VULKAN=1`). Driver and log:
`.superpowers/sdd/2026-11-01-phase-s/phase-i-task-4-mutate.py`, `phase-i-task-4-mutants.log` (research repo).

**16 / 16 killed.** History: L7's first form left an empty `finally` (build error, CS warning as error); rewritten (`+= 0`) and killed. L2 (handles never released) was killed by the library tests within minutes; its run was then aborted (my own `testhost.exe`, by PID) because every CLI put waits its full 30-60 s lock timeout (~1 h); the failures listed were reported before the abort.

| mutant | verdict | killed by |
|---|---|---|
| L1 index lock is the store lock (plan) | KILLED | `Lock_ConcurrentBuildAndEvict_LeaveTheStoreComplete`, `Lock_EachPutTakesTheStoreLock_AHeldLockFailsThePutsNotTheIndex`, `Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot`, `CrashedHolder_ItsLockIsFreedByTheOs`, `DifferentChunkers_DoNotBlock`, `EvictionPass_HoldsStoreLock_PutTimesOut`, `IndexLock_RefusesChunkerNamesThatAreNotAFileNamePart`, `IndexOnlyUpdate_DoesNotNeedStoreLock`, `LockOrder_IndexLockWhileHoldingStoreLock_IsRefused`, `SameChunkerIndexUpdates_Serialise` |
| L2 lock not released on dispose / exception (plan) | KILLED | `StoreWideOrphans_AreStoreKeysNoIndexReferences_AndTheStoreLockIsExclusive`, `EvictionPass_HoldsStoreLock_PutTimesOut`, `LockOrder_IndexLockWhileHoldingStoreLock_IsRefused`, `SameChunkerIndexUpdates_Serialise`, `StoreLock_ReleasedOnDispose_EvenAfterException` |
| L2b locking store releases the lock only when the put succeeds | KILLED | `StoreLock_ReleasedOnDispose_EvenAfterException` |
| L3 shared lock mode | KILLED | `FileShare.ReadWrite (plan): Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot`, `StoreWideOrphans_AreStoreKeysNoIndexReferences_AndTheStoreLockIsExclusive`, `EvictionPass_HoldsStoreLock_PutTimesOut`, `Lock_IsExclusive_EvenAgainstReaders`, `SameChunkerIndexUpdates_Serialise` |
| L3b shared lock mode | KILLED | `FileShare.Read: Lock_IsExclusive_EvenAgainstReaders` |
| L4 short timeouts give up at once (no wait) | KILLED | `SameChunkerIndexUpdates_Serialise` |
| L5 lock timeout is a plain TimeoutException (not ChunkStoreBusyException) | KILLED | `Lock_EachPutTakesTheStoreLock_AHeldLockFailsThePutsNotTheIndex`, `Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot`, `StoreWideOrphans_AreStoreKeysNoIndexReferences_AndTheStoreLockIsExclusive`, `CrashedHolder_ItsLockIsFreedByTheOs`, `EvictionPass_HoldsStoreLock_PutTimesOut`, `IndexOnlyUpdate_DoesNotNeedStoreLock`, `SameChunkerIndexUpdates_Serialise` |
| L6 lock order not enforced | KILLED | `LockOrder_IndexLockWhileHoldingStoreLock_IsRefused` |
| L7 store-lock count not decremented on dispose (v2 | KILLED | `v1 left an empty finally`, `a build error): Lock_ConcurrentBuildAndEvict_LeaveTheStoreComplete`, `Lock_EachPutTakesTheStoreLock_AHeldLockFailsThePutsNotTheIndex`, `Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot`, `CrashedHolder_ItsLockIsFreedByTheOs`, `LockOrder_IndexLockWhileHoldingStoreLock_IsRefused`, `Lock_IsExclusive_EvenAgainstReaders`, `StaleLockFile_IsNotAHeldLock_AndIsNeverDeleted`, `StoreLock_ReleasedOnDispose_EvenAfterException` |
| L8 eviction pass without the store lock | KILLED | `EvictionPass_HoldsStoreLock_PutTimesOut` |
| L9 locking store puts without the lock | KILLED | `Lock_EachPutTakesTheStoreLock_AHeldLockFailsThePutsNotTheIndex`, `EvictionPass_HoldsStoreLock_PutTimesOut` |
| L10 CLI build | KILLED | `no index lock: Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot` |
| L11 CLI build | KILLED | `old contract`, `store lock over the whole build: Lock_ConcurrentBuildAndEvict_LeaveTheStoreComplete`, `Lock_EachPutTakesTheStoreLock_AHeldLockFailsThePutsNotTheIndex`, `Lock_EvictAfterIndexPublished_KeepsReReferencedKeys_AndDoesNotWaitForTheBuild`, `Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot` |
| L12 CLI build | KILLED | `puts bypass the store lock: Lock_EachPutTakesTheStoreLock_AHeldLockFailsThePutsNotTheIndex` |
| L13 CLI | KILLED | `lock timeout reported as a generic error: Lock_HeldByAnotherWriter_BuildAndEvictApplyFail_DryRunsDoNot`, `Lock_IndexLockHeld_BuildIsBusy_DryRunIsNot` |
| L14 lock file deleted on release (breaks POSIX locks; stale-file contract) | KILLED | `CrashedHolder_ItsLockIsFreedByTheOs`, `StaleLockFile_IsNotAHeldLock_AndIsNeverDeleted` |

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
