# Server: parse and validate `chunk_cache` annotations behind `--chunk-cache` (draft)

> **Status: DRAFT, not filed.** Lane S, plan Task 10. Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and #1542
> (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Packaging (Task 10 review, controller amendment): this step does not ship as a standalone PR.** Tasks 10, 11 and 13
> go upstream as one PR (the flag must do something when merged); this text becomes that PR's parsing section, or a
> sub-issue of #1543. Branch `feature/chunk-cache-server`, worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`, commits `b0a4e246`, `5e527b9f`, `6cf23d19` (review fix
> round), `91cbdf00`, `4e3f8257` on top of `38c0314b` (Task 9).

## Title

Server: `chunk_cache` wire convention — parse and validate annotations behind `--chunk-cache` (off by default)

## Body

Refs #1543, #1542.

The `chunk_cache` convention (spec `2026-11-02-chunk-cache-integration.md` §5 in ChunkedkvCache; wire contract
`docs/contracts/chunk-cache-v1/`, rulings 1–32 plus the Task 10 review amendments to rulings 4, 17 and 24) lets an agent
harness mark spans of message text as reusable chunks. This part adds the request side: an internal parser that turns
the annotations into a model and validates them against the text the server received. No store access, no reuse; the
endpoints call it from the `exact` / `shadow` part of the same PR. With the flag off nothing reads the annotations.

What it adds:

- **Flags.** `--chunk-cache` (off) and `--chunk-cache-max-chunks` (default 4096, ≥ 1, no upper bound) on `dotllm serve`
  and `ServerOptions.Parse` (`ServerOptions.ChunkCache`). Help and docs say "parsed and validated"; reuse comes with the
  later parts.
- **DTOs.** A raw `chunk_cache` `JsonElement?` on `ChatCompletionRequest` and `AnthropicMessagesRequest` (no
  initializer; no new JSON context, so `JsonContextDefaultsTests` covers it). Inline Anthropic `chunk` fields stay
  inside `content`.
- **`ChunkAnnotationParser`** (`src/DotLLM.Server/ChunkCache/`, `internal` with its records). OpenAI = manifest on
  string `content` (`part: 0`); array content stays the binding 400 even with the flag on (ruling 19). Anthropic =
  inline `chunk` on `text` blocks (also inside a `tool_result` content array, ruling 30) and the manifest (top-level
  `text` block, string content, or a `tool_result` with string content).
- **Codes** (§5.8 plus rulings 23, 26, 32): `chunk_annotation_malformed` (wrong JSON type, missing required field,
  unknown `at` shape, an undecodable string), `chunk_version_unsupported`, `chunk_span_invalid`, `chunk_hash_mismatch`,
  `chunk_manifest_conflict`, `chunk_too_many`, `chunk_policy_unavailable`, `chunk_namespace_ignored`,
  `chunk_not_wire_eligible` (a warning, 400 when strict). Non-strict: one warning per code with a count, the span is
  plain text. Strict: the first defect (request-level first, then inline annotations in (message, part) order, then
  manifest entries in array order) as `400 invalid_request_error` with the code; nothing is 422.
- **Check order per annotation** (amended ruling 24): structure, version, id (and chunker), range / boundary, overlap,
  then hash (`sha256:` + lowercase hex of the decoded text's UTF-8 bytes; CRLF kept). One defect per annotation.
- **Namespace.** Always server-assigned: the caller's namespace is a required argument (the API key's once
  authentication exists, `""` until then); a body `chunk_cache.namespace` other than it is ignored with
  `chunk_namespace_ignored`. Format validation stays with the assignment (authentication part).
- **Never throws on body content.** Annotation strings are read through a guarded read: a lone-surrogate escape (which
  System.Text.Json parses but cannot return as a string) is `chunk_annotation_malformed`. Ruling 17 (lone surrogate
  hashes as U+FFFD) applies to in-process callers only: over HTTP such text cannot reach the parser.
- **Bounded work.** The manifest is cut at `GetArrayLength()` before any entry is read; each annotated part is encoded to
  UTF-8 once per request with a byte-to-char checkpoint table; overlaps are rejected before hashing, so the bytes hashed
  per request never exceed the request's text; an unannotated Anthropic request is detected by a pre-scan and never
  converted twice; null messages are tolerated.
- **Engine mapping.** Each accepted span carries `EngineSpan(EngineMessage, StartChar, EndChar)` into the converter's
  `ChatMessage` list (before a profile system prompt, ruling 31). On Anthropic, `AnthropicConverter` records the
  positions while it joins (`AnthropicTextOrigins`, an optional recorder; the public `ToMessages` is unchanged), and the
  parser checks the engine substring equals the span text.
- **Logging hygiene.** The parsed records' `ToString` never prints span text, hashes, the query or the namespace;
  client JSON echoed into error messages is clipped to 64 chars.
- **Contract fixtures** copied byte for byte under `tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/` (`-text` in
  `.gitattributes`; checked against `fixtures.sha256` and its own pinned hash).
- **Docs.** `docs/CHUNK_CACHE.md` (switches, packaging, surfaces, mapping, validation order, cost bounds, ruling 17) and
  `docs/SERVER.md` (both surfaces and the flag table).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; ships together with span location and `exact` / `shadow` (Tasks 11, 13);
      `Closes #N` closed by hand.
- [ ] Flag off: the parser returns null for any body, and an annotated body is byte-identical over HTTP to the same body
      without annotations (valid, strict-with-defects, version 2, conflicting and malformed `chunk_cache` values;
      OpenAI chat and Anthropic `count_tokens`; `/v1/messages` and streaming once wired).
- [ ] OpenAI array content is the same bare 400 with the flag on and off.
- [ ] Every contract request fixture gives `expected.json`'s warnings, strict error, accepted ids and defects, directly
      and translated to the Anthropic surface; the fixture copy matches `fixtures.sha256`.
- [ ] Malformed annotations (incl. a lone-surrogate escape in `id`, `hash`, `chunker`, `positioning`, `stability`,
      `policy`, `namespace`, `report`, `on_miss`, `query.text`) are `chunk_annotation_malformed` (strict 400), never an
      exception; `chunk_not_wire_eligible` is a strict 400.
- [ ] Cost bound: 4096 whole-part spans on a 4 MiB part hash once and allocate < 64 MiB; a 1,000,000-entry manifest
      with cap 16 reads 16 entries and allocates < 4 MiB.
- [ ] Anthropic mapping: the second text block's span is shifted by the first plus `'\n'`; a `tool_result` maps to its
      own engine message and the text after it restarts at offset 0; a property test over random block layouts
      (incl. `thinking` blocks) finds every mapped span as the exact substring of its engine message; a wrong engine
      offset is caught (`not_carried`).
- [ ] A body `chunk_cache.namespace` other than the caller's is ignored with `chunk_namespace_ignored` (strict 400);
      the caller's own value is accepted silently; the caller's namespace is a required parameter.
- [ ] `--chunk-cache` and `--chunk-cache-max-chunks` documented (`docs/SERVER.md` incl. the flag table,
      `docs/CHUNK_CACHE.md`) and covered by tests (both option paths, values below 1 rejected).
- [ ] System.Text.Json DTO rule: no init-property initializers on deserialized DTOs; no new `JsonSerializerContext`.
- [ ] Correctness tests shown to fail against mutants (table below, also in the PR body).

## Mutant evidence

Run in a `git archive` copy (never the live worktree), `--filter FullyQualifiedName~Server.ChunkCache`, Release, CPU,
`DOTLLM_SKIP_VULKAN=1`. Production code at `6cf23d19` (unchanged since); M1–M33 with the tests of `91cbdf00` (baseline
106 / 106), M24–M25 re-run with `4e3f8257` (baseline 107 / 107). **36 mutants, 36 killed.**

| mutant | change | killed by |
|---|---|---|
| M1a | engine char offsets taken as the byte offsets | `OpenAi_StringContentManifest_Parsed`, `Anthropic_TwoTextBlocks_…`, property test, nonascii fixture (both runs) |
| M1b | wire `start`/`end` read as UTF-16 char offsets | 12 incl. `Fixture_NonAscii_…`, nonascii + bad-span fixtures, `BadRanges_…`, property test |
| M2 | overlap allowed | `Overlap_…`, `CheckOrder_OverlapBeforeHash`, `CostBound_ManyWholePartSpans…`, bad-span fixture (both runs) |
| M3 | conflict served annotated | conflict fixture (both runs) |
| M4 | strict status 422 | 11: every strict fixture run, `MalformedAnnotations_…`, `TooMany_…`, `UnknownChunker_…`, `UnknownPolicy_…`, `BodyNamespace_…` |
| M5a | Anthropic text-block `'\n'` join not counted in the mapping | `Anthropic_TwoTextBlocks_…`, property test, 5 Anthropic fixture runs |
| M5b | `tool_result` array join not counted | `Anthropic_ToolResultBlock_MapsToOwnEngineMessage`, property test |
| M6a | `tool_result` offset not reset | `Anthropic_ToolResultBlock_…`, property test |
| M6b | `tool_result` mapped to the message before it | `Anthropic_ToolResultBlock_…`, `Anthropic_ToolResultManifest_…`, property test |
| M7 | `--chunk-cache` off ignored | `FlagOff_ReturnsNull_EvenWithAnnotations` |
| M8 | hash compared case-insensitively | `UppercaseHex_IsAMismatch` |
| M9 | strict error = last defect | `Strict_FirstDefectInDocumentOrderWins`, `Strict_ManifestDefects_InArrayOrder` |
| M10 | `id` length in UTF-16 units | `IdLongerThan256_Rejected` |
| M11 | too-many not enforced | `TooMany_Warns_StrictIs400`, `CostBound_HugeManifest_OnlyTheCapIsRead` |
| M12 | non-wire-eligible chunker accepted | `UnknownChunker_NotWireEligible_WarningAndStrict400` |
| M13 | hash over the whole part | 12 incl. manifest / nonascii fixtures, `CheckOrder_…`, `Overlap_…` |
| M14 | UTF-8 boundary check skipped | bad-span fixture (both runs) |
| M15 | empty span allowed | `BadRanges_AreSpanInvalid(2, 2)` |
| M16 | inline `v` not required | `Version_Unsupported_DropsEverything` |
| M17 | query = last message of any role | `QueryDefaultsToLastUserMessage` |
| M18 | engine-substring verification removed (bounds kept) | `WrongEngineOffset_IsNotCarried` (was the round-1 survivor) |
| M19 | a future endpoint wiring that ignores the flag | `FlagOff_OpenAi_…`, `FlagOff_Anthropic_…` (+ 2 Task 9 HTTP pins) |
| M20 | default max chunks 1024 | `Default_IsOff_With4096`, `Parse_Flags`, `CostBound_ManyWholePartSpans…` |
| M21 | `dotllm serve` does not validate `--chunk-cache-max-chunks` | `MaxChunks_BelowOne_Rejected` (0, -5) |
| M22 | non-strict request also gets the error | 8: non-strict fixture runs with defects, `TooMany_…`, `BodyNamespace_…` |
| M23 | body `chunk_cache.namespace` honoured | `BodyNamespace_OtherThanCallers_IgnoredWithWarning_StrictIs400` |
| M24 | malformed annotations reported as `chunk_span_invalid` (pre-ruling 23) | `Codes_AreTheSpecStrings` (survived until that test was added: the other tests compare against the constant) |
| M25 | `chunk_not_wire_eligible` warning-only (pre-ruling 26) | `UnknownChunker_NotWireEligible_WarningAndStrict400`, `Codes_AreTheSpecStrings` |
| M26 | hash checked before overlap (pre-amendment order) | `CheckOrder_OverlapBeforeHash`, `CostBound_ManyWholePartSpans…` (hash count) |
| M27 | part re-encoded per annotation | `CostBound_ManyWholePartSpans…` (allocation bound) |
| M28 | manifest materialised before the cap | `CostBound_HugeManifest_OnlyTheCapIsRead` (allocation bound) |
| M29 | unguarded string read (lone surrogate throws) | `LoneSurrogateEscape_InAnnotationField_…` (all 10 fields) |
| M30 | no Anthropic pre-scan | `Anthropic_Unannotated_SkipsTheConversion` |
| M31 | OpenAI null-message guard removed | `NullMessages_ReturnNull` |
| M32 | `ToString` prints the namespace | `ToString_RedactsTextHashQueryAndNamespace` |
| M33 | echoed client JSON not clipped | `ErrorMessage_ClipsEchoedClientJson` |

Round 1 (before the review, `5e527b9f`): 24 mutants, 23 killed, M18 survived; kept in
`.superpowers/sdd/2026-11-01-phase-s/phase-i-task-10-mutants.log` beside the round-2 log.
