# Client package: `DotLLM.ChunkCache.Client` types, span hash and control-plane client (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Umbrella: `00-umbrella.md`, PR row 1 (client
> package; Tasks 6, 7, 8 may land as one PR or three). Branch: `feature/chunk-cache-client` off `dev` (local only).
> Plan: Phase I Task 6.

**Suggested title:** `chunk-cache client: MIT DotLLM.ChunkCache.Client package (types, span hash, control-plane client)`

## Body

Adds `src/DotLLM.ChunkCache.Client` (package id `DotLLM.ChunkCache.Client`, `net8.0` + `net10.0`), the client half of the
chunk-cache wire convention v1 (spec `2026-11-02-chunk-cache-integration.md` §5, §7.2, §8.2), and its own test project
`tests/DotLLM.ChunkCache.Client.Tests`.

**Licence.** MIT via its own `PackageLicenseExpression`; the rest of the repository stays `GPL-3.0-only`. The package is pure
HTTP plus DTOs: no `ProjectReference` to any `DotLLM.*` project, no package dependency (only the BCL today;
`Microsoft.Extensions.AI.Abstractions` arrives with the MEAI decorator in the follow-up), wire DTOs duplicated rather than
shared with the server. A test enforces it. **For dotllm-97 / the maintainer:** confirm MIT-in-a-GPL-repo, whether a
`NOTICE` / `LICENSE-MIT` file is wanted in the package, the copyright line (inherited `Copyright (c) Konrad Kokosa` from
`Directory.Build.props`), and trusted publishing for a second package id.

What it adds:

- **§8.2 abstractions, verbatim:** `ChunkSpan`, `ChunkSourceInfo`, `IChunkSource`, `ChunkedText`, `LineRange`,
  `IInvalidationSignal`, `ChunkInvalidation`, `InvalidationKind`, `IRecomputePolicy`, `ChunkRequestContext`,
  `ChunkRequestOptions` (`exact` / `prefill` / `summary`), `IChunkCacheClient`.
- **`ExactPolicy`**, the default policy: always the wire defaults, whatever the context (no lossy default).
- **`ChunkHash.Of(text)`**: `"sha256:"` + lowercase hex of the UTF-8 bytes of the decoded text, no normalisation.
- **`ChunkCacheHttpClient(HttpClient, Uri baseUrl, string? apiKey, IChunkIndexQueries? queries = null)`**:
  - `GET /v1/chunk-cache` → `null` on 404 and on a 200 body that is not JSON or lacks `versions: [1]`; 401 / 403 / 5xx throw;
  - `POST /v1/chunk-cache/prewarm` `{"texts":[{id,text,source?}],"max_tokens"?}`: text only, a `select` input resolved
    locally with `include_text` and its hashes never sent;
  - `POST /v1/chunk-cache/evict` `{mode,path?,namespace?,dry_run}` with `mode` / `dry_run` always sent resolved
    (`orphans`, `true`);
  - `POST /v1/chunk-cache/explain` `{"request": <body>}`;
  - `X-API-Key` header; base URL with or without `/v1`; errors as `ChunkCacheRequestException(status, type, code)`.
- **`IChunkIndexQueries` / `CliChunkIndexQueries`** for `select` / `status` (local index operations; no server endpoint):
  run `chunkcache select|status --json ...` through an `IProcessRunner` seam and parse the §7.2 output.
- **DTOs** for capabilities (§5.9) and the §7.2 tool inputs / outputs in a source-generated snake_case
  `ChunkCacheJsonContext` (plus an internal context for request bodies and the error envelope), with nullable properties and
  `[JsonIgnore]` `Effective*` defaults per `CLAUDE.md` (#462), and a `JsonContextDefaultsTests`-style guard for both contexts.
- **Contract fixtures:** byte-exact copies of the v1 wire-contract fixture set in `Fixtures/v1/` (line-ending conversion
  disabled), checked against `fixtures.sha256`, whose own hash is pinned.
- **Docs:** `docs/CHUNK_CACHE_CLIENT.md` (new); `docs/PACKAGING.md` notes the one MIT package. No server flag or behaviour
  changes, so `docs/SERVER.md` is untouched (the server endpoints are Tasks 14 and 16).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `dotnet test tests/DotLLM.ChunkCache.Client.Tests` passes (55 tests); the solution build is warning-free for both
  new projects; `dotnet pack` produces a `DotLLM.ChunkCache.Client` nupkg with `<license type="expression">MIT</license>`,
  its own README and no dependencies.
- [ ] `Package_HasNoDotLlmEngineReference`: no `DotLLM.*` assembly reference, no `ProjectReference`, licence MIT.
- [ ] Hashes match every accepted annotation in `inline.json`, `manifest.json`, `nonascii-crlf.json`,
  `hash-mismatch.json` (span text cut by UTF-8 byte offsets of the decoded part), and a CRLF text misses its LF hash.
- [ ] Capabilities: 404 → `null`; `versions` without 1 → `null`; non-JSON 200 → `null`; 401 / 403 / 500 throw; fixture
  parses field by field.
- [ ] Prewarm never sends a hash; evict defaults to a dry run, sent explicitly.
- [ ] JSON guard covers both new contexts.
- [ ] Every correctness test shown to fail against a mutant (below).
- [ ] CI: `ci.yml` runs only `tests/DotLLM.Tests.Unit/`; the maintainer decides whether to add
  `dotnet test tests/DotLLM.ChunkCache.Client.Tests/` (the plan does not change workflows from our side).

## Mutant evidence

Each mutant was applied one at a time in a `git archive` copy of the branch head, the suite was run, and the mutant
was reverted. 22 applied, 22 killed; the suite was 55/55 again after restoring.

| mutant | killed by |
|---|---|
| M1 404 treated as capable | `Capabilities_404_IsNull` |
| M2 hash in uppercase hex | `Hash_MatchesFixtures` (4), `Hash_KnownAnswers`, `Hash_IsOverUtf8`, `Hash_CrlfPart_*`, `Hash_LfVariant_*` |
| M3 API-key header missing | `ApiKey_SentAsXApiKey`, `ApiKey_Null_SendsNoKeyHeader` |
| M4 hash over UTF-16 | `Hash_MatchesFixtures`, `Hash_IsOverUtf8`, `Hash_KnownAnswers`, ... |
| M5 hash normalises CRLF to LF | `Hash_MatchesFixtures(hash-mismatch.json)`, `Hash_CrlfPart_DoesNotMatchItsLfHash`, `Hash_LfVariant_DiffersFromCrlf` |
| M6 `versions` check skipped | `Capabilities_UnknownVersionOnly_IsNull` (3 cases) |
| M7 401 / 403 / 500 treated as absent | `Capabilities_OtherErrors_Throw` (3 cases) |
| M8 prewarm sends the select hash instead of the text | `Prewarm_SendsTextNeverHashesOnly` |
| M9 prewarm accepts a selected chunk without text | `Prewarm_SelectedChunkWithoutText_ThrowsAndSendsNothing` |
| M10 evict `dry_run` sent unresolved (omitted) | `Evict_Defaults_SentExplicitlyAsDryRunOrphans` |
| M11 `ExactPolicy` returns `auto` when the user opted in | `ExactPolicy_AlwaysExact` |
| M12 CLI non-zero exit ignored | `CliQueries_NonZeroExit_ThrowsWithStderr` |
| M13 CLI `--json` omitted | `CliQueries_PassesArgsAndParsesJson`, `CliQueries_StatusMapsPathAndOmitsUnset` |
| M14 `--solution` / `--directory` swapped | same two |
| M15 `init` initializer on a DTO (`EvictRequest.DryRun = true`) | both JSON-guard theories, `EffectiveDefaults_MatchSpec` |
| M16 explain body not wrapped in `request` | `Explain_PostsRequestBody_ParsesResult` |
| M17 trailing `/v1` not stripped | `BaseUrl_WithOrWithoutV1_ProbesOnePath`, `BaseUrl_WithPathPrefix_IsKept` |
| M18 error `code` not parsed | `Evict_StoreUnavailable_ThrowsWithCode` |
| M19 GPL `ProjectReference` (net10 only, unused, so absent from assembly metadata) | `Package_HasNoDotLlmEngineReference` (csproj check) |
| M20 licence changed to GPL | `Package_HasNoDotLlmEngineReference` |
| M21 one fixture byte changed | `FixtureCopy_MatchesContractSha256`, `Capabilities_ParsesFixture` |
| M22 fixture and its `fixtures.sha256` line changed together | `FixtureList_IsTheContractList` (pinned list hash), `Capabilities_ParsesFixture` |
