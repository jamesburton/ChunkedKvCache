# Server: chunk-cache capabilities, explain and opt-in authentication (draft) — SECURITY-SENSITIVE

> **Status: DRAFT, not filed.** Lane S, plan Task 14. Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and #1542
> (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Security-sensitive:** this is the first authentication code in the dotLLM server (opt-in, chunk-cache surface only);
> please review it as such. Branch `feature/chunk-cache-server`, worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`, on top of the Task 13 fix round (`10149688`):
> `e5e0ea0b` (keys file, `ChunkCacheAuth`), `e23b16f7` (endpoints, caller namespace for inference, per-chunk status),
> `ba271c5c` + `865d51a4` (tests), `bf77ef7d` (docs).
> **Packaging:** it builds on the Tasks 10 + 11 + 13 PR (issue 13) and can ship as its own PR right after it, or ride
> with it; without it a `--chunk-cache` server has no capabilities probe, so the client (issues 06 / 08) never annotates.

## Title

Server: `GET /v1/chunk-cache` capabilities, `POST /v1/chunk-cache/explain`, and opt-in API-key authentication for the chunk-cache surface (behind `--chunk-cache`)

## Body

Refs #1543, #1542.

The chunk-cache wire convention (issues 10, 11, 13) runs `exact` / `shadow` behind `--chunk-cache`. A client needs to
know whether a server speaks it (the capabilities probe: anything but a 2xx means "strip the annotations"), a tool needs
a dry run of a request (explain), and per-chunk store answers need a caller identity: "is this text stored?" is a
membership probe on cached source code (spec §10). dotLLM has no authentication today (`docs/SERVER.md` § Security).
This adds the smallest opt-in authentication that closes the probe, scoped to the chunk-cache surface only.

**Everything sits behind `--chunk-cache` (off by default).** With the flag off the two routes are not mapped (the usual
bare 404 for every method) and nothing else changes.

### Routes

- **`GET /v1/chunk-cache`**: the contract's `capabilities.json` shape (`versions [1]`, the five policies,
  `selectors ["chunk_starts"]`, `wire_chunkers ["symbol-512"]`, `auto_validated []`, `model`, `store`,
  `max_chunks_per_request`), plus the chunk-key identity in `model`: `id` (the content model id,
  `GgufIdentity.ModelId`, not the served name), `id_kind: "sampled"`, `tokenizer_id`, `producer` (the key of no tokens
  in **the caller's** namespace; a server-backed `chunkcache` names its index from `model.id` and `model.producer`),
  `quantization`, `backend`, `kv_dtype`, `rope {dim, theta, type}`. These are exactly the fingerprint inputs whose
  disagreement makes a CLI-built store silently miss (issue 13, "silent disagreements"). Unsupported model: `id` null,
  `supported: false`, `reason: "chunk_model_unsupported"`. `store` figures are the caller's own namespace's and are all
  0 until the server keeps a ledger (the sole-writer task); no caller sees store-wide figures yet.
- **`POST /v1/chunk-cache/explain`**: body `{"request": <a /v1/chat/completions body>}` and nothing else (contract
  ruling 15). Any other top-level field (a hash list), a non-object `request`, a body that is not JSON or a `request` the
  chat endpoint could not bind is `400 invalid_request_error`: there is no hash lookup, the text must be sent. The
  request is validated, parsed in the caller's namespace, rendered by the chat endpoint's own render (`TryRender`, a pure
  extraction from `ChatCompletionEndpoint`), checked against the context length, then located, token-checked and looked
  up exactly as inference would. Returns `policy_would_apply`, `reason`, `chunks[{id, status, why}]` (authenticated
  caller only, own namespace), `counts`, `predicted_ms {reuse, full_prefill}` (the shadow plan's cost-model prediction)
  and `warnings` (codes). A strict request's defect is returned exactly as the chat endpoint returns it. Nothing is
  generated, stored or counted in `/metrics`; explain does not probe the prompt cache (nothing is `prefix`).
- Both routes are **rate-limited like inference** (every `/v1/` path is metered unless exempted; these are deliberately
  not exempt, documented in `RateLimitMiddleware`).

### Authentication (`ChunkCacheAuth`)

- **`--chunk-cache-api-keys <file>`** (needs `--chunk-cache`): one key per line, `<key>` or `<key> admin`, `#`
  comments, each line trimmed. Any non-ASCII or control character (also a no-break space) refuses the file at startup
  with the **line number, never the key**; so do repeated keys, an unknown role word and a file with no key. Keys shorter
  than 16 characters start with a warning naming the line. Only SHA-256 digests are kept.
- **With keys**: `X-API-Key` (exactly one value) or `Authorization: Bearer` must be listed, else
  `401 authentication_error` (`WWW-Authenticate: Bearer`). Matching is constant-time
  (`CryptographicOperations.FixedTimeEquals` over the digests of every key, no early exit). Namespace =
  `ChunkNamespace.ForApiKey(key)`.
- **Without keys**: local callers only, namespace `ChunkNamespace.Default`, else `403 permission_error`. "Local" is
  stricter than the plan's "loopback": a loopback remote address **and** a `localhost` / loopback `Host` header **and** no
  `Origin` header. The server's CORS policy allows any origin, so without the last two a web page in the user's browser
  (directly, or through DNS rebinding) could read the local caller's per-chunk status. An unknown remote address (Unix
  socket, in-memory host) is not local. Behind a reverse proxy on the same host every caller looks local: configure keys.
- **Inference is never refused** (dotLLM inference stays unauthenticated). An annotated inference request from a caller
  the control plane would refuse is served normally, but its chunks are **never looked up** in the store (all misses, no
  warning) and `report: "per_chunk"` gives it the summary. An authenticated caller's `report: "per_chunk"` adds
  `per_chunk: [{id, status, why}]` to the response `chunk_cache` object (blocking, finish-reason chunk, Anthropic
  `message_delta`). The same rule will gate store writes (sole-writer task).
- **Namespaces are server-assigned and never leave the server**: they are hashed into every chunk key (one key's
  entries are never hits for another's), the body `chunk_cache.namespace` is still ignored unless it equals the
  caller's own (`chunk_namespace_ignored`), and no response or log line carries a namespace, a key or a key digest.
  Nothing in the auth path logs at all; startup logs the key count and the short-key warnings (line numbers only).

### Maintainer decision: unsalted `ForApiKey` vs HMAC (needs a decision before multi-tenant use)

`ChunkNamespace.ForApiKey(key)` is `k-` + the first 16 hex digits of an **unsalted** SHA-256 of the key. Namespaces
appear in store file names (`index-<chunker>.<model12>.<p8>.<ns>.json`) and, with the sole-writer task, in the server
ledger. So **anyone who can read the store root can test guessed keys offline**, at SHA-256 speed; a short or
dictionary key is cheap to recover (hence the startup warning), and a recovered key unlocks that tenant's chunk-cache
surface (and whatever else the operator reused it for).

The alternative is `HMAC-SHA256(server secret, key)` with the secret in server configuration, outside the store root.
Offline guessing then needs the secret too. The costs:

- rotating or losing the secret, or changing the derivation at all, re-keys every namespace: a key-scheme bump
  (`chunk-key/v5`) that orphans every stored entry and index;
- a server-backed `chunkcache` can no longer derive its own namespace from its key to name its index file (the server
  would have to tell it, or index names would have to drop the namespace part);
- one more secret to provision and back up.

v1 ships the unsalted form with the risk documented (`docs/CHUNK_CACHE.md`, "Authentication and namespaces"): treat
the store root like the repository (same ACLs, not synced, not world-readable), use long random keys. **Question for
the maintainer:** keep it, or switch to HMAC before any shared (multi-tenant) deployment?

### Other decisions in this change

- Explain is OpenAI-surface only in v1 (ruling 19; `chunkcache select --server` sends OpenAI string content).
- Admin keys are parsed now (`<key> admin`) but grant nothing yet: store-wide figures and cross-namespace evict come with
  the store tasks.
- `per_chunk` items: `why` is the §5.8 code that dropped the annotation (machine-readable), not prose.
- With no `--chunk-store`, `store` is still the object with zeros (the shipped client parses `store` as an object; contract
  ruling 44 says `store: false`; see the ruling question in the task report).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `docs/SERVER.md` (flag, Security subsection, metering note) and
      `docs/CHUNK_CACHE.md` updated; `Closes #N` closed by hand; flagged security-sensitive in the PR.
- [ ] `--chunk-cache-api-keys` documented and tested on both option paths, refused without `--chunk-cache`.
- [ ] Flag off: `GET` and `POST` on both routes are the same bare 404 as an unmapped path (`FlagOff_404`); the existing
      flag-off byte-identity tests still pass.
- [ ] Capabilities match `capabilities.json` (same top-level keys, lists, store keys) and expose model id, tokenizer id,
      producer of the caller's namespace, quantisation, backend, K/V dtype, RoPE (`Capabilities_MatchesFixtureShape`).
- [ ] No keys: non-loopback 403 on both routes, inference still 200 without per-chunk (`NoKeysConfigured_NonLoopback_403`);
      loopback admitted, `Origin` or a foreign `Host` refused (`EnabledWithoutKeys_LoopbackOnly`).
- [ ] Keys: no key, unknown key, prefix, extension, other case, `Basic`, empty bearer → 401 with `WWW-Authenticate`;
      listed key via either header → 200 (`KeysConfigured_MissingKey_401`); namespace = `ForApiKey(key)`, two values of
      `X-API-Key` are no key (`KeysConfigured_ValidKey_NamespaceFromKey`).
- [ ] Two keys on one store: a chunk stored under A is a hit for A and a miss for B in explain and in shadow plan
      counts, also when B names A's namespace in the body (`TwoKeys_CannotSeeOrEvictEachOthersEntries`; evict is the
      store task's).
- [ ] Explain per-chunk status in the caller's own namespace, `why` for ignored annotations, counts, prediction
      (`Explain_PerChunkOnlyForOwnNamespace`); hash lists and other bodies 400, never 500; strict defect identical to
      the chat endpoint's (`Explain_HashListBody_Rejected`).
- [ ] No namespace, key or key digest in any response body or log line (console and `ILogger`, every level) across
      capabilities, 401, explain, a 400 explain, blocking and streaming inference (`NamespaceNeverInResponseBodiesOrLogs`).
- [ ] Keys file: trimmed, comments, admin role, non-ASCII / control / no-break space refused with the line number and
      without the key, short keys warned, duplicates / unknown role / empty refused (`KeysFile_TrimsKeys_RefusesNonAscii_WarnsShortKeys`).
- [ ] A non-admin sees its own namespace's figures only, not store-wide totals (`NonAdmin_CapabilitiesShowOwnNamespaceFiguresOnly`).
- [ ] Both routes metered: second request under a 1-per-minute policy is 429 (`Endpoints_AreRateLimited`).
- [ ] Unauthenticated annotated inference: summary for `per_chunk`, no store lookups; key holder gets `per_chunk`, also
      on the streaming finish chunk (`ReportPerChunk_UnauthenticatedGetsSummary`).
- [ ] No new `JsonSerializerContext`: the new DTOs are in `ServerJsonContext`, have no init-property initializers and are
      covered by `JsonContextDefaultsTests`.
- [ ] Correctness tests shown to fail against mutants (table below, also in the PR body).

## Mutant evidence

Run in a `git archive` copy of `865d51a4` (never the live worktree), `--filter FullyQualifiedName~Server.ChunkCache`,
Release, CPU, `DOTLLM_SKIP_VULKAN=1`, `-m:2`. Baseline 218 / 218. **26 mutants + L0, all killed** on the first run (L0's
first attempt did not compile, a nullable error in the stub itself; fixed and re-run). Red evidence: L0, a stub with no
routes, every caller authenticated in the default namespace, no keys-file checks and no per-chunk, fails 13 of the 14
new tests. The plan's named mutants are T1 (loopback check skipped), T2 (per-chunk leaked to anonymous), T3 / T3b / T3c
(key compare not exact), T4 (namespace logged), T5 (keys not trimmed), T6 (store-wide figures to a non-admin), T7 /
T3c (shared namespace, key ignored).

| mutant | change | killed by |
|---|---|---|
| L0 | stub: no routes, everyone authenticated in the default namespace, no keys-file checks, no per-chunk | 13 of 14 new tests |
| T1 | loopback check skipped | `EnabledWithoutKeys_LoopbackOnly`, `NoKeysConfigured_NonLoopback_403` |
| T1b | remote address not checked (Host and Origin only) | same two |
| T1c | `Origin` ignored | `EnabledWithoutKeys_LoopbackOnly` |
| T1d | `Host` ignored (DNS rebinding) | `EnabledWithoutKeys_LoopbackOnly` |
| T1e | unknown remote address treated as local | `EnabledWithoutKeys_LoopbackOnly` |
| T2 | per-chunk leaked to anonymous (report and explain) | `Explain_PerChunkOnlyForOwnNamespace`, `NoKeysConfigured_NonLoopback_403`, `ReportPerChunk_UnauthenticatedGetsSummary` |
| T3 | key compare case-insensitive | `KeysConfigured_MissingKey_401` |
| T3b | key compare on the first 16 characters only | `KeysConfigured_MissingKey_401`, `KeysFile_…` |
| T3c | key ignored: any presented key admitted | `KeysConfigured_MissingKey_401`, `KeysConfigured_ValidKey_NamespaceFromKey` |
| T4 | namespace logged on every authenticated call | `NamespaceNeverInResponseBodiesOrLogs` |
| T4b | namespace echoed in the capabilities body | `Capabilities_MatchesFixtureShape`, `NamespaceNeverIn…` |
| T5 | keys not trimmed (the raw line is the key) | `KeysFile_TrimsKeys_RefusesNonAscii_WarnsShortKeys` |
| T6 | store-wide figures shown to a non-admin | `NonAdmin_CapabilitiesShowOwnNamespaceFiguresOnly` |
| T7 | shared namespace (every key in the default namespace) | `TwoKeys_CannotSeeOrEvictEachOthersEntries`, `Explain_PerChunk…`, `KeysConfigured_ValidKey_…` |
| T8 | unauthenticated inference callers looked up in the store | `ReportPerChunk_UnauthenticatedGetsSummary` |
| T9 | inference ignores the caller namespace | `TwoKeys_CannotSeeOrEvictEachOthersEntries` |
| T10 | explain accepts extra fields (a hash list rides along) | `Explain_HashListBody_Rejected` |
| T11 | routes mapped with the flag off (404 from the handler, 405 on the wrong method) | `FlagOff_404` |
| T12 | chunk-cache routes exempt from rate limiting | `Endpoints_AreRateLimited` |
| T13 | non-ASCII keys accepted | `KeysFile_…` |
| T14 | short keys not warned | `KeysFile_…`, `NamespaceNeverIn…` |
| T15 | two `X-API-Key` values: the first is used | `KeysConfigured_ValidKey_NamespaceFromKey` |
| T16 | keys-file error echoes the offending line | `KeysFile_…` |
| T17 | duplicate keys accepted | `KeysFile_…` |
| T18 | producer computed in the default namespace for every caller | `KeysConfigured_ValidKey_NamespaceFromKey` |
