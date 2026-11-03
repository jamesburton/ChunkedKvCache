# Server: prewarm, evict and forget, admin keys, per-namespace budget, capabilities store figures (draft) — SECURITY-SENSITIVE

> **Status: DRAFT, not filed.** Lane S, plan Task 16 (I1b). Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and
> #1542 (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Security-sensitive:** two new control-plane routes with side effects on a store that holds source code (prewarm
> persists caller text as token ids and K/V; evict deletes entries and is the spec's "forget this repo" privacy
> control), plus the first use of `admin` keys. Branch `feature/chunk-cache-server`, worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`, on top of Task 15 (`569f59a3`): `f31b2990` (library:
> per-file index keys), `c30dcd94` (server), `7576acba` (tests, written first and shown red 19 / 19), `5b2c2167` (docs), `2c85f5ed` (fence guard).
> **Packaging:** builds on issue 15 (the sole writer, its ledger, queue and sighting table) and issue 14 (auth, CSRF
> gates, `admin` parsed but inert there). Can ship as its own PR after 15; issue 17 (CLI `--server` / `prewarm` /
> `evict`) consumes this endpoint contract.

## Title

Server: `POST /v1/chunk-cache/prewarm` and `POST /v1/chunk-cache/evict` (orphans, forget by path / namespace / all), admin keys, `--chunk-store-namespace-budget`, and capabilities store figures (behind `--chunk-cache` and `--chunk-store-write`)

## Body

Refs #1543, #1542.

Issue 15 made a `--chunk-store-write` server the store's only K/V writer, encoding misses it has seen twice. Spec §7.2
adds two control-plane tools on top: **prewarm** (queue known text before it is ever requested, e.g. a repository just
indexed by `chunkcache build --encode`) and **evict** (remove orphans, or **forget** a path, a namespace or the whole
store: the §10 deletion control). This issue adds both routes, gives `admin` keys their meaning, adds the optional
per-namespace budget that stops one tenant's prewarm from evicting another's entries, and fills the capabilities
`store` figures that were 0 until now.

**Everything sits behind `--chunk-cache`; the write routes also need `--chunk-store-write`** (without it they answer
`503 chunk_store_unavailable`). With `--chunk-cache` off the routes do not exist (404) and nothing changes.

### Gates on both write routes (in order)

`404` flag off; `403 chunk_cache_cross_site` for `Sec-Fetch-Site: cross-site`; `415` unless `Content-Type:
application/json` (a browser must preflight, which the `Origin` rule refuses: no web page can drive a side effect,
CSRF); `401` / `403` as for the other routes (issue 14); `503 chunk_store_unavailable` without a writer; `429
chunk_control_busy` beyond 2 concurrent prewarm / evict calls. Metered like inference when rate limiting is configured.
Bodies are strict (unknown or repeated fields, wrong types: `400`, messages never echo content). Responses and logs carry
counts only: no namespace, key, key digest, text, hash or path.

### `POST /v1/chunk-cache/prewarm`

`{"texts": [{"id"?, "text", "source"?: {"path"?}}], "max_tokens"?}` → `{"requested", "already_stored", "queued",
"queued_tokens", "refused", "refused_reasons"}` (spec §7.2 output, ruling 14 input).
- **Text only**: no hash or hash list is accepted (a hash-only API would be a membership oracle).
- Each text is tokenised exactly as the chat path tokenises chunk text (`ChunkTokenization.Encode`, ruling 21) and keyed
  with the served model's identity **in the caller's namespace**. Already stored → `already_stored`. Otherwise the sole
  writer's admission (`ChunkStoreService.AdmitPrewarm`) with **every issue 15 rule except "seen in 2 requests"**, and
  **no sighting is recorded**: deny-list on `source.path` (advisory: the server cannot rely on it), PEM private-key
  sniff, CPU only and ≤ 512 tokens (ruling 65), budget (`over_budget`), writer not stopped, index-only, queue bounds
  (256 items, 64 per namespace). Encodes run under the same idle rule as encodes on miss.
- Caps: 256 texts per call (`400 chunk_too_many`, nothing queued), 4 MiB body (`413`), `max_tokens` bounds the tokens
  one call queues (a text past it is refused `max_tokens`).
- `refused_reasons`: the distinct admission reasons, never per text.

### `POST /v1/chunk-cache/evict`

`{"mode"?: "orphans" | "path" | "namespace" | "all", "path"?, "namespace"?, "dry_run"?}` → `{"evicted", "freed_bytes",
"kept_referenced", "dry_run", "removed": {"ledger_rows", "index_files", "sightings", "queued"}, "warnings"?}`
(`removed` and `warnings` are additive to the spec's output).
- **`dry_run` defaults to `true`**; only an explicit JSON `false` deletes (a string is a 400). `mode` defaults to `orphans`.
- **Namespaces are server-assigned.** The body `namespace` is honoured only for an **admin** (`default` names the default
  namespace; an invalid name is a 400); from anyone else it is ignored with `chunk_namespace_ignored` and the call acts
  on the caller's own namespace.
- `orphans`: files neither an index nor the ledger references; store-wide, so **admin only** (`403
  chunk_cache_admin_only` otherwise).
- `path` ("forget this repo"): in the namespace, ledger rows whose first-seen provenance matches the glob (relative,
  non-negated `PathGlob`), their entry files, and sighting rows / queued encodes with a matching provenance. The
  sighting table stores paths over 256 characters as a prefix plus a hash (issue 15); forget compares the requested path
  in that stored form too, so a long literal path matches.
- `namespace`: the namespace's ledger rows, **its own index files** (current names `index-<chunker>.<model12>.<p8>.<ns>.json`,
  index locks taken first), the entries those referenced, its sightings and queued encodes. Another namespace is never
  touched.
- `all`: a non-admin's own namespace; an admin without a body namespace wipes the **whole store** (every ledger row,
  current-name index file, sighting, queued encode and entry file, except those a remaining legacy-named index
  references).
- **Rule (c) and what forget keeps.** An entry whose key an index the call does not remove still references (a CLI
  index, which the server never edits; a legacy-named index, never deleted) keeps its file; its ledger row still goes;
  it is counted in `kept_referenced`. So `path` removes K/V, ledger rows and sightings, and **reports** index references
  instead of editing them (the server owns none; the CLI, issue 17, can forget its own index entries).
- **No marker**: removing the rows and saving suffices; the next sighting starts at 1 again. An encode in flight when
  its namespace is forgotten is dropped before its write by a fence (queue sequence numbers), so nothing forgotten comes
  back; for `path` the fence drops every in-flight item of the namespace (conservative).
- **Fail closed** (Review Focus): writes disabled (unreadable ledger at startup or after a failed save), a ledger file
  that no longer reads, or an unreadable index file → `503 chunk_store_unavailable` and **nothing deleted**, dry runs
  included. A ledger found unreadable here also disables writes until it reads back.
- **Locks** (lock order index → store): the index locks of the index files to delete, then the writer's in-memory ledger
  gate (shared with the background writer), then the store lock for **one short scope**: verify, save the ledger without
  the forgotten rows, delete the index files, re-read every reference from disk, delete the entry files no longer
  referenced. All waited for **asynchronously** within the writer's lock timeout (10 s), never by sleeping on a request
  thread; a timeout is `503` with nothing deleted. A dry run takes no lock file.

### Admin keys

`admin` in the keys file (parsed since issue 14) now grants: store-wide capabilities figures, `orphans`, another
namespace in the evict body, and a store-wide `all`. Without a keys file the **local caller is admin** (a single-user
server; the issue 14 review's condition, the CSRF gates above, is met).

### `--chunk-store-namespace-budget <bytes>` (optional, off by default)

Each namespace's ledger bytes must stay within it, and budget eviction (issue 15) takes **only the writing namespace's
own rows**: a namespace over its share evicts its own LRU rows; when the store is full of others' rows, the entry is
dropped (`entry_too_large`) instead of evicting another tenant, and a namespace never stops the writer for the others.
Admission refuses `over_budget` against the smaller budget. Off: issue 15's shared LRU (own rows first, then others').
Both option paths; needs `--chunk-store-write`; above 0.

### Capabilities `store`

With a writer: a **non-admin** sees its namespace's ledger `entries` / `bytes` and the budget that applies to it (the
namespace budget when set); an **admin** sees every entry file in the store and the store budget. Without a writer a
non-admin sees 0 and an admin the read-only store's files. `dtype` is `f32`.

### Library

`ChunkIndex.IndexFilesUnder`, `KeysOfIndexFile`, `IndexReferencedKeysUnder(root, except)` (same fail-closed
`InvalidDataException`); `IndexKeysUnder` refactored onto them, no behaviour change.

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `docs/SERVER.md` and `docs/CHUNK_CACHE.md` updated in the same PR.
- [ ] `--chunk-store-namespace-budget` documented and tested on both option paths (needs `--chunk-store-write`, above 0).
- [ ] Flag off: no route, bodies byte-identical; read-only store: write routes 503, nothing else changes.
- [ ] Three new DTOs (`ChunkCachePrewarmDto`, `ChunkCacheEvictDto`, `ChunkCacheEvictRemovedDto`) in the existing
      `ServerJsonContext`, no init-property initializers, guarded by `JsonContextDefaultsTests`; no new context.
- [ ] Mutation evidence below recorded in the PR body; `Closes #N` closed by hand on `dev`.
- [ ] Reviewed as security-sensitive (CSRF gates, admin scope, namespace isolation, fail closed, no content in logs).

## Tests

`ChunkCacheWriteEndpointTests` (19, real HTTP on the synthetic model, CPU; one direct service test for the namespace
budget): `Prewarm_TextOnly_QueuesWithoutSightings`, `Prewarm_DeniedPath_Refused`, `Prewarm_Caps_ItemsBytesTokens`,
`WriteRoutes_FlagWriterCsrfAndAuthGates`, `Evict_DryRunDefault_DeletesNothing`, `Evict_Orphans_KeepsLedgerAndIndexKeys`,
`Evict_Path_ForgetsAllFourKinds`, `Evict_Path_LongPath_MatchesStoredForm`, `Evict_Namespace_CannotTouchOtherNamespace`,
`NonAdmin_EvictBodyNamespace_Ignored`, `Evict_UnreadableLedger_FailsClosed`, `Evict_UnreadableIndex_FailsClosed`,
`Evict_StoreLockHeld_LockTimeout_NothingDeleted`, `EvictNamespaceMode_RemovesThatNamespacesIndexFilesRowsAndSightingsOnly`,
`Forget_ClearsSightings_NoMarker`, `Forget_DropsQueuedAndInFlightItems`, `Capabilities_ReportsStoreFigures`,
`NamespaceBudget_PrewarmEvictsOnlyOwnRows`, `WriteRoutes_NoNamespaceKeyTextOrPathInBodiesOrLogs`. Written first: 19 / 19
failed against stubs (routes unmapped, option inert), then green. Broad regression (ChunkReuse, Server, Cli, ChunkCache,
PrefixLineage, Engine.PromptCache): **2122 passed, 14 skipped, 0 failed**; server and CLI 0 warnings.

## Mutation evidence

Drivers and log: `.superpowers/sdd/2026-11-01-phase-s/phase-i-task-16-mutate.py`, `phase-i-task-16-fix-mutate.py`,
`phase-i-task-16-mutants.log`. Each mutant applied to a `git archive` copy (never the live worktree), filter
`Server.ChunkCache|StoreLockTests`, Release, CPU; baseline 370 / 370. **L0 + 34 mutants, all killed** (ten first
written as constant `if (true/false)` failed to compile under warnings-as-errors and were rewritten with non-constant
conditions; one rewrite failed nullable analysis and was rewritten again).

| mutant | killed by |
|---|---|
| L0 stub: write routes not mapped | 18 of the 19 new tests |
| dry run ignored (route default false / service flag ignored) | `Evict_DryRunDefault_DeletesNothing`, + 4 |
| cross-namespace evict (non-admin body namespace honoured) | `NonAdmin_EvictBodyNamespace_Ignored` |
| admin body namespace ignored | `NonAdmin_EvictBodyNamespace_Ignored` |
| sightings kept on forget | `Evict_Path_ForgetsAllFourKinds`, `Forget_ClearsSightings_NoMarker`, + 2 |
| namespace budget evicts globally / namespace share not enforced | `NamespaceBudget_PrewarmEvictsOnlyOwnRows` |
| ledger file on disk not verified (fail open) | `Evict_UnreadableLedger_FailsClosed` |
| unreadable index treated as none (fail open) | `Evict_UnreadableIndex_FailsClosed`, + 3 |
| index-referenced file deleted on forget (rule c) | `Evict_Path_ForgetsAllFourKinds`, `EvictNamespaceMode_…` |
| `kept_referenced` not counted | same two |
| prewarm records sightings | `Prewarm_TextOnly_QueuesWithoutSightings`, + 1 |
| prewarm skips deny-list / PEM sniff | `Prewarm_DeniedPath_Refused` |
| prewarm `max_tokens` ignored / item cap removed | `Prewarm_Caps_ItemsBytesTokens` |
| prewarm does not report already stored | `Prewarm_TextOnly_QueuesWithoutSightings` |
| orphans allowed for a non-admin | `Evict_Orphans_KeepsLedgerAndIndexKeys` |
| local keyless caller not admin | `Evict_Orphans_…`, `Evict_DryRunDefault_…`, + 2 |
| forget compares the raw path only (StoredPath form dropped) | `Evict_Path_LongPath_MatchesStoredForm` |
| no forget fence (in-flight encode written) / queued encodes kept | `Forget_DropsQueuedAndInFlightItems` |
| namespace index files not deleted / another namespace's or legacy ones deleted | `EvictNamespaceMode_RemovesThatNamespacesIndexFilesRowsAndSightingsOnly` (+ 1) |
| write routes: cross-site accepted / non-JSON accepted / no auth | `WriteRoutes_FlagWriterCsrfAndAuthGates` |
| capabilities: store-wide figures for a non-admin | `Capabilities_ReportsStoreFigures` |
| admin `all` keeps orphans and CLI entries | `NonAdmin_EvictBodyNamespace_Ignored` |
| dry run removes sightings | `Evict_DryRunDefault_…`, `EvictNamespaceMode_…` |
| `dry_run: "false"` (string) deletes | `Evict_DryRunDefault_DeletesNothing` |
| evict proceeds without the store lock | `Evict_StoreLockHeld_LockTimeout_NothingDeleted` |
| path forget ignores the namespace | `Evict_Path_ForgetsAllFourKinds` |

Not mutant-checked (code review): the ledger gate shared by the worker's `Write` / `Tick` and evict (a race, not
deterministically observable), the async (non-sleeping) lock waits, the per-namespace `over_budget` admission check,
the `429` write gate, and the forget fence's `Seq 0` guard (`2c85f5ed`).

## Known limits / questions for the maintainer

- `path` forget does not edit CLI index files (the server owns no index references); it reports them in
  `kept_referenced`. The CLI's own forget (issue 17) removes its index entries.
- `orphans` is admin-only (store-wide); a keyed non-admin cannot clean orphans.
- The forget fence for `path` drops every in-flight encode of the namespace, not only the matching path's.
- Per-namespace figures count ledger rows (what the server wrote for the namespace), not a CLI's offline entries.
- The store registry (`chunkcache.json`) is not rewritten on index-file deletion (advisory; it drops rows of missing
  files on its next load).
