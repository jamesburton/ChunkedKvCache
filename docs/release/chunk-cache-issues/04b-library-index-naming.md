# Library: index files named by chunker, model and namespace; store registry (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Refs #1542. Umbrella: `00-umbrella.md`, PR row 2
> (library PR, Lane L; this draft is the Task 4b part and may be folded into the row-2 issue). Branch: `feature/chunk-cache`
> (local only). Plan: Phase I Task 4b (spec §14 L9). Builds on draft 04 (lock model).

**Suggested title:** `chunk-cache store: one index per chunker, model and namespace, plus a chunkcache.json registry`

## Body

`ChunkIndex.DefaultPath(storeRoot, chunker)` is `index-<chunker>.json`: one index per chunker for every model and
namespace. Two models (or two tenants) sharing a store root load each other's index as empty (other producer), save over
it, and the next orphan eviction deletes the first one's entries. The Phase S CLI worked around it with
`index-<chunker>.<producer12>.json` and its own `chunkcache.json`. This change makes the per-model, per-namespace name the
library's and moves the registry into the library.

- **Index name** `ChunkIndex.DefaultPath(storeRoot, chunker, modelId, ns)` =
  `<storeRoot>/index-<chunker>.<model12>.<ns-or-default>.json`: `model12` = first 12 lowercase hex of SHA-256 over the
  UTF-8 content model id (`ChunkIndex.ModelTag`; `GgufIdentity.ModelId` form; a server-backed client uses the server's
  model id); the last part is the namespace, or `default` for `ChunkNamespace.Default`. The index lock follows
  (`index-<chunker>.<model12>.<ns-or-default>.lock`, `AcquireIndexLock(storeRoot, chunker, modelId, ns, timeout)`).
  Chunker names must be `[a-z0-9_-]{1,64}`; the namespace is validated (`ChunkNamespace.Validate`) before it reaches a file
  name. **`default` becomes a reserved namespace** (`ChunkNamespace.IsValid("default")` is false), so the default namespace
  and a namespace named `default` can never share a file. `ChunkIndex.TryParseIndexFileName` parses a name back.
- **Not in the name:** tokenizer, RoPE, backend, dtype. `ChunkIndex.ProducerOf(path)` reads an index file's producer, and
  `chunkcache build` refuses to save over another producer's index at its name (exit 1).
- **Migration, read once.** `ChunkIndex.MigrateLegacyIndex(storeRoot, chunker, modelId, ns, keyOf, timeout)` (called under
  the new index lock; takes the store lock for the rename): when the new file does not exist, a legacy `index-<chunker>.json`
  or Phase S `index-<chunker>.<producer12>.json` saved by this producer is renamed (not copied: its keys never lose
  protection) and its registry row moves with it. A legacy file of another producer, an unreadable one, or one beside an
  existing current file is left where it is: still an index (its keys stay protected) until someone deletes it.
  `ChunkIndex.ResolveIndexPath` gives read-only callers the current file, else this producer's legacy file read in place.
  The legacy two-argument `DefaultPath(storeRoot, chunker)` stays (it names the legacy file).
- **Registry** `StoreRegistry`, `<storeRoot>/chunkcache.json`, format 2, snake_case: `{"format_version": 2, "indexes":
  [{"file", "chunker", "model12", "model_id", "tokenizer_id", "backend", "namespace", "producer", "updated", "tool": {...}}]}`
  (`tool`: tool-specific strings; unknown row properties are kept). `Find(chunker, modelId, ns)`, `Get`, `Upsert`,
  `Remove`, `EntryFor`, `Update(storeRoot, timeout, change)`.
  - **Advisory:** `ReferencedKeysUnder` / `StoreWideOrphans` still read every `index-*.json`, listed or not. `Load` never
    fails on content: a missing, corrupt or newer-format registry is rebuilt from the index file names (chunker, model tag,
    namespace); rows whose file is gone are dropped; unlisted current-form index files are added.
  - **Writes** only under the store lock (`Save` refuses otherwise), as load + change + save, atomically (temp file, flush,
    one rename), so concurrent writers never lose rows. A corrupt registry is copied to `chunkcache.json.bad` first; a
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
- [ ] `ChunkCacheCliTests.Build_MigratesAPhaseSStore_IndexRenamedOnce_RegistryKeepsRootAndSource`,
  `Build_NeverOverwritesAnotherProducersIndexAtItsName`, `Evict_AllForModel_RefusesRegistryIndexNamesOutsideTheStore`
  pass; `ChunkStoreTests.Namespace_Invalid_IsRefusedEverywhere("default")` passes.
- [ ] `ChunkReuseJsonContextDefaultsTests` covers `StoreRegistryJsonContext`.
- [ ] The owning doc has an index-name and registry section: `experiments/store/README.md`, "Index names and the store
  registry (Phase I Task 4b, L9)" (research repo; moves to the dotLLM docs with the library PR).
- [ ] The namespace rule change (`default` reserved) is reflected in issue draft 02 / the spec's validity rule before filing.
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
