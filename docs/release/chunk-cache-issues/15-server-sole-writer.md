# Server: the chunk store's sole writer (admission, idle-only background encode, ledger, disk budget) (draft) — SECURITY-SENSITIVE

> **Status: DRAFT, not filed.** Lane S, plan Task 15 (I1b). Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and
> #1542 (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Security-sensitive:** this is the first code in the server that persists caller-supplied text (as token ids and K/V)
> to disk; the admission rules (deny-list, `no_store`, authenticated callers only, index-only mode) are privacy
> controls and should be reviewed as such. Branch `feature/chunk-cache-server`, worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`, on top of the Task 14 security fix round (`3db1b01c`):
> `804f8f1c` (library: owner lock, index-only referenced keys, deny-list), `0231b85b` (server), `b6fc3832` + `8e309015`
> (tests), `2eb254df` (docs).
> **Security review fix round** (`review-phase-i-task15-report.md`, 7 should-fix + nits): `72919d72` (deny-list),
> `2be535b8` (server), `923a2246` + `10abfc68` (tests, written first and shown red), `7fbc5447` (docs). Summary in the
> section "Review fix round" below.
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
2. its `source.path`, when given, is not on the deny-list (`ChunkDenyList`, new in `DotLLM.ChunkReuse`; the widened
   list and the Windows-spelling normalisation are under "Review fix round", S6), and its text holds no PEM private
   key; a `source` that is not an object or a non-string `path` is never admitted (the annotation itself is still
   accepted: `source` never affects lookup); the most restrictive occurrence of a repeated text decides;
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

## Review fix round (security review of Task 15)

- **S1, oversized entries.** An encoded entry larger than the budget, or than what the server's own rows could free, is
  dropped alone with `chunk_store_unavailable` / `detail: entry_too_large`; nothing is evicted and the writer keeps
  running. Only a store with nothing the server may evict stops encoding (`budget_exhausted`). A caller can no longer
  stop the writer for everyone with one large chunk.
- **S2, shutdown.** An encode in progress cannot be interrupted (the forward takes no cancellation). The server waits up
  to 30 s; if the worker is still encoding, the model, the request gate and the store's ownership are left for the
  process exit (logged by type only) instead of being freed under a running forward; ownership is released by the
  worker itself when it ends.
- **S3, ledger unreadable mid-run.** One state: after a failed save the ledger is read back (brief retries for a sharing
  violation); if it cannot be read, the unsaved row leaves memory and writes stop (`ledger_unreadable`: no admission,
  encode or write; the file is never written over). Only a verified read (retried every 30 s) re-enables writes; the
  same applies to an unreadable ledger at startup.
- **S4, latency.** The worker takes the model only after 2 s of quiet (no request running, waiting or started meanwhile;
  a fixed constant), and pauses 10 s after 4 encodes in one quiet window. Worst-case wait for a request is one encode:
  measured on the synthetic test model (CPU, 1 thread) about 35 ms for 86 tokens and 2.0-2.2 s for 2048 tokens; a real
  CPU model is not measured (plausibly tens of seconds for 2048 tokens of a 7-8B model).
- **S5, fairness.** Per-namespace queue share (64 of 256), at most 16 texts queued per request, per-namespace sighting
  share (25,000 of 100,000), `source.path` stored capped at 256 characters (prefix + hash), and budget eviction takes the
  writing namespace's own rows first.
- **S6, deny-list (ruling).** Denied by file name: `.env*`, `*.env`, `*.pem`, `*.key`, `*.pfx`, `*.p12`, `id_*`,
  `id_rsa*`, `secrets.*`, `appsettings*.json` (all, including `appsettings.Development.json`), `credentials*`,
  `.npmrc`, `.netrc`, `.pgpass`; and anything under `.git/` or `.ssh/`. Windows spellings are normalised (trailing dots
  and spaces, `::` alternate data streams denied, `:stream` dropped, 8.3 short names whose stem could be a denied name
  denied). Chunk text with a PEM private-key header is never stored.
- **S7, offline writers (Task 17, no code here).** `chunkcache --offline` must take the owner lock with
  `StoreOwnerLock.TryAcquire` and **hold it for the whole write**. `StoreOwnerLock.IsHeldByAnother` is a racy probe (a
  server can start between the probe and the write, and the probe itself can make a starting server fail); use it for
  status display only.
- **Nits.** The most restrictive occurrence of a text repeated in one request decides; `serve` claims ownership before
  the model loads (a second writer fails in seconds); docs state that the owner lock is unreliable on network file
  systems and that the store holds token ids (same access controls as the repository, out of crash dumps); writer
  metrics `dotllm_chunk_store_{writes,evictions,skips}_total` and `dotllm_chunk_store_queue_depth` (fixed labels); a test
  for the model-swap drop; the GPU test also asserts no `chunk_store_unavailable`.

### Known limits (multi-tenant)

(a) The encode queue is shared (per-namespace share 64 of 256, 16 per request). (b) The sighting table is shared
(per-namespace share 25,000 of 100,000). (c) Sighting memory is bounded by the 256-character path cap. (d) The byte
budget and its LRU are shared: eviction prefers the writing namespace's own rows, but a tenant with none evicts others'
least recently used entries. Per-namespace budgets come with issue 16. The writer-wide `detail` values are visible to
every authenticated tenant. The owner lock assumes a local file system.

## Re-review fix round (second)

Commits `95afe2b6` (deny-list), `fb8850de` (server), `bcc36799` (tests, written first and shown red: 16 failing),
`eb0a1a68` + `6fdf4400` (docs).

- **R1, stop rule.** The writer stops (`budget_exhausted`) only when not even a minimum-size entry (32 tokens of the
  served model) would fit after evicting everything the server may evict; any other entry that cannot fit is dropped
  alone (`entry_too_large`), whatever its size. So a fresh writer on a CLI-built store cannot be stopped by one large
  chunk, and a store full of CLI entries plus a tiny server row stops instead of encoding and dropping every miss. An
  entry larger than the whole budget is refused before the store is counted, and, once the writer has stored one entry
  (bytes per token known), a chunk that could never fit is refused at admission (`over_budget`, no encode).
- **R2, drive-relative names.** A path segment with a colon is checked on both sides of it (`secrets.json:stream` and
  `C:secrets.json`, `D:.env`, `C:id_rsa`); `::` is still refused.
- **Nits.** PEM: `PRIVATE KEY` anywhere on a `-----BEGIN ` or `-----END ` line (PGP `PRIVATE KEY BLOCK` included); a key
  body split into a chunk with neither armour line is not detected (documented). Added patterns: `*.keystore`, `*.jks`,
  `kubeconfig*`, `.kube/**`, `.docker/**`, `*.tfvars`, `*.tfstate` (`.aws/credentials` was already covered by
  `credentials*`). NTFS hashed 8.3 names (`SE1A2B~1.JSO`) are denied when their extension could be a denied one.
  Monotonic clocks for the quiet period, ticks and reload retries. Stored path prefixes are cut at a character boundary.
  The misplaced `ServerState` doc comment is moved. `DisaggregatedScheduler` is not wired into the server, so the
  activity stamp's `ContinuousBatchScheduler` counter covers every server path (documented).
- **Measured worst-case request wait (S4).** Qwen3-4B-Instruct-2507 Q4_K_M, CPU, 8 threads, Strix Halo, one run under
  the `cpu-bench` lock with the CPU otherwise lightly loaded: a 512-token chunk encodes in 8.4 s, a 2048-token chunk in
  43.5 s. A request on a CPU server can therefore wait up to about 45 s behind one maximal background encode (about 8 s
  behind a 512-token wire chunk). The 2048-token cap (`MaxEncodeTokens`) is a candidate to lower to 512 for CPU servers
  (maintainer decision; fixed constants per ruling 61).
- **For issue 16 (forget).** A path stored on a sighting row longer than 256 characters is a prefix plus a hash, so
  forget must compare `SightingTable.StoredPath(requested)`, never the raw path.
- **Still not on the deny-list** (for the Task 16/17 deny-list flag): `*.kdbx`, `*.p8`, `.pypirc`, `.gnupg/`.

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `docs/SERVER.md` and `docs/CHUNK_CACHE.md` updated in the same PR.
- [ ] `--chunk-store-write`, `--chunk-store-budget`, `--chunk-store-index-only` documented and tested on both option
      paths; budget required; flag off / read-only store byte-identical to issue 13.
- [ ] No new `JsonSerializerContext` (the one new DTO field, `ChunkCacheWarningDto.Detail`, is nullable without an
      initializer, guarded by the existing `JsonContextDefaultsTests`).
- [ ] Mutation evidence below recorded in the PR body; `Closes #N` closed by hand on `dev`.
- [ ] GPU step: `VulkanServer_CpuWrittenStore_NoHits` run under the GPU lock (not yet run: lock not obtained).
- [ ] Task 17's `--offline` writer takes and holds the owner lock (`TryAcquire`), never relies on `IsHeldByAnother`.

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
