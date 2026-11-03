# Server: chunk-cache capabilities, explain and opt-in authentication (draft) — SECURITY-SENSITIVE

> **Status: DRAFT, not filed.** Lane S, plan Task 14. Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and #1542
> (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Security-sensitive:** this is the first authentication code in the dotLLM server (opt-in, chunk-cache surface only);
> please review it as such. Branch `feature/chunk-cache-server`, worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`, on top of the Task 13 fix round (`10149688`):
> `e5e0ea0b` (keys file, `ChunkCacheAuth`), `e23b16f7` (endpoints, caller namespace for inference, per-chunk status),
> `ba271c5c` + `865d51a4` (tests), `bf77ef7d` (docs); security review fix round `dca359d4` (code + tests) and
> `3db1b01c` (docs).
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
  generated, stored or counted in `/metrics`; explain does not probe the prompt cache (nothing is `prefix`). The prompt
  is tokenised once. **Bounds**: at most 2 explains run at once per server (the next gets `429`, `Retry-After: 1`); a
  body over 4 MiB is `413`, with or without a `Content-Length`.
- **CSRF guards** (in place before prewarm / evict add side effects): `Sec-Fetch-Site: cross-site` is `403` on both
  routes whatever the key; explain reads only `Content-Type: application/json` (else `415`), so a browser must preflight.
- **Rate limiting** applies only when it is configured (`--rate-limit-*`; off by default): `/v1/chunk-cache*` is then
  metered like inference (not exempted, documented in `RateLimitMiddleware`). Pre-existing: the limiter's bucket is the
  raw presented key string, so a client that sends a fresh random key per request gets a fresh bucket each time; with
  keys configured such requests only reach the cheap 401 path, and explain's own bounds above apply regardless.

### Authentication (`ChunkCacheAuth`)

- **`--chunk-cache-api-keys <file>`** (needs `--chunk-cache`): one key per line, `<key> [admin] [ns=<namespace>]`;
  a line whose first non-blank character is `#` is a comment (so a key never starts with `#`); each line trimmed. Any
  non-ASCII or control character (also a no-break space) refuses the file at startup with the **line number, never the
  key**; so do repeated keys, unknown or repeated fields, an invalid `ns=` and a file with no key. **Keys shorter than 32
  characters refuse startup** (line number only) unless `--chunk-cache-allow-short-keys`, which accepts them with a
  warning each. `docs/CHUNK_CACHE.md` gives a generation recipe (32 random bytes, base64url). The keys file's keys are
  held as SHA-256 digests only (a presented key string does stay in memory elsewhere: the rate limiter's buckets, the
  request items, the scheduler's fairness key; none is logged).
- **`ns=<namespace>`** (optional): the key maps to that namespace (`ChunkNamespace.IsValid`, not empty, never `default`)
  instead of the derived one. Two keys may share one on purpose (a team; a rotated key keeping its predecessor's
  entries). A named namespace says nothing about the key.
- **Rotation and revocation**: the file is read once at startup and never reloaded, so **revoking a key means a
  restart**. A replacement key starts a new, empty derived namespace and strands the old key's entries, unless both
  lines carry the same `ns=` (the rotation path).
- **With keys**: `X-API-Key` (exactly one value) or `Authorization: Bearer` must be listed, else
  `401 authentication_error` (`WWW-Authenticate: Bearer`). Matching is constant-time
  (`CryptographicOperations.FixedTimeEquals` over the digests of every key, no early exit). Namespace =
  the key's `ns=`, else `ChunkNamespace.ForApiKey(key)`.
- **Without keys**: local callers only, namespace `ChunkNamespace.Default`, else `403 permission_error`. "Local" is
  stricter than the plan's "loopback": a loopback remote address **and** a `localhost` / loopback `Host` header **and** no
  `Origin` header. The server's CORS policy allows any origin, so without the last two a web page in the user's browser
  (directly, or through DNS rebinding) could read the local caller's per-chunk status. An unknown remote address (Unix
  socket, in-memory host) is not local. "Local" still admits every process on the machine (an SSRF-able service too),
  and behind a reverse proxy on the same host every caller looks local: configure keys in both cases.
- **Inference is never refused** (dotLLM inference stays unauthenticated). An annotated inference request from a caller
  the control plane would refuse is served normally, but its chunks are **never looked up** in the store (all misses, no
  warning) and `report: "per_chunk"` gives it the summary. An authenticated caller's `report: "per_chunk"` adds
  `per_chunk: [{id, status, why}]` to the response `chunk_cache` object (blocking, finish-reason chunk, Anthropic
  `message_delta`). The same rule will gate store writes (sole-writer task).
- **Namespaces are server-assigned**: they are hashed into every chunk key (one key's store entries are never hits
  for another's), the body `chunk_cache.namespace` is still ignored unless it equals the caller's own
  (`chunk_namespace_ignored`), and **no response or log line carries a namespace, a key or a key digest**. Namespaces
  **do appear on disk**: in the store's index file names and, with the sole-writer task, in the server ledger. Nothing in
  the auth path logs at all; startup logs the key count and the short-key warnings (line numbers only).
- **Isolation stops at the store.** The prompt (prefix) cache is shared by every caller and knows nothing about
  namespaces: `prefix` status, `usage.cached_tokens` / `timings.cache_n` and time to first token show whether *anyone*
  recently sent the same prompt prefix. That is pre-existing (`cached_tokens` is unauthenticated) and nothing here adds
  to it, but a multi-tenant deployment does not get full isolation (a per-namespace prompt cache is an open item).
  `/metrics` is unauthenticated and its chunk-cache counters are server-wide (aggregate only, no namespace labels).
- **Stack traces**: the server runs `UseDeveloperExceptionPage()` unconditionally (pre-existing; worth an upstream
  look now that a security-sensitive surface sits on it). The chunk-cache handlers catch their own failures.

### Maintainer decision: unsalted `ForApiKey` vs HMAC (needs a decision before multi-tenant use)

`ChunkNamespace.ForApiKey(key)` is `k-` + the first 16 hex digits of an **unsalted** SHA-256 of the key. Derived
namespaces appear in store file names (`index-<chunker>.<model12>.<p8>.<ns>.json`) and, with the sole-writer task, in
the server ledger. So **anyone who can read the store root can test guessed keys offline**, at GPU SHA-256 rates (on the
order of 10^10 guesses per second). The 64-bit truncation does not slow that down, and the name's `k-<16 hex>` is not the
only verifier: the producer tag `<p8>` in index file names and the ledger rows can confirm a guess too. A short or
dictionary key is cheap to recover (hence the 32-character minimum), and a recovered key unlocks that tenant's
chunk-cache surface (and whatever else the operator reused it for). Long random keys, or `ns=` names (which are not
derived from the key), avoid it.

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
- `per_chunk` items: `why` is the §5.8 code that dropped the annotation, or null (ruling 55), not prose.
- `store` is always an object; without `--chunk-store` it carries `"configured": false` (ruling 52).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `docs/SERVER.md` (flag, Security subsection, metering note) and
      `docs/CHUNK_CACHE.md` updated; `Closes #N` closed by hand; flagged security-sensitive in the PR.
- [ ] `--chunk-cache-api-keys` and `--chunk-cache-allow-short-keys` documented and tested on both option paths, refused
      without `--chunk-cache` (the override also without a keys file); an unusable path is a clean startup error.
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
      without the key, keys under 32 characters refused (warned with the override), duplicates / unknown fields / bad
      `ns=` / empty refused (`KeysFile_TrimsKeys_RefusesNonAscii_WarnsShortKeys`); `ns=` maps keys to a named,
      shareable namespace (`KeysFile_NsField_MapsKeyToNamedNamespace`).
- [ ] `store.configured: false` without a store, absent with one (`Capabilities_StoreConfiguredFalse_WithoutStore`).
- [ ] CSRF: explain without `application/json` is 415; `Sec-Fetch-Site: cross-site` is 403 on both routes
      (`ControlPlane_RequiresJson_RefusesCrossSite`).
- [ ] Explain bounded: 2 concurrent (429 + `Retry-After`), 4 MiB body (413, sized and chunked), every slot released
      (`Explain_ConcurrencyCapped_429_BodyLimited_413`); `Host` with a port is still local; a parse/caller namespace
      mismatch is refused (`ExchangeBegin_NamespaceMismatch_Refused`).
- [ ] A non-admin sees its own namespace's figures only, not store-wide totals (`NonAdmin_CapabilitiesShowOwnNamespaceFiguresOnly`).
- [ ] Both routes metered when rate limiting is configured: second request under a 1-per-minute policy is 429
      (`Endpoints_AreRateLimited`).
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

### Security review fix round

`git archive` copy of `3db1b01c`, same filter; baseline 223 / 223. Red evidence for the fix round: written test-first;
against API stubs (no behaviour) 8 of the 19 tests failed. **17 new mutants, all killed; the 26 + L0 above re-run against
the new code, all killed** (L0 now fails 17).

| mutant | change | killed by |
|---|---|---|
| F1 | short keys accepted without the override | `KeysFile_TrimsKeys_…` |
| F1b | minimum key length 16 | `KeysFile_TrimsKeys_…` (31-character key) |
| F1c | override ignored (short keys always refused) | `KeysFile_TrimsKeys_…`, `NamespaceNeverIn…` |
| F1d | `--chunk-cache-allow-short-keys` accepted without a keys file | `KeysFile_TrimsKeys_…` |
| F2 | `ns=` ignored (derived namespace always) | `KeysFile_NsField_MapsKeyToNamedNamespace` |
| F2b | `ns=` not validated | `KeysFile_TrimsKeys_…` |
| F2c | a second `ns=` overrides the first | `KeysFile_TrimsKeys_…` |
| F3 | explain slot never released | `Explain_ConcurrencyCapped_…` and 3 more |
| F3b | explain concurrency not capped | `Explain_ConcurrencyCapped_429_BodyLimited_413` |
| F4 | explain body not limited | `Explain_ConcurrencyCapped_…` |
| F4b | only `Content-Length` checked (chunked bodies unbounded) | `Explain_ConcurrencyCapped_…` |
| F5 | explain content type not checked | `ControlPlane_RequiresJson_RefusesCrossSite` |
| F6 | cross-site not refused on explain | `ControlPlane_RequiresJson_…` |
| F6b | cross-site not refused on capabilities | `ControlPlane_RequiresJson_…` |
| F7 | `store.configured` never written | `Capabilities_StoreConfiguredFalse_WithoutStore`, `Capabilities_MatchesFixtureShape` |
| F8 | `ChunkCacheExchange.Begin` accepts a parse/caller namespace mismatch | `ExchangeBegin_NamespaceMismatch_Refused` |
| F9 | `why` omitted when null (ruling 55) | `Explain_PerChunkOnlyForOwnNamespace` |

Not mutant-checked: the clean-error wrap around an unusable keys path (on .NET the inputs the test can produce already
throw `ArgumentException`, so the wrap cannot be told apart) and the `BadHttpRequestException` → 413/400 mapping
(Kestrel's own 30 MB limit is above explain's 4 MiB, so the test reaches explain's own 413 first); both are code-review
items.
