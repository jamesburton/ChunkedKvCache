# Library: server ledger and ownership-aware orphan eviction (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Refs #1542. Umbrella: `00-umbrella.md`, PR row 2
> (library PR, Lane L Tasks 1-5; this draft is the Task 3 part and may be folded into the row-2 issue). Branch:
> `feature/chunk-cache` (local only; the library PR is cut fresh from `dev` later). Plan: Phase I Task 3 (spec §14 L2).

**Suggested title:** `chunk-cache store: server ledger so orphan eviction never deletes server-written entries`

## Body

Today `ChunkIndex.StoreWideOrphans` is store keys minus the keys any `index-*.json` references. Once the server becomes the
only K/V writer (spec §14 L1), its entries are referenced by no index, so a plain `chunkcache evict --apply` (or the server's
own `orphans` eviction) would delete every one of them. Budget (LRU) eviction and "forget this path" also need per-entry
last-use times and provenance that no index holds. This adds the server ledger to `DotLLM.ChunkReuse`; the server writes it
in the I1b store PR.

What it adds:

- **`ServerLedger`** (`<storeRoot>/ledger-server.json`): one row per server-written key, `LedgerRow(KeyHex, Namespace,
  SourcePath, Bytes, FirstSeen, LastUsed)`.
  - `Load(storeRoot)`: a missing file is an empty ledger (nothing is created); a row whose entry file is gone is dropped
    (`DroppedOnLoad`; the next save persists it).
  - `Record(key, ns, sourcePath, bytes, now)`: a new row, or a re-sighting that keeps the first-seen time and provenance,
    takes the new size, and never moves `LastUsed` backwards. The namespace must pass `ChunkNamespace.Validate`; a key
    already recorded under another namespace is refused (the namespace is hashed into the key). `sourcePath` is
    tree-relative and normalised like index paths.
  - `Touch(key, now)` (a hit), `Remove(key)` (forget / budget eviction: the only way a ledger key loses protection),
    `LeastRecentlyUsed()` (ascending `LastUsed`, then key), `UnderPath(glob)` (`PathGlob` semantics, case-insensitive on
    Windows like `ChunkIndex.PathComparer`), `InNamespace(ns)`.
  - `Save()`: temp file, flush, one rename (retried briefly while a reader holds the file); stale temp files are swept after
    an hour. Rows are written sorted by namespace then key, so each namespace is one contiguous section and identical
    content gives identical bytes.
- **Format version 1**, camelCase, source-generated `JsonSerializerContext`, nullable DTO properties (no initialisers).
  Unknown properties are ignored; any other version, a missing field, a malformed / duplicate row, an invalid namespace, a
  rooted source path, or an I/O error is **`LedgerUnreadableException`** (an `IOException` naming the file, never a
  namespace value), never an empty ledger.
- **`ChunkIndex.ReferencedKeysUnder`** now adds every ledger key (all namespaces; `exceptPath` never skips the ledger), so
  `StoreWideOrphans` = store keys minus index keys minus ledger keys, and `EvictableOrphans` honours the ledger too. An
  unreadable ledger makes both throw: eviction fails closed and deletes nothing.
- **`chunkcache status`** reports the ledger (`ledger: {state: absent | ok | unreadable, rows, rows_without_entry, error}`
  in `--json`; one text line), and still exits 0 when the ledger is unreadable (read-only verb). **`chunkcache evict`** says
  entries are kept when "referenced by an index or the server ledger" and exits 1 on an unreadable ledger (dry run and
  `--apply`).

**Locking.** The ledger has one writer, the server that owns the store. It must put the entry file first, then record and
save the row, holding `ChunkIndex.AcquireStoreLock` from the put through the ledger save; an eviction pass holds the same
lock from `StoreWideOrphans` to its deletes, so it never sees a new entry without its row. Lane L Task 4 narrows these
scopes (per Put batch, per ledger / index save, per eviction pass); this change only documents the order.

Not in this change: the server's use of the ledger (Task 15: encode, budget eviction; Task 16: prewarm, evict modes
`path` / `namespace`, per-namespace figures), and the CLI revision (Task 17).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit --filter FullyQualifiedName~ChunkReuse` passes.
- [ ] `ServerLedgerTests`: `Ledger_RoundTrip` (oracle: the file parsed with `JsonNode`; byte-identical re-save),
  `Ledger_Record_RefusesBadInput`, `Ledger_RowWithoutStoreFile_DroppedOnLoad`, `Ledger_LruOrder_Deterministic`,
  `Ledger_UnderPath_UsesGlobAndPathComparer`, `Ledger_TwoNamespaces_DoNotAffectEachOther`,
  `StoreWideOrphans_KeepsLedgerKeys`, `StoreWideOrphans_UnreadableLedger_ThrowsAndDeletesNothing` (14 cases: not JSON,
  null, future version, no version, no rows, null row, bad key, bad namespace, no namespace, negative bytes, no last use,
  rooted source, duplicate key, truncated), `Ledger_HeldExclusivelyByAnotherProcess_IsUnreadable_NotEmpty`,
  `Ledger_UnknownFieldsAreIgnored_WithinTheVersion`, `Ledger_SaveIsAtomic`,
  `Ledger_ConcurrentSaves_EvictionNeverSeesAPartialLedger`, `Ledger_IsNotAnIndexFile_AndDefaultPathIsInTheStoreRoot` pass.
- [ ] `ChunkCacheCliTests.Evict_KeepsServerLedgerKeys_AndAnUnreadableLedgerBlocksIt_StatusReportsTheLedger` passes.
- [ ] Every correctness test shown to fail against a mutant (below).

## Mutant evidence

Each mutant was applied in a `git archive` copy of `d1f6a069` (scratchpad `p1t3\copy`; the live worktree was never
mutated), the unit tests were built with `-m:2` and the filter `ServerLedgerTests | ChunkCacheCliTests.Evict_ |
ChunkIndexTests` run on the CPU (`DOTLLM_SKIP_VULKAN=1`; baseline 66 passed / 0 failed), then the file was restored byte for
byte (checked with `diff -r --strip-trailing-cr` afterwards). **23 applied, 23 killed.** M4's first form (`if (true)`) did
not compile (CS0162 as error) and was rewritten as `File.Exists(...) || key.Length > 0`; the rewrite is killed. Driver
`phase-i-task-3-mutate.py`, log `phase-i-task-3-mutants.log` (`.superpowers/sdd/2026-11-01-phase-s/`).

| mutant | killed by |
|---|---|
| M1 orphans ignore the ledger (plan) | `StoreWideOrphans_KeepsLedgerKeys`, `Ledger_TwoNamespaces_DoNotAffectEachOther`, `Ledger_ConcurrentSaves_EvictionNeverSeesAPartialLedger`, CLI `Evict_KeepsServerLedgerKeys_…`, and more |
| M2a non-JSON ledger treated as empty (plan: unreadable = empty) | `StoreWideOrphans_UnreadableLedger_ThrowsAndDeletesNothing` |
| M2b unknown future version treated as empty | `StoreWideOrphans_UnreadableLedger_…`, CLI `Evict_KeepsServerLedgerKeys_…` |
| M2c malformed row skipped instead of refused | `StoreWideOrphans_UnreadableLedger_…` |
| M2d `ReferencedKeysUnder` swallows `LedgerUnreadableException` | `StoreWideOrphans_UnreadableLedger_…`, `Ledger_HeldExclusively…`, CLI `Evict_KeepsServerLedgerKeys_…` |
| M2e I/O error (locked file) treated as empty | `Ledger_HeldExclusivelyByAnotherProcess_IsUnreadable_NotEmpty` |
| M3 LRU by FirstSeen (plan) | `Ledger_LruOrder_Deterministic` |
| M3b LRU tie broken by descending key | `Ledger_LruOrder_Deterministic` |
| M4 rows without an entry file kept on load | `Ledger_RowWithoutStoreFile_DroppedOnLoad` |
| M5 ledger overwritten before the crash point (non-atomic) | `Ledger_SaveIsAtomic`, `Ledger_ConcurrentSaves_…` |
| M6 `LastUsed` can move backwards | `Ledger_LruOrder_Deterministic` |
| M7 re-record overwrites first-seen provenance | `Ledger_RoundTrip` |
| M7b re-record resets `FirstSeen` | `Ledger_RoundTrip` |
| M8 `UnderPath` as an ordinal prefix match | `Ledger_UnderPath_UsesGlobAndPathComparer` |
| M9 `InNamespace` ignores the namespace | `Ledger_TwoNamespaces_DoNotAffectEachOther`, `Ledger_UnderPath_…` |
| M10 namespace rule not checked on load | `StoreWideOrphans_UnreadableLedger_…` |
| M11 duplicate rows not refused | `StoreWideOrphans_UnreadableLedger_…` |
| M12 `Record` re-assigns a key's namespace | `Ledger_Record_RefusesBadInput` |
| M13 rows not sorted on save | `Ledger_RoundTrip` |
| M14 negative bytes accepted on load | `StoreWideOrphans_UnreadableLedger_…` |
| M15 source path not normalised by `Record` | `Ledger_Record_RefusesBadInput`, `Ledger_RoundTrip` |
| M16 CLI `status` reports an unreadable ledger as absent | CLI `Evict_KeepsServerLedgerKeys_…` |
| M17 `Remove` does not remove | `Ledger_TwoNamespaces_DoNotAffectEachOther`, `StoreWideOrphans_KeepsLedgerKeys` |

