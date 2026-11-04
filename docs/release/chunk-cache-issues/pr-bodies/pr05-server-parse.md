# PR 5 body draft: Server: parse / validate `chunk_cache` behind `--chunk-cache`

> DRAFT, not pushed, not opened. Branch `pr/chunkcache-server-parse` (local, worktree
> `C:\Development\dotLLM\.claude\worktrees\pr05-server-parse`), one commit `cdb9fa21` on `origin/dev` `3e617a70`. Needs the
> user's per-PR go-ahead before push / PR. Open the PR against `dev`.

## Title

Server: parse and validate `chunk_cache` annotations behind `--chunk-cache` (off by default)

## Body

Refs #1543, #1542. Follows #1576 (server behaviour pins), #1577 (core), #1588 (store); none is a build dependency of this PR
(the server does not reference `DotLLM.ChunkReuse` yet).

### Summary

The `chunk_cache` wire convention lets an agent harness mark spans of message text as reusable chunks (wire contract
`docs/contracts/chunk-cache-v1`, tracked in the umbrella #1542). This PR adds the **request side only**: an internal parser
that turns the annotations into a model and validates them against the text the server received. No store access, no reuse,
and no endpoint calls the parser yet (span location and `exact` / `shadow` execution are the next PRs). With the flag off
nothing reads the annotations: an annotated body behaves exactly as any body with an unknown field.

- **Flags.** `--chunk-cache` (off) and `--chunk-cache-max-chunks` (default 4096, at least 1, no upper bound) on `dotllm serve`
  and `ServerOptions.Parse` (`ServerOptions.ChunkCache`). Help and docs say "parsed and validated".
- **DTOs.** A raw `chunk_cache` `JsonElement?` on `ChatCompletionRequest` and `AnthropicMessagesRequest` (no initializer,
  no new JSON context). Inline Anthropic `chunk` fields stay inside `content`.
- **`ChunkAnnotationParser`** (`src/DotLLM.Server/ChunkCache/`, `internal`). OpenAI: manifest on string `content`
  (`part: 0`); array content stays the binding 400 with the flag on. Anthropic: inline `chunk` on `text` blocks (also inside a
  `tool_result` content array) and the manifest.
- **Codes.** `chunk_annotation_malformed`, `chunk_version_unsupported`, `chunk_span_invalid`, `chunk_hash_mismatch`,
  `chunk_manifest_conflict`, `chunk_too_many`, `chunk_policy_unavailable`, `chunk_namespace_ignored`,
  `chunk_not_wire_eligible`. Non-strict: one warning per code with a count, the span is plain text. Strict: the first defect
  in document order as `400 invalid_request_error` with the code (nothing is 422).
- **Check order per annotation:** structure, version, id, wire eligibility of the named chunker, range / boundary, overlap,
  then hash (`sha256:` + lowercase hex of the decoded text's UTF-8 bytes; CRLF kept). One defect per annotation. Unknown
  `report` / `on_miss` values and an out-of-range `query.message` are malformed (the default applies).
- **Namespace** is always server-assigned (a required parameter; `""` until authentication exists); a body value other than it
  is ignored with `chunk_namespace_ignored`.
- **Never throws on body content** (lone-surrogate escapes are `chunk_annotation_malformed`) and **bounded work**: manifest cut
  at `GetArrayLength()` before any entry is read, each part encoded to UTF-8 once, overlaps rejected before hashing,
  unannotated Anthropic requests pre-scanned and never converted twice.
- **Engine mapping.** Each accepted span carries `EngineSpan(EngineMessage, StartChar, EndChar)` into the converter's message
  list. `AnthropicConverter` records positions while it joins (`AnthropicTextOrigins`, an optional recorder; the public
  `ToMessages` is unchanged), and the parser checks the engine substring equals the span text.
- **Logging hygiene.** The parsed records' `ToString` never prints span text, hashes, the query or the namespace; client JSON
  echoed into error messages is clipped to 64 chars.
- **Contract fixtures** copied byte for byte under `tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/`, with a `-text` line in
  `.gitattributes` (plus the directory's own `.gitattributes`), checked against `fixtures.sha256`.
- **Docs in this PR:** `docs/CHUNK_CACHE.md` (switches, surfaces, mapping, validation order, cost bounds),
  `docs/SERVER.md` (both surfaces and the flag table).

### Scope

`git diff --stat origin/dev` (30 files, +3,468 / -10):

```
 .gitattributes                                            |    2 +
 docs/CHUNK_CACHE.md                                       |  102 ++-
 docs/SERVER.md                                            |   13 +
 src/DotLLM.Cli/Commands/ServeCommand.cs                   |   14 +
 src/DotLLM.Server/AnthropicConverter.cs                   |   57 +-
 src/DotLLM.Server/ChunkCache/ChunkAnnotationParser.cs     |  662 ++
 src/DotLLM.Server/ChunkCache/ChunkCacheCodes.cs           |   85 +
 src/DotLLM.Server/ChunkCache/ChunkCacheOptions.cs         |   31 +
 src/DotLLM.Server/ChunkCache/ChunkCacheWire.cs            |  140 ++
 src/DotLLM.Server/Models/AnthropicMessagesModels.cs       |    9 +
 src/DotLLM.Server/Models/ChatCompletionRequest.cs         |    9 +
 src/DotLLM.Server/ServerOptions.cs                        |   13 +
 tests/.../ChunkCache/Fixtures/v1/* (13 files)             |  842 ++
 tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj          |    2 +   (None item for the fixtures)
 tests/.../Server/ChunkCache/ChunkAnnotationParserTests.cs | 1278 ++
 tests/.../Server/ChunkCache/ChunkCacheFlagTests.cs        |  216 ++
 tests/.../Server/ChunkCache/ServerPinTests.cs             |    2 +-  (NonComputingModel private -> internal)
```

No new project, package, `JsonSerializerContext` or endpoint wiring; no release-asset change (`DotLLM.Server` does not
reference `DotLLM.ChunkReuse` in this PR). Request and response bytes are unchanged for every body with the flag off.

### Tests (CPU, `DOTLLM_SKIP_VULKAN=1`, Release, `-m:2`, clean worktree of `origin/dev` + this commit)

| run | result |
|---|---|
| `dotnet build tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj -c Release -m:2` | 0 errors |
| `--filter "FullyQualifiedName~DotLLM.Tests.Unit.Server&Category!=GPU"` (Windows) | **989 passed**, 13 skipped, 0 failed (1,002) |
| `--filter FullyQualifiedName~Server.ChunkCache` (the mutant baseline) | **124 passed**, 0 skipped, 0 failed |
| Linux (Docker `mcr.microsoft.com/dotnet/sdk:10.0`, non-root, CI filter, `FullyQualifiedName~DotLLM.Tests.Unit.Server`) | **980 passed**, 17 skipped, 0 failed (997) |

## Acceptance criteria

- [x] PR targets `dev`, never `main`; `Closes #N` is not used (it does not auto-close on `dev`).
- [x] Flag off: the parser returns null for any body, and an annotated body is byte-identical over HTTP to the same body
      without annotations (`FlagOff_*` tests; the pins of #1576 still pass).
- [x] OpenAI array content is the same bare 400 with the flag on and off.
- [x] Every contract request fixture gives `expected.json`'s warnings, strict error, accepted ids and defects, directly and
      translated to the Anthropic surface; the fixture copy matches `fixtures.sha256`.
- [x] Malformed annotations (incl. a lone-surrogate escape in each string field) are `chunk_annotation_malformed`
      (strict 400), never an exception; `chunk_not_wire_eligible` is a strict 400.
- [x] Cost bound: 4096 whole-part spans on a 4 MiB part hash once and allocate < 64 MiB; a 1,000,000-entry manifest with cap
      16 reads 16 entries and allocates < 4 MiB.
- [x] Anthropic mapping: second text block shifted by the first plus a newline; `tool_result` maps to its own engine message
      and the text after it restarts at offset 0; property test over random block layouts; a wrong engine offset is
      `not_carried`.
- [x] A body `chunk_cache.namespace` other than the caller's is ignored with a warning (strict 400).
- [x] `--chunk-cache` / `--chunk-cache-max-chunks` documented (`docs/SERVER.md` flag table, `docs/CHUNK_CACHE.md`) and tested
      (both option paths, values below 1 rejected).
- [x] STJ DTO rule: no init-property initializers on the new DTO members; no new JSON context.
- [x] `-text` fixtures line in `.gitattributes` in the same PR.
- [x] Correctness tests shown to fail against mutants (below).

## Mutant evidence

Run in a `git archive` copy of this commit, one mutant at a time, `--filter FullyQualifiedName~Server.ChunkCache`, Release,
CPU, `DOTLLM_SKIP_VULKAN=1`, baseline 124 / 124. **40 mutants, 40 killed** (every kill is a failing test, none is a build
error): the 35 parser / converter / options / flag mutants M1a-M33 of the original S2 review (M19, a future endpoint wiring
that ignores the flag, has no code in this PR and is exercised by the next PR), and P1-P5 for the ruling 33 / 34 follow-up
(unknown `report` / `on_miss`, out-of-range `query.message`, eligibility order). The original S2 round-2 run was 36 / 36 on
the milestone before the follow-up. Runner and logs (ChunkedkvCache): `.superpowers/sdd/2026-11-01-phase-s/pr05-mutants.py`,
`pr05-mutants.log`; originals `phase-i-task-10-mutants*.log` and `phase-i-task-11-mutate.py` (P1-P5).

| mutant | change | failing tests |
|---|---|---|
| M1a | engine char offsets taken as byte offsets | 8 (`Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText`, `Anthropic_TwoTextBlocks_SecondBlockSpanShiftedByFirstPlusNewline`, `Fixture_NonAscii_ByteOffsetsDifferFromCharOffsets_AndCrlfIsHashedAsSent`, `Fixtures_MatchExpected`, +4 more) |
| M1b | wire start/end read as UTF-16 char offsets | 8 (`Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText`, `Anthropic_TwoTextBlocks_SecondBlockSpanShiftedByFirstPlusNewline`, `Fixture_NonAscii_ByteOffsetsDifferFromCharOffsets_AndCrlfIsHashedAsSent`, `Fixtures_MatchExpected`, +2 more) |
| M2 | overlap allowed | 5 (`CheckOrder_OverlapBeforeHash`, `CostBound_ManyWholePartSpansOnALargePart_EncodeOnceHashOnce`, `Fixtures_MatchExpected`, `Fixtures_ThroughTheAnthropicSurface_MatchExpected`, +1 more) |
| M3 | conflict served annotated | 2 (`Fixtures_MatchExpected`, `Fixtures_ThroughTheAnthropicSurface_MatchExpected`) |
| M4 | strict status 422 | 20 (`BodyNamespace_OtherThanCallers_IgnoredWithWarning_StrictIs400`, `Fixtures_MatchExpected`, `Fixtures_ThroughTheAnthropicSurface_MatchExpected`, `MalformedAnnotations_AreAnnotationMalformed_NotAThrow`, +4 more) |
| M5a | text-block newline join not counted in the mapping | 7 (`Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText`, `Anthropic_TwoTextBlocks_SecondBlockSpanShiftedByFirstPlusNewline`, `Fixtures_ThroughTheAnthropicSurface_MatchExpected`) |
| M5b | tool_result array join not counted | 2 (`Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText`, `Anthropic_ToolResultBlock_MapsToOwnEngineMessage`) |
| M6a | tool_result offset not reset after the split | 2 (`Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText`, `Anthropic_ToolResultBlock_MapsToOwnEngineMessage`) |
| M6b | tool_result mapped to the message before it | 3 (`Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText`, `Anthropic_ToolResultBlock_MapsToOwnEngineMessage`, `Anthropic_ToolResultManifest_StringContentIsText_ArrayContentIsNot`) |
| M7 | --chunk-cache off ignored | 1 (`FlagOff_ReturnsNull_EvenWithAnnotations`) |
| M8 | hash compared case-insensitively | 1 (`UppercaseHex_IsAMismatch`) |
| M9 | strict error is the last defect | 2 (`Strict_FirstDefectInDocumentOrderWins`, `Strict_ManifestDefects_InArrayOrder`) |
| M10 | id length in UTF-16 units | 1 (`IdLongerThan256_Rejected`) |
| M11 | too-many not enforced | 2 (`CostBound_HugeManifest_OnlyTheCapIsRead`, `TooMany_Warns_StrictIs400`) |
| M12 | non-wire-eligible chunker accepted | 2 (`CheckOrder_EligibilityAfterId_BeforeRange_ReservesNoRange`, `UnknownChunker_NotWireEligible_WarningAndStrict400`) |
| M13 | hash over the whole part | 13 (`Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText`, `Anthropic_ToolResultManifest_StringContentIsText_ArrayContentIsNot`, `Anthropic_TwoTextBlocks_SecondBlockSpanShiftedByFirstPlusNewline`, `CheckOrder_EligibilityAfterId_BeforeRange_ReservesNoRange`, +7 more) |
| M14 | UTF-8 boundary check skipped | 2 (`Fixtures_MatchExpected`, `Fixtures_ThroughTheAnthropicSurface_MatchExpected`) |
| M15 | empty span allowed | 1 (`BadRanges_AreSpanInvalid`) |
| M16 | inline v not required | 1 (`Version_Unsupported_DropsEverything`) |
| M17 | query = last message of any role | 1 (`QueryDefaultsToLastUserMessage`) |
| M18 | engine-substring verification removed (bounds kept) | 1 (`WrongEngineOffset_IsNotCarried`) |
| M20 | default max chunks 1024 | 3 (`CostBound_ManyWholePartSpansOnALargePart_EncodeOnceHashOnce`, `Default_IsOff_With4096`, `Parse_Flags`) |
| M21 | dotllm serve does not validate --chunk-cache-max-chunks | 2 (`MaxChunks_BelowOne_Rejected`) |
| M22 | non-strict request also gets the error | 17 (`BodyNamespace_OtherThanCallers_IgnoredWithWarning_StrictIs400`, `Fixtures_MatchExpected`, `Fixtures_ThroughTheAnthropicSurface_MatchExpected`, `TooMany_Warns_StrictIs400`, +1 more) |
| M23 | body namespace honoured (no warning) | 1 (`BodyNamespace_OtherThanCallers_IgnoredWithWarning_StrictIs400`) |
| M24 | malformed annotations reported as chunk_span_invalid | 8 (`CostBound_HugeManifest_OnlyTheCapIsRead`, `LoneSurrogateEscape_InAnnotationField_IsMalformed_NeverThrows`, `MalformedAnnotations_AreAnnotationMalformed_NotAThrow`, `Version_Unsupported_DropsEverything`) |
| M25 | chunk_not_wire_eligible warning-only | 2 (`Codes_AreTheSpecStrings`, `UnknownChunker_NotWireEligible_WarningAndStrict400`) |
| M26 | hash checked before overlap | 2 (`CheckOrder_OverlapBeforeHash`, `CostBound_ManyWholePartSpansOnALargePart_EncodeOnceHashOnce`) |
| M27 | part re-encoded per annotation | 1 (`CostBound_ManyWholePartSpansOnALargePart_EncodeOnceHashOnce`) |
| M28 | manifest materialised before the cap | 1 (`CostBound_HugeManifest_OnlyTheCapIsRead`) |
| M29 | unguarded string read (lone surrogate throws) | 10 (`LoneSurrogateEscape_InAnnotationField_IsMalformed_NeverThrows`) |
| M30 | no Anthropic pre-scan | 1 (`Anthropic_Unannotated_SkipsTheConversion`) |
| M31 | OpenAI null-message guard removed | 1 (`NullMessages_ReturnNull`) |
| M32 | ToString prints the namespace | 1 (`ToString_RedactsTextHashQueryAndNamespace`) |
| M33 | echoed client JSON not clipped | 1 (`ErrorMessage_ClipsEchoedClientJson`) |
| P1 | report: unknown value falls back silently | 3 (`UnknownOptionValue_IsMalformed_DefaultApplies_StrictIs400`) |
| P2 | on_miss: unknown value falls back silently | 2 (`UnknownOptionValue_IsMalformed_DefaultApplies_StrictIs400`) |
| P3 | query.message out of range falls back silently | 4 (`QueryDefaultsToLastUserMessage`, `UnknownOptionValue_IsMalformed_DefaultApplies_StrictIs400`) |
| P4 | eligibility checked after range/boundary | 1 (`CheckOrder_EligibilityAfterId_BeforeRange_ReservesNoRange`) |
| P5 | ineligible span reserves its range (eligibility after overlap) | 1 (`CheckOrder_EligibilityAfterId_BeforeRange_ReservesNoRange`) |

### Conventions checklist

- [x] Targets `dev`; opened after #1576, #1577, #1588 merged (this branch is cut from `origin/dev` `3e617a70`).
- [x] Issue first: #1543 (Lane S lead) and umbrella #1542; draft `10-server-request-parsing.md`.
- [x] Owning docs in the same PR: `docs/CHUNK_CACHE.md`, `docs/SERVER.md`.
- [x] XML docs on new types; warnings as errors (no CS1574: no cref to a type of a later PR).
- [x] STJ DTO rule respected (see above).
- [x] Correctness tests shown to fail against mutants.
- [x] Linux check run before opening (CI is ubuntu).

Generated with [Claude Code](https://claude.com/claude-code)
