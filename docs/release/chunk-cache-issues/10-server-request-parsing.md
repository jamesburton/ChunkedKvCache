# Server: parse and validate `chunk_cache` annotations behind `--chunk-cache` (draft)

> **Status: DRAFT, not filed.** Lane S, plan Task 10 (second PR under the Lane S lead issue). Refs #1543 (Lane S lead,
> `09-server-behaviour-pin.md`) and #1542 (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user
> decide when and whether it is filed, and whether it is its own issue or a PR under #1543. Branch:
> `feature/chunk-cache-server`, worktree `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`, commits
> `b0a4e246` and `5e527b9f` on top of `38c0314b` (Task 9).

## Title

Server: `chunk_cache` wire convention — step 2: parse and validate annotations behind `--chunk-cache` (off by default)

## Body

Refs #1543, #1542.

The `chunk_cache` convention (spec `2026-11-02-chunk-cache-integration.md` §5 in ChunkedkvCache; wire contract
`docs/contracts/chunk-cache-v1/`, rulings 1–22) lets an agent harness mark spans of message text as reusable chunks. This
step adds the request side only: a parser that turns the annotations into an internal model and validates them against
the text the server received. No store access, no reuse, and the endpoints do not call it yet (the `exact` / `shadow`
step wires it in, with strict 400s and the response object). With the flag off nothing reads the annotations.

What it adds:

- **Flags.** `--chunk-cache` (off) and `--chunk-cache-max-chunks` (default 4096, ≥ 1) on `dotllm serve` and
  `ServerOptions.Parse` (`ServerOptions.ChunkCache`).
- **DTOs.** A raw `chunk_cache` `JsonElement?` on `ChatCompletionRequest` and `AnthropicMessagesRequest` (no
  initializer; no new JSON context, so the existing `JsonContextDefaultsTests` guard covers it). Inline Anthropic `chunk`
  fields stay inside `content`.
- **`ChunkAnnotationParser`** (`src/DotLLM.Server/ChunkCache/`): OpenAI = manifest on string `content` (`part: 0`);
  array content stays the binding 400 even with the flag on (ruling 19). Anthropic = inline `chunk` on `text` blocks
  (also inside a `tool_result` content array) and the manifest (top-level `text` block, string content, or a
  `tool_result` with string content). Checks: version, `id` 1–256 characters, `positioning: isolated`, message / part in
  range, text part, byte range non-empty and in range, UTF-8 boundaries, overlap (later span dropped), hash recomputed
  over the decoded text (`sha256:` + lowercase hex; CRLF kept; lone surrogate as U+FFFD), wire-eligible chunker
  (`symbol-512`), manifest conflict, too many, and a body `chunk_cache.namespace` other than the caller's
  (`chunk_namespace_ignored`: the namespace is server-assigned; the parser takes the caller's namespace as an argument,
  default `""` until authentication lands; format validation stays with the assignment). Non-strict: warning with a count, span dropped. Strict: the first defect
  in document order as `400 invalid_request_error` with the §5.8 code (no 422).
- **Engine mapping.** Each accepted span carries `EngineSpan(EngineMessage, StartChar, EndChar)` into the converter's
  `ChatMessage` list. On Anthropic, `AnthropicConverter` records the positions while it joins (`AnthropicTextOrigins`,
  an optional recorder; the public `ToMessages` is unchanged), so the `'\n'` joins, the empty-block rule and the
  `tool_result` split cannot drift from the mapping; the parser also checks the engine substring equals the span text.
- **Contract fixtures** copied byte for byte under `tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/` (`-text` in
  `.gitattributes`; checked against `fixtures.sha256` and its own pinned hash).
- **Docs.** `docs/CHUNK_CACHE.md` (switches, request parsing, mapping, validation order) and `docs/SERVER.md` (both
  surfaces point to it).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` is closed by hand.
- [ ] Flag off: `ChunkAnnotationParser.Parse` returns null for any body, and an annotated body is byte-identical over HTTP
      to the same body without annotations (valid, strict-with-defects, version 2, conflicting and malformed
      `chunk_cache` values; OpenAI chat and Anthropic `count_tokens`).
- [ ] OpenAI array content is the same bare 400 with the flag on and off.
- [ ] Every contract request fixture gives `expected.json`'s warnings, strict error, accepted ids and defects, directly
      and translated to the Anthropic surface; the fixture copy matches `fixtures.sha256`.
- [ ] Anthropic mapping: the second text block's span is shifted by the first plus `'\n'`; a `tool_result` maps to its
      own engine message and the text after it restarts at offset 0; a property test over random block layouts finds
      every mapped span as the exact substring of its engine message.
- [ ] A body `chunk_cache.namespace` other than the caller's is ignored with `chunk_namespace_ignored` (strict: 400 with
      that code); the caller's own value is accepted silently; the parse always carries the caller's namespace.
- [ ] `--chunk-cache` and `--chunk-cache-max-chunks` documented (`docs/SERVER.md`, `docs/CHUNK_CACHE.md`) and covered by
      tests (both option paths, validation of values below 1).
- [ ] System.Text.Json DTO rule: no init-property initializers on deserialized DTOs; no new `JsonSerializerContext`.
- [ ] Correctness tests shown to fail against mutants (table below, also in the PR body).

## Mutant evidence

Run in a `git archive` copy of `5e527b9f` (never the live worktree), `--filter FullyQualifiedName~Server.ChunkCache`,
Release, CPU, `DOTLLM_SKIP_VULKAN=1`. Baseline: 87 / 87 pass. 24 mutants, 23 killed, 1 survivor (M18, by design).

| mutant | change | killed by |
|---|---|---|
| M1a | engine char offsets taken as the byte offsets (offsets as chars) | `OpenAi_StringContentManifest_Parsed`, `Anthropic_TwoTextBlocks_…`, property test, both nonascii fixture runs (5) |
| M1b | wire `start`/`end` read as UTF-16 char offsets | 11 incl. `Fixture_NonAscii_…`, nonascii + bad-span fixtures, `OpenAi_StringContentManifest_Parsed`, property test |
| M2 | overlap allowed | `Overlap_LaterSpanDropped_…`, bad-span fixture (both runs) |
| M3 | conflict served annotated | conflict fixture (both runs) |
| M4 | strict status 422 instead of 400 | 9: every strict fixture run, `TooMany_…`, `UnknownPolicy_…`, `BodyNamespace_OtherThanCallers_…` |
| M5a | Anthropic text-block `'\n'` join not counted in the mapping | `Anthropic_TwoTextBlocks_SecondBlockSpanShiftedByFirstPlusNewline`, property test, 5 Anthropic fixture runs |
| M5b | `tool_result` array join not counted | `Anthropic_ToolResultBlock_MapsToOwnEngineMessage`, property test |
| M6a | `tool_result` offset not reset (text after the split keeps the earlier offset) | `Anthropic_ToolResultBlock_MapsToOwnEngineMessage`, property test |
| M6b | `tool_result` mapped to the message before it (no split) | `Anthropic_ToolResultBlock_…`, `Anthropic_ToolResultManifest_…`, property test |
| M7 | `--chunk-cache` off ignored (parses anyway) | `FlagOff_ReturnsNull_EvenWithAnnotations` |
| M8 | hash compared case-insensitively | `UppercaseHex_IsAMismatch` |
| M9 | strict error = last defect, not first | `Strict_FirstDefectInDocumentOrderWins` |
| M10 | `id` length in UTF-16 units | `IdLongerThan256_Rejected` |
| M11 | too-many not enforced | `TooMany_Warns_StrictIs400` |
| M12 | non-wire-eligible chunker accepted | `UnknownChunker_NotWireEligibleWarning` |
| M13 | hash over the whole part, not the span | 11 incl. manifest / nonascii fixtures, `OpenAi_StringContentManifest_Parsed`, `Overlap_…` |
| M14 | UTF-8 boundary check skipped | bad-span fixture (both runs) |
| M15 | empty span allowed | `BadRanges_AreSpanInvalid(2, 2)` |
| M16 | inline `v` not required | `Version_Unsupported_DropsEverything` |
| M17 | query = last message of any role | `QueryDefaultsToLastUserMessage` |
| M18 | engine-substring verification removed | **survived** (defence in depth: the mapping comes from the converter itself, so the check only fires on a converter/mapping bug; M5a/M5b/M6a/M6b are such bugs and are killed by the offset tests directly) |
| M19 | a future endpoint wiring that ignores the flag (OpenAI chat + Anthropic count_tokens refuse any `chunk_cache`) | `FlagOff_OpenAi_…ByteIdenticalToPlain`, `FlagOff_Anthropic_…ByteIdenticalToPlain` (+ 2 Task 9 HTTP pins) |
| M20 | default max chunks 1024 | `Default_IsOff_With4096`, `Parse_Flags` |
| M21 | `dotllm serve` does not validate `--chunk-cache-max-chunks` | `MaxChunks_BelowOne_Rejected` (0, -5) |
| M22 | non-strict request also gets the error | 8: every non-strict fixture run with defects, `TooMany_…`, `BodyNamespace_…` |
| M23 | body `chunk_cache.namespace` honoured (used, no warning) | `BodyNamespace_OtherThanCallers_IgnoredWithWarning_StrictIs400` |

The plan's six named mutants map to M1a/M1b (offsets as chars), M2 (overlap), M3 (conflict), M4 (422), M5a/M5b (join
separator), M6a (tool_result offset not reset). Four mutants (M12, M14, M17, M18) first failed to build on CS0162
(constant `if (false)` with warnings-as-errors) and were re-expressed with runtime-false conditions; the table is the
final run.
