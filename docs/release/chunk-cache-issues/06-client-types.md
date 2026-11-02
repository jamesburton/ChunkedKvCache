# Client package: `DotLLM.ChunkCache.Client` types, span hash and control-plane client (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Umbrella: `00-umbrella.md`, PR row 1 (client
> package; Tasks 6, 7, 8 may land as one PR or three). Branch: `feature/chunk-cache-client` off `dev` (local only;
> commits `45c70535`, review round `59c4aaa9`). Plan: Phase I Task 6. Contract: `docs/contracts/chunk-cache-v1/`,
> rulings 1-18.

**Suggested title:** `chunk-cache client: MIT DotLLM.ChunkCache.Client package (types, span hash, control-plane client)`

## Body

Adds `src/DotLLM.ChunkCache.Client` (package id `DotLLM.ChunkCache.Client`, `net8.0` + `net10.0`, `IsAotCompatible`), the
client half of the chunk-cache wire convention v1 (spec `2026-11-02-chunk-cache-integration.md` §5, §7.2, §8.2), and its
own test project `tests/DotLLM.ChunkCache.Client.Tests`.

**Licence.** MIT; the rest of the repository stays `GPL-3.0-only`. The terms are in `src/DotLLM.ChunkCache.Client/LICENSE`
(packed into the nupkg), every source file there starts with `// SPDX-License-Identifier: MIT`, and the csproj sets
`PackageLicenseExpression` MIT. The package is pure HTTP plus DTOs: no `ProjectReference` to any `DotLLM.*` project, no
package dependency (only the BCL today; `Microsoft.Extensions.AI.Abstractions` arrives with the MEAI decorator in the
follow-up), wire DTOs duplicated rather than shared with the server. Tests enforce all of this.

**Questions for dotllm-97 / the maintainer (licence and identity; the PR waits on them):**
- MIT inside a GPL-3.0 repository: confirm, and whether a repository-level `NOTICE` is wanted.
- **Copyright holder.** The MIT `LICENSE` uses the repository's existing convention, `Copyright (c) Konrad Kokosa` (the
  `<Copyright>` in `Directory.Build.props`), because we do not know who the holder of this package should be. Please
  confirm or give the right line; the file says the holder is an open question.
- The nupkg also inherits `<Authors>Konrad Kokosa</Authors>` and the engine `icon.png` from `Directory.Build.props`: keep,
  or override for this package?
- Trusted publishing for a second package id, if it is ever pushed to nuget.org (today it is not; see Release behaviour).

What it adds:

- **§8.2 abstractions, verbatim:** `ChunkSpan`, `ChunkSourceInfo`, `IChunkSource`, `ChunkedText`, `LineRange`,
  `IInvalidationSignal`, `ChunkInvalidation`, `InvalidationKind`, `IRecomputePolicy`, `ChunkRequestContext`,
  `ChunkRequestOptions` (`exact` / `prefill` / `summary`), `IChunkCacheClient`.
- **`ExactPolicy`**, the default policy: always the wire defaults, whatever the context (no lossy default).
- **`ChunkHash.Of(text)`**: `"sha256:"` + lowercase hex of the UTF-8 bytes of the decoded text, no normalisation; a lone
  surrogate hashes as U+FFFD (ruling 17). One code path for both target frameworks.
- **`ChunkCacheHttpClient(HttpClient, Uri baseUrl, string? apiKey, IChunkIndexQueries? queries = null)`**:
  - `GET /v1/chunk-cache` → `null` on 404 and on a 200 body that is not JSON or lacks `versions: [1]`; 401 / 403 / 5xx throw
    with status, type and code;
  - **`ChunkCacheProbe.ProbeAsync` / `ChunkCacheProbeResult`**: the fail-closed form. Ruling 16: any exception or non-2xx
    from the probe (401, 403, 5xx, timeout, 404) means "strip annotations and send a plain request". `ProbeAsync` never
    throws for a server or transport failure; only the caller's own cancellation propagates. Task 8's installer uses it;
  - `POST /v1/chunk-cache/prewarm` `{"texts":[{id,text,source?:{path}}],"max_tokens"?}`: text only; a `select` input is
    resolved locally with `include_text` and its hashes are never sent. `source` is `{path}` only and advisory (ruling 14);
  - `POST /v1/chunk-cache/evict` `{mode,path?,namespace?,dry_run}` with `mode` / `dry_run` always sent resolved
    (`orphans`, `true`); `EvictResult.DryRun` is nullable (an omitted field never reads as "deleted");
  - `POST /v1/chunk-cache/explain` `{"request": <body>}` (ruling 15);
  - `X-API-Key` header (an empty key sends none); base URL with or without `/v1`; base-URL user info dropped; every
    failure, including a 2xx body that is not the expected JSON, is a `ChunkCacheRequestException`.
- **`IChunkIndexQueries` / `CliChunkIndexQueries`** for `select` / `status` (local index operations; no server endpoint):
  run `chunkcache select|status --json ...` through an `IProcessRunner` seam and parse the §7.2 output.
  - A bare executable name is resolved against **fully qualified `PATH` entries only**; relative entries and the working
    directory are never searched (a harness's working directory is usually an untrusted repository). A relative path with a
    directory part is rejected.
  - Per-call **timeout** (default 5 minutes, configurable, infinite allowed); expiry kills the started process tree and
    throws `ChunkCacheCliException` with an inner `TimeoutException`.
  - `paths` / `exclude` values containing a comma or leading / trailing whitespace are **rejected** (today's CLI splits and
    trims list values; ruling 18) until Task 17 adds a non-splitting form.
- **DTOs** for capabilities (§5.9) and the §7.2 tool inputs / outputs in a source-generated snake_case
  `ChunkCacheJsonContext` (plus an internal context for request bodies and the error envelope), with nullable properties and
  `[JsonIgnore]` `Effective*` defaults per `CLAUDE.md` (#462), and a `JsonContextDefaultsTests`-style guard for both contexts.
- **Contract fixtures:** byte-exact copies of the v1 wire-contract fixture set in `Fixtures/v1/` (line-ending conversion
  disabled), checked against `fixtures.sha256`, whose own hash is pinned.
- **Docs:** `docs/CHUNK_CACHE_CLIENT.md` (new); `docs/PACKAGING.md` (the one MIT package and its release behaviour). No
  server flag or behaviour changes, so `docs/SERVER.md` is untouched (the server endpoints are Tasks 14 and 16).

## Release behaviour (changes with this PR)

- `release.yml`'s `pack-nuget` runs `dotnet pack` over the whole repository, so the client now packs.
- `create-release` copies every `*.nupkg` / `*.snupkg` into the GitHub release assets and attests them, and `ci.yml` calls
  the release pipeline on every green push to the fork's `dev`. **So every dev prerelease will carry
  `DotLLM.ChunkCache.Client.<version>.nupkg` as an asset.**
- It is **not** pushed to nuget.org: `push-nuget` pushes only `$DOTLLM_TOOL_PACKAGE_ID`.
- CI builds the `net8.0` target (`dotnet build`) but runs only `tests/DotLLM.Tests.Unit/`; adding
  `dotnet test tests/DotLLM.ChunkCache.Client.Tests/` is the maintainer's call (we change no workflow).

## Maintainer action: run the client tests in CI (separate small PR)

`ci.yml` runs only `tests/DotLLM.Tests.Unit` and `tests/DotLLM.Tests.Integration`, so `tests/DotLLM.ChunkCache.Client.Tests`
(the MIT client package's whole suite) never runs in CI; its pass counts are local only. We change no workflow. We ask
the maintainer to add, in a separate small PR (or in this one if preferred), one step next to the unit tests:

```yaml
      - name: Chunk-cache client tests
        run: dotnet test tests/DotLLM.ChunkCache.Client.Tests -c Release --filter "Category!=Benchmark" --blame-hang-timeout 5m
```

The filter follows the repository's convention: the client's timing test (`Overhead_Under5ms`) is
`Category=Benchmark` and is skipped outside Release anyway.

## Requirements on the CLI (Task 17) that this client depends on

The `select` / `status` mapping only works once the `chunkcache` CLI provides these (contract ruling 18):

1. **UTF-8 JSON on stdout** in `--json` mode, independent of the console code page (set `Console.OutputEncoding` to UTF-8
   or keep STJ's ASCII-escaping encoder). The client reads stdout as UTF-8; mangled non-ASCII chunk text would make prewarm
   encode the wrong text (a silent miss). Task 17 adds a real-process non-ASCII test.
2. **API key from the environment**: `CHUNKCACHE_API_KEY`, never argv (argv shows in process listings). Without it, the
   CLI's `stored` lookup against a keyed server gets 401.
3. **`--server <url>`** on `select` and `status` (new option).
4. **No `--model` requirement** for `select` / `status` (today's `select` requires `--model`; the tokenizer comes from the
   server or the index).
5. **A non-splitting, repeatable list option** for `--path` / `--exclude` (today every list value is split on `,` and
   trimmed, so `src/**/*.{cs,razor}` becomes two broken patterns). When it lands, the client's comma rejection is removed.
6. The option names the client already emits: `--json`, `--store`, `--solution` / `--directory`, `--chunker`, `--path`,
   `--exclude`, `--symbol`, `--hops`, `--since`, `--budget`, `--include-text`, `--order`, `--list-missing`.

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `dotnet test tests/DotLLM.ChunkCache.Client.Tests` passes (90 tests); the build is warning-free for both new projects
  (trim / AOT analyzers on); `dotnet pack` produces a `DotLLM.ChunkCache.Client` nupkg with
  `<license type="expression">MIT</license>`, its own README and LICENSE, and no dependencies.
- [ ] `Package_HasNoDotLlmEngineReference` and `ClientSources_CarryMitLicenseAndSpdxHeaders` pass.
- [ ] Hashes match every accepted annotation in `inline.json`, `manifest.json`, `nonascii-crlf.json`,
  `hash-mismatch.json`; a CRLF text misses its LF hash; a lone surrogate hashes as U+FFFD.
- [ ] Capabilities: 404 / no v1 / non-JSON → `null`; 401 / 403 / 500 throw; `ProbeAsync` is not capable for all of those plus
  transport errors and HTTP timeouts, and propagates only the caller's cancellation.
- [ ] Prewarm never sends a hash, and `source` is `{path}` only; evict defaults to a dry run, sent explicitly.
- [ ] CLI: PATH-only resolution (working directory and relative entries never searched), timeout, comma / whitespace
  rejection, start failure wrapped.
- [ ] JSON guard covers both new contexts.
- [ ] Every correctness test shown to fail against a mutant (below).
- [ ] The licence questions above are answered.
- [ ] The maintainer has decided on the CI step above (`dotnet test tests/DotLLM.ChunkCache.Client.Tests -c Release --filter "Category!=Benchmark"`).

## Mutant evidence

Each mutant was applied in a `git archive` copy of the branch head (`59c4aaa9`), the suite was run
(`dotnet test --blame-hang-timeout 90s`), and the mutant was reverted. **42 applied, 42 killed**; the suite was 90/90 after
restoring. The script is `mutants.py`. Its logs are `mutants.log` (M1-M22, N1-N18), `mutants-n19.log`, and
`mutants-round1.log` (the first run, M1-M21 on `45c70535`); M22 there was run by hand and now has its own log line.

| mutant | killed by |
|---|---|
| M1 404 treated as capable | `Capabilities_404_IsNull`, `Probe_ErrorStatus_IsNotCapable` |
| M2 hash in uppercase hex | `Hash_MatchesFixtures` (4), `Hash_KnownAnswers`, `Hash_IsOverUtf8`, `Hash_CrlfPart_*`, `Hash_LfVariant_*`, `Hash_LoneSurrogate_*` |
| M3 API-key header missing | `ApiKey_SentAsXApiKey`, `ApiKey_Null_SendsNoKeyHeader`, `ApiKey_Empty_SendsNoHeader` |
| M4 hash over UTF-16 | `Hash_MatchesFixtures`, `Hash_IsOverUtf8`, `Hash_KnownAnswers`, ... |
| M5 hash normalises CRLF to LF | `Hash_MatchesFixtures(hash-mismatch.json)`, `Hash_CrlfPart_DoesNotMatchItsLfHash`, `Hash_LfVariant_DiffersFromCrlf` |
| M6 `versions` check skipped | `Capabilities_UnknownVersionOnly_IsNull` (3 cases) |
| M7 401 / 403 / 500 treated as absent | `Capabilities_OtherErrors_Throw` (3), `Probe_ErrorStatus_IsNotCapable` (`Failure` expected) |
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
| N1 relative `PATH` entries (`.`, `bin`) searched | `RelativePathEntries_AreIgnored_PlantedCliInWorkingDirectoryNeverRuns` |
| N2 working directory searched first | `WorkingDirectory_NotSearched` |
| N3 relative path with a directory accepted | `RelativePathWithDirectory_Rejected` (3) |
| N4 bare name handed to the runner unresolved | `BareName_ResolvedOnPath_RunnerGetsAbsolutePath` |
| N5 timeout never armed | `Timeout_CancelsRunnerAndThrows` hangs; the run is aborted by `--blame-hang-timeout` (non-zero exit) |
| N6 comma check removed | `ListValues_TheCliWouldSplitOrTrim_Rejected` (comma cases) |
| N7 whitespace check removed | `ListValues_TheCliWouldSplitOrTrim_Rejected` (whitespace cases) |
| N8 probe swallows the caller's cancellation | `Probe_CallerCancellation_Propagates` |
| N9 probe: 404 counted as capable | `Probe_ErrorStatus_IsNotCapable(404)` |
| N10 prewarm `source` dropped | `Prewarm_SourceCarriesPathOnly`, `Prewarm_SendsTextNeverHashesOnly` |
| N11 lone surrogate throws (strict UTF-8 encoder) | `Hash_LoneSurrogate_IsReplacementCharacter` |
| N12 empty API key sent | `ApiKey_Empty_SendsNoHeader` |
| N13 base-URL user info kept | `BaseUrlUserInfo_NotInMessagesOrRequests` |
| N14 2xx non-JSON body not wrapped | `Post_BadSuccessBody_ThrowsRequestException` (2 cases) |
| N15 process start failure not wrapped | `ProcessRunner_MissingExecutable_ThrowsCliException` |
| N16 reflection-based `JsonSerializer.Serialize<object>` added | build fails: IL2026 / IL3050 (the `IsAotCompatible` analyzers are live) |
| N17 LICENSE not packed | `Package_HasNoDotLlmEngineReference` (csproj check) |
| N18 SPDX header missing on one file | `ClientSources_CarryMitLicenseAndSpdxHeaders` |
| N19 `EvictResult.DryRun` back to non-nullable `bool` | test build fails: xUnit2002 on `Assert.Null(r.DryRun)` (a compile-time guard rather than a runtime one) |
