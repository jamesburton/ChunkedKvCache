# Server: chunk_cache wire convention, flag off by default (draft)

> **Status: DRAFT, not filed.** Lane S lead issue (plan Task 9, first PR of umbrella row 4). Our side files nothing and
> pushes nothing; dotllm-97 / the user decide when and whether it is filed. Branch: `feature/chunk-cache-server` (off
> `dev` at `ec2d7836`), worktree `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`. First commit `38c0314b`.

## Title

Server: `chunk_cache` wire convention, flag off by default — step 1: pin today's template, special-token and
unknown-field behaviour

## Body

The `chunk_cache` convention (spec `2026-11-02-chunk-cache-integration.md` in ChunkedkvCache; wire contract
`docs/contracts/chunk-cache-v1/`) lets an agent harness mark spans of message text as reusable chunks. The server will
parse the annotations behind `--chunk-cache` (off by default), locate each span in the rendered prompt, and run `exact`
(default; output identical to the unannotated request) or `shadow` (plus a reuse plan). Flag off, request and response
bytes stay identical to today's for any body.

The convention leans on three behaviours of the current server that were never pinned. This first PR pins them with
characterisation tests (no production change) and records them in a new `docs/CHUNK_CACHE.md`, because the span locator
and the annotation parser (later PRs under this issue) are built on them:

1. **Multi-part content.** OpenAI `/v1/chat/completions` takes string `content` only: an array is a binding 400 with an
   empty body. Anthropic joins `text` blocks (and `tool_result` / `system` arrays) with one `'\n'`, and a `tool_result`
   splits the turn into separate messages.
2. **Templates.** Qwen3-4B-Instruct-2507 renders user / tool content verbatim. Llama-3.1-8B-Instruct trims user /
   assistant / system content and `tojson`-encodes tool content (so spans in Llama tool results are never byte-identical
   in the render).
3. **Special tokens.** The chat path tokenizes special spellings in content as plain text (#1339), via U+FDD0 markers
   that appear in the rendered string; `EncodeRaw` (the chunkers' path) parses them as control tokens; a caller U+FDD0
   is dropped at encode.
4. **Unknown fields.** `chunk_cache` (top level) and `chunk` (on a message or Anthropic text block) are ignored on both
   surfaces; an unknown Anthropic block type is a 400; blocks inside a `tool_result` content array are not type-checked.

Later PRs under this issue: wire parsing and validation behind `--chunk-cache` (Task 10), span location (Task 11),
`exact` / `shadow` execution and response metadata (Task 13), capabilities / explain / auth (Task 14). Snapshot lineage
(Task 12) has its own issue.

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `docs/CHUNK_CACHE.md` (owning doc) carries the "Pinned server behaviour" section; later PRs extend it and
      `docs/SERVER.md` for each new flag / endpoint.
- [ ] `tests/DotLLM.Tests.Unit/Server/ChunkCache/ServerPinTests.cs` passes on unmodified `dev` (27 tests: 23 model-free,
      4 real-GGUF tokenizer / template tests on CPU that skip when the GGUFs are absent).
- [ ] No production code changed in this PR.
- [ ] Every new server flag in later PRs is documented and covered by a test; `--chunk-cache` off by default.
- [ ] System.Text.Json source-generated DTOs follow dotLLM `CLAUDE.md` (no init-property initializers; nullable plus a
      resolved default); each new `JsonSerializerContext` gets a `JsonContextDefaultsTests`-style guard (none added here).
- [ ] Correctness tests shown to fail against mutants, recorded below and in the PR body.

## Mutant evidence

Run in a `git archive` copy of `38c0314b` (never the live worktree), `--filter FullyQualifiedName~ServerPin`, Release, CPU,
`DOTLLM_SKIP_VULKAN=1`. Baseline: 27 / 27 pass.

| mutant | change | killed by |
|---|---|---|
| M1 | `AnthropicConverter`: text blocks joined with no separator | `Anthropic_TextBlocks_AreJoinedWithOneNewline`, `Anthropic_EmptyTextBlock_SeparatorRule` (2 cases), HTTP `Anthropic_CountTokens_ChunkFieldsIgnored_BlocksJoinedWithNewline` |
| M2 | `ConcatTextBlocks` (tool_result / system arrays) with no separator | `Anthropic_SystemBlocks_…`, `Anthropic_ToolResult_ArrayContentJoinedWithNewline_…`, `Anthropic_ToolResultInnerBlocks_…` |
| M3 | unknown Anthropic block type accepted | `Anthropic_UnknownBlockType_IsRejected`, HTTP `Anthropic_UnknownBlockType_Is400InvalidRequest` |
| M4 | strict DTOs (`JsonUnmappedMemberHandling.Disallow` on `ServerJsonContext` and the HTTP options) | both unknown-field DTO tests and both unknown-field HTTP tests |
| M5 | OpenAI `content` accepts an array of parts, joined with no separator (the spec's assumption, as a converter) | `OpenAi_ArrayContent_DoesNotDeserialize`, HTTP `OpenAi_ArrayContent_Is400FromBinding_EmptyBody` |
| M6 | #1339 guard off in `JinjaChatTemplate` | `ContentPath_SpecialSpellings_…` (Qwen3, Llama-3.1) and `RealGguf_ContentPathIsPlain_EncodeRawParses` (both real GGUFs: substitution on real data) |
| M7 | `EncodeRaw` never parses specials (the spec's assumption) | `ChunkerEncodeRaw_ParsesSpecialSpellings_GuardedEncodeIsPlain`, both `RealGguf_ContentPathIsPlain_EncodeRawParses` |
| M8 | U+FDD0 markers not stripped at encode | `CallerSuppliedMarker_IsDroppedAtEncode`, `ChunkerEncodeRaw_…`, both `ContentPath_…` |
| M9 | Jinja `trim` is the identity | `Llama31_UserContent_IsTrimmed_InteriorKept`, `Llama31_SystemContent_IsTrimmed` |
| M10 | `tojson` of a string emits it raw | `Llama31_ToolContent_IsJsonStringEncoded` |

All 10 killed. Not targeted by a code mutant: `Qwen3_UserAndToolContent_AreRenderedVerbatim` (a full golden render of
the GGUF template; it is the Qwen3 counterpart of the Llama-3.1 trim / tojson pins), the `["", "b"]` case of the
empty-block rule (identical with or without a separator, by design), and `RealGguf_TemplateFixture_IsTheGgufMetadataTemplate`
(fixture provenance). The spec's assumptions were also run as expectations first (plan Step 1): 8 of 27 failed, all
recorded in the task report.
