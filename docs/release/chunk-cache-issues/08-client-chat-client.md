# Client package: annotating pipeline (span registry, MEAI decorator, HTTP body handler) (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Umbrella: `00-umbrella.md`, PR row 1 (client
> package; Tasks 6, 7, 8 may land as one PR or three). Branch: `feature/chunk-cache-client` off `dev` (local only;
> commits `57eab36d` code, `9f0d5bb1` / `2efe642e` tests, `df707d92` docs, `cd044cc6` perf, `81ac4061` review round,
> on Task 6's `59c4aaa9`). Plan: Phase I Task 8. Contract:
> `docs/contracts/chunk-cache-v1/`, rulings 1-22. Depends on: the Task 6 issue (`06-client-types.md`).

**Suggested title:** `chunk-cache client: annotating pipeline (ChunkAnnotatingChatClient + ChunkCacheBodyHandler)`

## Body

Adds the request half of the chunk-cache client (spec `2026-11-02-chunk-cache-integration.md` §5.1-5.3, §5.7-5.9, §8.3,
§12.1): a harness registers the chunk spans of the file reads it returns, and every chat request to a chunk-capable dotLLM
server carries a top-level `chunk_cache` manifest (placement B) for the spans that are really in the serialised body. The
response's `chunk_cache` report comes back on the `ChatResponse`. Without capabilities nothing changes on the wire.

**New dependency.** `Microsoft.Extensions.AI.Abstractions` **10.10.0** (MIT, pinned in `Directory.Packages.props`), for
`DelegatingChatClient`. On `net8.0` it brings `System.Text.Json` 10.0.x transitively. The test project also references
`Microsoft.Extensions.AI.OpenAI` 10.10.0 (MIT; test-only) so the pipeline tests run against the body the real OpenAI bridge
serialises. Still no `ProjectReference`, no engine assembly; the package test allows exactly that one package.

What it adds (`src/DotLLM.ChunkCache.Client/`):

- **`ChunkSpanRegistry : IChunkSpanRegistry`**: part text → spans, keyed by **text** (the decorator runs below the
  invocation loop and never sees tool-call ids). Thread-safe LRU bounded by count (4,096 texts) and size (32 Mi UTF-16
  chars = 64 MiB; a single larger text is not kept); longest registered prefix wins for a text with an appended suffix
  (hook context). Range-checked at registration.
- **`ChunkAnnotatingChatClient(inner, registry, policy[, ChunkAnnotatingOptions])`** (`DelegatingChatClient`):
  - finds registered parts among `TextContent` and string `FunctionResultContent` results, decides the request options,
    and hands both to the HTTP layer through **`ChunkManifestScope`** (AsyncLocal; a snapshot, so retries are identical);
  - **no lossy default**: `ExactPolicy` by default, and anything but `exact` / `shadow` is sent as `exact` unless the
    harness sets `ChunkSessionFlags.UserOptedIntoApproximation` for the call;
  - lifts the report into `ChatResponse.AdditionalProperties["chunk_cache"]` (streaming: onto an update; MEAI's
    `ToChatResponse` moves it to the message, where `ChunkCacheReport.TryGet` also looks) and raises `CallCompleted`
    with the handler's outcome (spans sent / dropped and why: the spec 12.5 plumbing-loss metric);
  - idempotent when stacked; streaming re-enters the scope on every step;
  - `CallCompleted` also fires when the call throws (a strict refusal) and when a stream is abandoned.
- **`ChunkCacheBodyHandler`** (`DelegatingHandler`, next to any other body-rewriting handler, dotLLM providers only):
  - writes only for POST `…/chat/completions` or `…/messages`, a current scope, a JSON body with no existing
    `chunk_cache` or inline `chunk`, capabilities with `versions` ∋ 1 (**ruling 16**), and a surviving span; otherwise the
    caller's content object goes out untouched (same bytes, same headers);
  - locates parts by **decoded** text (string content = part 0, ruling 19; array text parts by index), re-hashes every
    span (a mismatch drops it), converts UTF-16 to **UTF-8 byte** offsets, drops spans with lone surrogates or a boundary
    inside a pair (ruling 17 / review nit 11), orders by document position, drops overlaps (ruling 1), honours
    `max_chunks_per_request`, cuts ids to 256 chars;
  - splices `,"chunk_cache":{…}` before the closing brace, so every other byte is unchanged; options at their defaults
    are omitted, which makes the output byte-identical to the contract fixtures' `chunk_cache`;
  - a resend of the same request message restarts from the caller's original content (only over its own rewrite: a
    content replaced by a handler above wins);
  - strict `chunk_*` errors pass through; a non-strict `chunk_*` 400 / 503 (which a conforming server does not send)
    resends once with the original body and marks the source **not capable for the failure TTL (30 s)**, so a server
    that keeps refusing costs one extra request per period, never a loop (`FallBackOnChunkError = false` returns the
    refusal instead);
  - the response is disposed on every exit path; a blocking JSON body over 16 MiB is not read for the report;
  - report: from the buffered JSON body, or through **`SseChunkCacheScanner`** for `text/event-stream` (no buffering;
    only `data:` lines containing `"chunk_cache"` are parsed; OpenAI final chunk and Anthropic `message_delta`; `\n`,
    `\r\n` and bare `\r` line ends; a zero-byte read is not end of stream; lines over 1 MiB are skipped and counted).
  - install it **innermost** (closest to the wire), below other body rewriters such as CodeSharp's
    `DotLlmMaxTokensHandler`.
- **`ChunkCapabilityCache`** (`IChunkCapabilitySource`; also `FixedChunkCapabilities`): cached fail-closed probe, success
  TTL 5 min, failure TTL 30 s, probe timeout 5 s; answers kept **per model id** (up to 16), single flight per model; the
  shared probe runs without the first caller's execution context (no chunk scope, no tracing `Activity` parent);
  `MarkNotCapable()` after a refusal.

**Known limitation (v1): Anthropic `tool_result` blocks are not annotated.** On `/messages` the handler locates only
top-level `type: "text"` blocks. File-read results on that surface live inside `tool_result` blocks, so they go out
untouched (counted as not located; pinned by `AnthropicToolResult_Untouched_NotLocated`). The part-index mapping for
nested blocks is the server converter's (ruling 19) and is not yet pinned for clients. The OpenAI-compatible path, which
CodeSharp uses (spec 12.1), is unaffected.
- **Docs:** `docs/CHUNK_CACHE_CLIENT.md` (pipeline section), `docs/PACKAGING.md` (the dependency), package README. No
  server change, so `docs/SERVER.md` is untouched.

**Spec open question 1 (AsyncLocal hand-off), for a plain `HttpClient` stack: answered yes.** The scope reaches the body
handler through the OpenAI SDK pipeline and `HttpClient`, across awaited retry delays in a retrying handler on either side
of the body handler, a retrying chat client above the decorator, and later streaming steps. CodeSharp's own handlers
(`ProviderLivenessHandler`) were not tested here.

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

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `dotnet test tests/DotLLM.ChunkCache.Client.Tests -c Release --filter "Category!=Benchmark"` passes (205 tests);
  build warning-free (trim / AOT analyzers on); the maintainer has decided on the CI step above;
  `dotnet pack` gives an MIT nupkg whose only dependency is `Microsoft.Extensions.AI.Abstractions` 10.10.0.
- [ ] The manifest for `manifest.json` and `nonascii-crlf.json` equals the fixture's `chunk_cache` byte for byte (compact),
  with every other body byte unchanged; escaped and raw-UTF-8 bodies give the same manifest; offsets 35 / 374 for the
  surrogate-pair fixture.
- [ ] No capabilities (null, no v1, 401, 404, probe timeout): body identical to an undecorated pipeline.
- [ ] Streaming: the first event reaches the reader before the server writes the last; report from the final chunk.
- [ ] Retry resends the same manifest; strict errors pass through; non-strict chunk errors fall back once.
- [ ] Overhead under 5 ms (100 spans, 200 KB body): `Overhead_Under5ms`, a Release-only benchmark
  (`--filter Category=Benchmark`), median of 120 interleaved pairs, measured 1.5-2.1 ms; its non-timing twin runs in the
  default suite.
- [ ] A server that keeps refusing manifests costs no extra POST on the next request; alternating model ids probe once
  each; responses are disposed when reading fails.
- [ ] Every correctness test shown to fail against a mutant (below).

## Mutant evidence

Each mutant was applied in a `git archive` copy of the branch head (`81ac4061`, after the review round), the suite was
run (`dotnet test --blame-hang-timeout 90s`, Debug, so the timing benchmark is skipped), and the mutant was reverted.
**75 applied, 75 killed by a test**; the suite was green before and after. P1-P4 are the plan's four (hash over wire
bytes, UTF-16 offsets sent, mismatch keeps the span, SSE fully buffered); N1-N21 cover the review round. N19's first form
did not compile, and it was redone in the pre-fix shape (event raised only on success) and run alone. The script is
`mutants.py`; logs `mutants-r2-81ac4061.log`, `mutants-r2-N19-81ac4061.log`, and the pre-review runs
`mutants-final-cd044cc6.log` (54/54) and `mutants-run1-9f0d5bb1.log` (53/54; D7 survived and led to
`NotCapableSource_NoScopeOpened`).

| mutant | killed by |
|---|---|
| P1 hash over wire bytes (raw JSON string, escapes kept) | `AppendedSuffix_FoundThroughRegistryPrefix`, `Blocking_ManifestFromRealSerializer_ReportInAdditionalProperties`, `LossyPolicy_RequiresOptIn`, `ProbeFlapping_AnnotationsOnOffOn`, `Retry_AboveDecorator_AndInHttpClient_SameManifest` and more |
| P2 UTF-16 offsets sent instead of UTF-8 | `AppendedSuffix_FoundThroughRegistryPrefix`, `Blocking_ManifestFromRealSerializer_ReportInAdditionalProperties`, `AppendedSuffix_KeepsSpan`, `EscapedNonAscii_StillLocated`, `JoinedPart_SpanLocatedInside` and more |
| P3 hash mismatch keeps the span | `CrlfPart_LfIndexedHash_Dropped`, `HashMismatch_DropsOnlyThatSpan` |
| P4 SSE fully buffered before the caller reads | `Streaming_ReportOnUpdate_NotBuffered`, `Streaming_ReportFromFinalChunk_NoBuffering` |
| C1 handler annotates without capabilities | `NoCapabilities_BodyByteIdentical`, `Resend_AfterCapabilityLost_SendsOriginalBytes`, `AlwaysRefusingServer_SecondRequestCostsNoExtraPost` |
| C2 version-1 check dropped (ctor and source) | `NoCapabilities_BodyByteIdentical` |
| C3 probe exception treated as capable | `NotCapable_BodyIdenticalToUndecoratedPipeline`, `ProbeFlapping_AnnotationsOnOffOn`, `Cache_ProbeFailure_IsNull_CachedForFailureTtl`, `Cache_ProbeTimeout_IsNull_WithinTimeout` |
| C4 failure cached for the success TTL | `ProbeFlapping_AnnotationsOnOffOn`, `Cache_ProbeFailure_IsNull_CachedForFailureTtl` |
| C5 no TTL: cached forever | `ProbeFlapping_AnnotationsOnOffOn`, `Cache_OneProbe_ForManyCalls_UntilTtl`, `Cache_ProbeFailure_IsNull_CachedForFailureTtl` |
| C6 model change ignored (one answer for every model) | `Cache_ModelChange_Reprobes_SameModelDoesNot`, `Cache_AlternatingModels_OneProbeEach`, `Cache_ModelMap_Bounded` |
| C7 null model id treated as a change (no adoption) | `ProbeFlapping_AnnotationsOnOffOn` |
| C8 no single flight | `Cache_ConcurrentCallers_ShareOneProbe` |
| C9 probe timeout ignored | `Cache_ProbeTimeout_IsNull_WithinTimeout` (the run is aborted by `--blame-hang-timeout`) |
| C10 caller cancellation ignored | `Cache_CallerCancellation_Propagates` |
| D1 lossy policy without opt-in allowed | `LossyPolicy_RequiresOptIn` |
| D2 shadow treated as lossy | `LossyPolicy_RequiresOptIn`, `StackedDecorators_SameAsOne` |
| D3 stacked decorators both open scopes | `StackedDecorators_SameAsOne` |
| D4 streaming: scope not re-entered on later steps | `Streaming_ScopeOnEveryStep_LateReportCarried` |
| D5 streaming: late report dropped | `Streaming_ScopeOnEveryStep_LateReportCarried` |
| D6 blocking report not attached | `Blocking_ManifestFromRealSerializer_ReportInAdditionalProperties`, `Retry_AboveDecorator_AndInHttpClient_SameManifest`, `StackedDecorators_SameAsOne` |
| D7 decorator ignores a not-capable source | `NotCapableSource_NoScopeOpened` |
| H1 overlapping span kept | `Spans_DocumentOrder_OverlapDropped_RepeatedTextAnnotatedTwice` |
| H2 no document-order sort | `AppendedSuffix_FoundThroughRegistryPrefix`, `Blocking_ManifestFromRealSerializer_ReportInAdditionalProperties`, `AppendedSuffix_KeepsSpan`, `Spans_DocumentOrder_OverlapDropped_RepeatedTextAnnotatedTwice` |
| H3 max_chunks_per_request ignored | `MaxChunksPerRequest_KeepsFirstInDocumentOrder` |
| H4 existing chunk_cache overwritten (duplicate member) | `AlreadyAnnotated_LeftUntouched` |
| H5 inline chunk ignored (conflict created) | `AlreadyAnnotated_LeftUntouched` |
| H6 resend does not restart from the original content | `Resend_AfterCapabilityLost_SendsOriginalBytes` |
| H7 non-strict chunk error: no fallback | `ChunkErrors_StrictPassesThrough_NonStrictFallsBackOnce`, `AlwaysRefusingServer_SecondRequestCostsNoExtraPost`, `ReadFailure_DisposesResponse` |
| H8 strict chunk error also falls back | `ChunkErrors_StrictPassesThrough_NonStrictFallsBackOnce`, `CallCompleted_FiresWhenTheCallThrows` |
| H9 "to the end" span runs to the end of the wire part (into a suffix) | `AppendedSuffix_KeepsSpan` |
| H10 lone surrogates not checked | `JoinedPart_SpanLocatedInside`, `Surrogates_LoneSkipped_SplitPairInvalid` |
| H11 whole-part span always gets start/end | `AnthropicMessagesPath_Annotated`, `EscapedNonAscii_StillLocated`, `Manifest_MatchesRegisteredSpans`, `Options_NonDefaultsSent_DefaultsOmitted`, `RawUtf8Body_SameManifestAsEscaped` and more |
| H12 default policy written | `LossyPolicy_RequiresOptIn`, `EscapedNonAscii_StillLocated`, `Options_NonDefaultsSent_DefaultsOmitted`, `RawUtf8Body_SameManifestAsEscaped` |
| H13 body re-serialised instead of spliced | `EscapedNonAscii_StillLocated`, `Manifest_MatchesRegisteredSpans`, `RawUtf8Body_SameManifestAsEscaped`, `SurrogatePairBeforeSpan_Utf8OffsetsExact`, `Surrogates_LoneSkipped_SplitPairInvalid` and more |
| H14 content headers not copied | `Manifest_MatchesRegisteredSpans` |
| H15 id cut splits a surrogate pair | `LongId_CutTo256` |
| H16 every endpoint rewritten | `OtherEndpoints_Untouched` |
| H17 Anthropic /messages not rewritten | `AnthropicMessagesPath_Annotated`, `AnthropicToolResult_Untouched_NotLocated` |
| H18 non-JSON response buffered and read | `NonJsonResponse_NotBuffered` |
| H19 blocking report not read | `Blocking_ManifestFromRealSerializer_ReportInAdditionalProperties`, `Retry_AboveDecorator_AndInHttpClient_SameManifest`, `StackedDecorators_SameAsOne`, `BlockingReport_ParsedIntoScope`, `Retry_ResendsSameManifest` |
| H20 registered text inside a joined part not located | `JoinedPart_SpanLocatedInside` |
| H21 suffix (prefix match) not located in the handler | `AppendedSuffix_FoundThroughRegistryPrefix`, `AppendedSuffix_KeepsSpan` |
| H22 request options not sent (strict/on_miss/report/recompute) | `Options_NonDefaultsSent_DefaultsOmitted` |
| H23 span flags not sent (no_store) | `Options_NonDefaultsSent_DefaultsOmitted` |
| R1 registry prefix lookup disabled | `AppendedSuffix_FoundThroughRegistryPrefix`, `Registry_ExactAndPrefixLookup_LongestPrefixWins` |
| R2 registry: get does not refresh recency (FIFO) | `Registry_CharBudget_EvictsLeastRecentlyUsed`, `Registry_LeastRecentlyUsedEvicted_AtCapacity` |
| R3 registry unbounded (count) | `Registry_ConcurrentUse_Consistent`, `Registry_DefaultCapacity_Is4096`, `Registry_LeastRecentlyUsedEvicted_AtCapacity` |
| R4 registry: shortest prefix wins | `Registry_ExactAndPrefixLookup_LongestPrefixWins` |
| R5 registry: span ranges not validated | `Registry_ReRegisterReplaces_EmptyRemoves_BadRangeThrows` |
| S1 scanner: unterminated final line ignored | `Scanner_ZeroByteReads_NotEndOfStream`, `NoReport_NoCallback_AndFinalLineWithoutNewlineStillSeen` |
| S2 scanner: parses every data line (not lazy) | `Scanner_CrLineEnds`, `OnlyCandidateEventsAreParsed` |
| S3 scanner: nested chunk_cache accepted as the report | `Blocking_ManifestFromRealSerializer_ReportInAdditionalProperties`, `Retry_AboveDecorator_AndInHttpClient_SameManifest`, `StackedDecorators_SameAsOne`, `Streaming_ReportOnUpdate_NotBuffered`, `BlockingReport_ParsedIntoScope` and more |
| S4 report not looked up on messages (ToChatResponse) | `Streaming_ReportOnUpdate_NotBuffered` |
| S5 scope Dispose does not restore the enclosing scope | `Scope_NestsAndRestores` |
| N1 refusal only invalidates (probe/annotate/refuse loop) | `AlwaysRefusingServer_SecondRequestCostsNoExtraPost` |
| N2 cache MarkNotCapable is a no-op | `AlwaysRefusingServer_SecondRequestCostsNoExtraPost`, `Refusal_ExpiresAfterFailureTtl` |
| N3 fixed MarkNotCapable is a no-op | `AlwaysRefusingServer_SecondRequestCostsNoExtraPost` |
| N4 scanner: zero-byte read scanned as end of stream | `Scanner_ZeroByteReads_NotEndOfStream` |
| N5 scanner: bare CR not a line end | `Scanner_CrLineEnds` |
| N6 scanner: overflow flag not reset (next line lost) | `Scanner_OversizedLine_SkippedNextParsed` |
| N7 registry char budget ignored | `Registry_CharBudget_EvictsLeastRecentlyUsed` |
| N8 registry keeps a text over the budget | `Registry_CharBudget_EvictsLeastRecentlyUsed` |
| N9 cache keeps one model only | `Cache_AlternatingModels_OneProbeEach` |
| N10 probe inherits the caller context | `Cache_ProbeDoesNotInheritCallerContext` |
| N11 response not disposed when reading fails | `ReadFailure_DisposesResponse` |
| N12 oversized JSON report body read | `OversizedJsonBody_NotReadForReport` |
| N13 Content-Encoding ignored | `ContentEncodedBody_Untouched` |
| N14 splice does not skip trailing whitespace | `EscapedNonAscii_StillLocated`, `Manifest_MatchesRegisteredSpans`, `SurrogatePairBeforeSpan_Utf8OffsetsExact`, `BomAndTrailingWhitespace_SplicedBeforeTheBrace` |
| N15 non-POST rewritten | `NonPostOnChatPath_Untouched` |
| N16 FallBackOnChunkError ignored | `FallbackOff_RefusalReachesCaller` |
| N17 scope is process-wide, not per async flow | `AppendedSuffix_FoundThroughRegistryPrefix`, `Blocking_ManifestFromRealSerializer_ReportInAdditionalProperties`, `LossyPolicy_RequiresOptIn`, `NotCapableSource_NoScopeOpened`, `ProbeFlapping_AnnotationsOnOffOn` and more |
| N18 Anthropic tool_result text located | `AnthropicToolResult_Untouched_NotLocated` |
| N19 CallCompleted raised only on success (not when the call throws) | `CallCompleted_FiresWhenTheCallThrows` |
| N20 CallCompleted not raised for an abandoned stream | `CallCompleted_FiresWhenStreamAbandoned` |
| N21 resend always restores the first original (upstream rewrite lost) | `Resend_AfterUpstreamRewrite_KeepsNewContent` |
