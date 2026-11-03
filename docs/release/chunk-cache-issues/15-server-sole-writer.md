# Server: the chunk store's sole writer (admission, idle-only background encode, ledger, disk budget) (draft) — SECURITY-SENSITIVE

> **Status: DRAFT, not filed.** Lane S, plan Task 15 (I1b). Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and
> #1542 (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Security-sensitive:** this is the first code in the server that persists caller-supplied text (as token ids and K/V)
> to disk; the admission rules (deny-list, `no_store`, authenticated callers only, index-only mode) are privacy
> controls and should be reviewed as such. Branch `feature/chunk-cache-server`, worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`, on top of the Task 14 security fix round (`3db1b01c`):
> `804f8f1c` (library: owner lock, index-only referenced keys, deny-list), `0231b85b` (server), `b6fc3832` + `8e309015`
> (tests), `2eb254df` (docs).
> **Packaging:** builds on issues 13 (exact / shadow, read-only `--chunk-store`) and 14 (auth, which gates the side
> effects), and on the library store issues 02, 03, 04, 04b (namespace key, server ledger, lock model, index naming),
> already merged into the server branch. Can ship as its own PR after 13 + 14; issue 16 (prewarm / evict / forget,
> per-namespace budgets, capabilities store figures) builds on it.

## Title

Server: `--chunk-store-write`, the server as the chunk store's only writer: encode admission, idle-only background encode, server ledger and a required disk budget (behind `--chunk-cache`)

## Body

Refs #1543, #1542.

Issues 13 and 14 let a `--chunk-cache` server look annotated chunks up in a store that only the `chunkcache` CLI fills.
The integration spec makes the server the store's **only** K/V writer (L1): the K/V is always computed by the server
from text it received and re-hashed, so no client can poison the store, and a CLI writes only `--offline` while it owns
the store. This adds that writer, opt-in, with the admission rules and disk budget of spec §5.10 and the privacy rules
of §10.

**Everything sits behind `--chunk-cache` and the new `--chunk-store-write` (both off by default).** Without
`--chunk-store-write` a `--chunk-store` stays read-only exactly as in issue 13; with `--chunk-cache` off nothing changes.

### Flags

- `--chunk-store-write`: needs `--chunk-store`; the server becomes the store's sole writer.
- `--chunk-store-budget <bytes>`: **required** with `--chunk-store-write` (no unlimited default; bytes or `20GiB` /
  `500MB`; above 0), rejected without it.
- `--chunk-store-index-only`: with `--chunk-store-write`, store only chunks that an index in the store references
  (built by `chunkcache build` from a scanned, deny-listed tree), so text from ad-hoc reads is never persisted.

All on `dotllm serve` and `ServerOptions.Parse`; a missing budget or a stray switch is a startup error.

### Ownership

At startup, before listening, the server takes `<store>/.chunkstore.owner.lock` exclusively for its lifetime
(`StoreOwnerLock`, new in `DotLLM.ChunkReuse`; the OS releases it if the process dies). A second server with
`--chunk-store-write` on the same directory exits with a message naming the lock (`InvalidServerOptionException`; `serve`
prints it and returns 1). A read-only server on the same store is fine. `StoreOwnerLock.IsHeldByAnother` is the probe
the offline CLI writer will use (issue 17). The owner lock is not the store lock: every write still takes the short
store lock, so CLI index updates and orphan passes interleave with the server between entries.

### Admission (spec §5.10; request thread, never blocking, never touching a lock file)

After `exact` / `shadow` planning, each verified **miss** of an **authenticated** caller (issue 14's rule: a local
caller without keys, or a valid key; anyone else gets no lookups and no side effects) on `/v1/chat/completions` or
`/v1/messages` (never `explain`, never a request failing strict) is queued for a background encode only when:
1. it is not `no_store` (no sighting either) and not `stability: "volatile"`;
2. its `source.path`, when given, is not on the deny-list (`ChunkDenyList`, new in `DotLLM.ChunkReuse`: `.env*`,
   `*.pem`, `*.key`, `*.pfx`, `id_*`, `secrets.json`, `appsettings.*.Development.json` by file name at any depth, and
   anything under `.git/`; case-insensitive on every platform); a `source` that is not an object or a non-string `path`
   is never admitted (the annotation itself is still accepted: `source` never affects lookup);
3. the backend is CPU and the chunk has at most 2048 tokens;
4. its text was seen in at least 2 requests in the caller's namespace (`SightingTable`: in memory, keyed by namespace
   and text hash, at most 100,000 rows, LRU; one sighting per request and text); `on_miss: "encode"` bypasses only this;
5. the writer is not stopped (unreadable ledger, budget exhausted);
6. with `--chunk-store-index-only`, an index references the key;
7. the queue has room (256 items, 16 Mi characters; a queued text is not queued twice).

The response reports `chunk_encode_queued` / `chunk_encode_skipped` (counts, one per verified miss) and
`tokens.encode_queued`. Hits refresh their ledger rows' last use. No per-chunk reason is reported (it would probe the
deny-list and the sightings).

### Background encode (one dedicated thread)

`ChunkEncodeQueue`'s worker encodes an item only while the server is idle (`ServerState.TryAcquireIdleModel`: request
gate free with no waiters, no load or activation in progress, the continuous-batch scheduler with no active or queued
sequence). It then holds the gate and the scheduler's model lease for **one** chunk's forward and releases them before
any disk I/O, so a request arriving meanwhile waits for at most one encode (≤ 2048 tokens). The text is tokenised again
with `ChunkTokenization.Encode` (contract ruling 21), the key recomputed with the served model's identity (a changed
model drops the item), and the chunk encoded in isolation at positions `0..n-1` on the served model (`ChunkEncoder`,
`CpuChunkBackend`): F32 rows, the model fingerprint and backend tag, bit-identical to what `chunkcache build` writes for
the same GGUF (tested). Shutdown cancels the worker and drops the queue.

### Writing, ledger and budget

- Per entry, **one** store-lock scope (taken on the worker thread, so the lock's 20 ms retry loop never runs on a
  request thread) holds the budget eviction, the put (temp + rename), the ledger `Record` and `Save` (which requires
  the held lock handle). File first, then row: no lock holder ever sees a row without a file; a crash leaves at most a
  file without a row (an orphan); a row whose file is gone is dropped on load. A failed put stores nothing; a failed
  ledger save keeps the old ledger file, reloads it and deletes the just-written file unless an index references it.
  `LockingChunkStore` is never used inside the scope (not re-entrant).
- **Budget**: the byte total of all entry files (CLI entries included) stays within `--chunk-store-budget`. Ledger rows
  go in LRU order; a row whose key an index also references (content-addressed keys) loses its row but keeps its file
  (decided after the ledger save, under the lock, from every index and the remaining ledger). Entries only an index
  references are never evicted. When the server's own entries cannot free enough, nothing is evicted and encoding stops
  (re-checked every 30 s). New library helper `ChunkIndex.IndexReferencedKeysUnder` (index keys without the ledger).
- **Unreadable ledger at startup**: writes disabled for the process lifetime; the ledger is never replaced by an empty
  one or saved over (`LedgerUnreadableException` is never handled as an ordinary `IOException`); inference runs.
- **Store problems in responses**: `chunk_store_unavailable` with an additive `detail` (`ledger_unreadable`,
  `budget_exhausted`, `lock_timeout`, `write_failed`) on responses with a verified miss of an authenticated caller.
  A warning only (never a strict 503): the request itself is unaffected. A lock timeout is never reported as a plain
  busy store.

### Vulkan

Only CPU entries are written. `ChunkReuseSchema.KvOutputVersion` pins CPU bits only, while Vulkan K/V also depend on the
shader binaries and the driver; until a per-backend schema version (or the shader set and driver identity in the Vulkan
fingerprint) is decided, a Vulkan server with `--chunk-store-write` refuses every miss (`chunk_encode_skipped`). CPU and
Vulkan entries never mix (backend in the key and the header): a GPU-gated test checks that a CPU-written store gives
`hit: 0` on a Vulkan server and that the Vulkan server writes nothing.

### Privacy

Nothing logs chunk text, hashes, keys or namespaces. The ledger holds each row's namespace and first `source.path`
(tree-relative only); the sighting table holds text hashes in memory. The store holds source code (token ids beside the
K/V): treat the root like the repository (spec §10). Maintainer decision carried from issue 14: namespaces derived by
unsalted `ForApiKey` now also land in `ledger-server.json`.

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `docs/SERVER.md` and `docs/CHUNK_CACHE.md` updated in the same PR.
- [ ] `--chunk-store-write`, `--chunk-store-budget`, `--chunk-store-index-only` documented and tested on both option
      paths; budget required; flag off / read-only store byte-identical to issue 13.
- [ ] No new `JsonSerializerContext` (the one new DTO field, `ChunkCacheWarningDto.Detail`, is nullable without an
      initializer, guarded by the existing `JsonContextDefaultsTests`).
- [ ] Mutation evidence below recorded in the PR body; `Closes #N` closed by hand on `dev`.
- [ ] GPU step: `VulkanServer_CpuWrittenStore_NoHits` run under the GPU lock (not yet run: lock not obtained).

## Tests

`ChunkStoreServiceTests` (direct, fake host), `ChunkStoreServerTests` (real HTTP server, synthetic model, CPU),
`ChunkStoreServerGpuTests` (GPU-gated), `StoreLockTests` additions. Counts and mutant evidence: see the next section.

## Mutation evidence

Driver and log: `.superpowers/sdd/2026-11-01-phase-s/phase-i-task-15-mutate.py`, `phase-i-task-15-mutants.log`. Each
mutant applied to a `git archive` copy (never the live worktree), filter `Server.ChunkCache|StoreLockTests`, Release, CPU;
baseline 290 / 290. Broad regression (ChunkReuse, Server, Cli, ChunkCache, PrefixLineage, Engine.PromptCache): 2043
passed, 41 skipped, 0 failed.

| mutant | killed by |
|---|---|
| L0 stub (no admission, writes or ownership; budget optional) | 27 new tests |
| seen-once admitted | `SeenOnce_NotQueued_SeenTwice_Queued`, `SameTextTwiceInOneRequest_IsOneSighting`, + 2 |
| eviction ignores the budget | `OverBudget_EvictsLruLedgerRows_NeverIndexOnlyEntries`, `CannotFree_StopsEncoding_Warns`, + 1 |
| ledger written before the file | `CrashMidPut_NoLoadableEntry_LedgerConsistentOnReload`, `PutRecordSave_InOneLockScope` (raw ledger) |
| unreadable ledger replaced by an empty one and saved | `UnreadableLedgerAtStartup_WritesDisabled_FileUntouched` (service + HTTP) |
| `LedgerUnreadableException` caught as `IOException` | same two |
| lock released between put and save | `RacingWriter_NeverSeesAFileWithoutItsRow` (a racing lock holder; cannot fail a correct writer) |
| evicted file deleted despite an index reference | `BudgetEviction_KeyAlsoInCliIndex_KeepsFile_RemovesRowOnly` |
| lock timeout reported as plain busy | `LockTimeout_SurfacesAsLockTimeoutDetail`, `RequestThread_NeverBlocksOnStoreLock` |
| `no_store` / `volatile` admitted; deny-list skipped, case-sensitive, `.git/**` ignored | `VolatileAndNoStore_NeverQueued`, `DenyList_DefaultPatterns` |
| unauthenticated callers admitted | `Unauthenticated_NoStoreSideEffects` |
| explain admits | `Explain_NeverAdmits` |
| encode not gated on idle | `EncodesOnlyWhenIdle`, + 3 |
| idle probe ignores the scheduler queue / a running request | `IdleProbe_RefusedWhileSchedulerHasWork` / `IdleProbe_RefusedWhileARequestRunsOrIsScheduled` |
| sightings per span | `SameTextTwiceInOneRequest_IsOneSighting` |
| LRU by first-seen; hits do not refresh LRU | `OverBudget_EvictsLruLedgerRows_NeverIndexOnlyEntries` |
| index-only ignored | `IndexOnly_AdHocTextNeverStored` |
| no ownership lock | `SecondServerSameRoot_FailsFast` (service + HTTP) |
| failed ledger save not rolled back | `CrashMidPut_NoLoadableEntry_LedgerConsistentOnReload` |
| budget not required (missing and zero accepted) | `BudgetRequired_StartupFailsWithoutIt` |
| queue unbounded; worker not cancelled on dispose | `Queue_IsBounded_AndDeduplicated`; `Dispose_StopsTheWorker_PendingItemsDropped` |
| worker tokenises with bare `EncodeRaw` | `ServerEncode_ChunkWithThinkTag_UsesChunkTokenization` |
| store problem not reported | 6 tests |
| Vulkan backend admitted | `VulkanBackendAndOverlongChunks_NotQueued` |
| rows evicted although eviction cannot make room | `CannotFree_EvictsNothing_KeepsOwnRows` |

Three tests were strengthened after their mutant first survived (raw ledger read, racing writer, own rows kept); one
mutant ("budget not required", removing only the missing-budget throw) was equivalent and replaced. Not mutant-checked:
the gate-waiter / loading / activation conditions of the idle probe, the key re-check after a model swap, the
index-snapshot refresh and the budget re-check timer.

**GPU step:** `VulkanServer_CpuWrittenStore_NoHits` is written and gated (`[SkippableFact]`, `Category=GPU`) but has
not run: the GPU lock was not obtained (see the task report). Run it under the GPU lock before filing.
