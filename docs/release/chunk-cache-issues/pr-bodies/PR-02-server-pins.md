# PR 2 body draft: server behaviour pins (tests only)

> **DRAFT, not opened.** Branch `pr/chunkcache-server-pins` (local, worktree
> `C:\Development\dotLLM\.claude\worktrees\pr-pins`), one commit (cherry-pick of `38c0314b`, message gains
> `Refs #1543`) on `origin/dev` `29567637`. Issue: #1543 (filed). Base: `dev`.

## Title

Server: pin today's template, special-token and unknown-field behaviour (chunk_cache step 1, tests only)

## Body

Refs #1543. Refs #1542 (umbrella).

### Summary

The `chunk_cache` wire convention (#1543) lets an agent harness mark spans of message text as reusable chunks; later
PRs parse it behind `--chunk-cache` (off by default), locate each span in the rendered prompt and run `exact` /
`shadow`. That design leans on four behaviours of the current server that were never pinned. This PR pins them with
characterisation tests on unmodified `dev` and records them in a new `docs/CHUNK_CACHE.md`. **No production code
changes.**

1. **Multi-part content.** OpenAI `/v1/chat/completions` takes string `content` only: an array is a binding 400 with an
   empty body. Anthropic joins `text` blocks (and `tool_result` / `system` arrays) with one `'\n'`; a `tool_result`
   splits the turn into separate messages.
2. **Templates.** Qwen3-4B-Instruct-2507 renders user / tool content verbatim. Llama-3.1-8B-Instruct trims user /
   assistant / system content and `tojson`-encodes tool content.
3. **Special tokens.** The chat path tokenizes special spellings in content as plain text (#1339) via U+FDD0 markers
   that appear in the rendered string; `EncodeRaw` parses them as control tokens; a caller-supplied U+FDD0 is dropped at
   encode.
4. **Unknown fields.** `chunk_cache` (top level) and `chunk` (on a message / Anthropic text block) are ignored on both
   surfaces; an unknown Anthropic block type is a 400; blocks inside a `tool_result` content array are not type-checked.

If a later change moves one of these, the pin fails and `docs/CHUNK_CACHE.md` must move with it.

### Scope

`git diff --stat origin/dev` (2 files, +695, no deletions):

```
 docs/CHUNK_CACHE.md                                |  82 +++
 .../Server/ChunkCache/ServerPinTests.cs            | 613 +++++++++++++++++++++
```

No production file, project, package, flag or DTO; no release-asset change.

### Tests (CPU, `DOTLLM_SKIP_VULKAN=1`, Release, `-m:2`, from the clean PR worktree)

| run | result |
|---|---|
| `dotnet build tests/DotLLM.Tests.Unit -c Release -m:2` | 0 errors |
| `--filter FullyQualifiedName~ServerPin` | 27 passed, 0 skipped, 0 failed (23 model-free + 4 real-GGUF tokenizer / template cases; the 4 skip when the Qwen3-4B-Instruct-2507 / Llama-3.1-8B-Instruct GGUFs are absent, so CI without models shows 23 passed / 4 skipped) |
| `--filter FullyQualifiedName~DotLLM.Tests.Unit.Server` | 891 passed, 15 skipped, 0 failed |

The real-GGUF cases load tokenizer and template metadata only (no forward pass) and resolve models through
`TestFixtureResolver`.

### Mutant evidence

Re-run on this exact cut (`git archive` of `pr/chunkcache-server-pins` `9d1899ed` into a throwaway copy, never the live
worktree), one mutant at a time against the **production** code the pins describe, `--filter
FullyQualifiedName~ServerPin`, Release, CPU, `DOTLLM_SKIP_VULKAN=1`, real GGUFs present. Baseline 27 / 27.
**10 / 10 killed**, each by the same tests as on the source branch.

| mutant | change | killed by |
|---|---|---|
| M1 | `AnthropicConverter`: text blocks joined with no separator | `Anthropic_TextBlocks_AreJoinedWithOneNewline`, `Anthropic_EmptyTextBlock_SeparatorRule` (2 cases), HTTP `Anthropic_CountTokens_ChunkFieldsIgnored_BlocksJoinedWithNewline` |
| M2 | `ConcatTextBlocks` (tool_result / system arrays) with no separator | `Anthropic_SystemBlocks_AreJoinedWithOneNewline`, `Anthropic_ToolResult_ArrayContentJoinedWithNewline_AndSplitsTheTurn`, `Anthropic_ToolResultInnerBlocks_AreNotTypeChecked` |
| M3 | unknown Anthropic block type accepted | `Anthropic_UnknownBlockType_IsRejected`, HTTP `Anthropic_UnknownBlockType_Is400InvalidRequest` |
| M4 | strict DTOs (`JsonUnmappedMemberHandling.Disallow` on `ServerJsonContext` and the HTTP options) | `OpenAi_UnknownTopLevelAndMessageFields_AreIgnored_PromptUnchanged`, `Anthropic_ChunkCacheAndChunkOnTextBlock_AreIgnored`, HTTP `OpenAi_UnknownFields_ReachTheHandler_SamePromptTokens`, HTTP `Anthropic_CountTokens_ChunkFieldsIgnored_BlocksJoinedWithNewline` |
| M5 | OpenAI `content` accepts an array of parts, joined with no separator | `OpenAi_ArrayContent_DoesNotDeserialize`, HTTP `OpenAi_ArrayContent_Is400FromBinding_EmptyBody` |
| M6 | #1339 guard off in `JinjaChatTemplate` | `ContentPath_SpecialSpellings_ArePlainText_AndTheRenderCarriesMarkers` (Qwen3, Llama-3.1), `RealGguf_ContentPathIsPlain_EncodeRawParses` (both real GGUFs: substitution on real data) |
| M7 | `EncodeRaw` never parses specials | `ChunkerEncodeRaw_ParsesSpecialSpellings_GuardedEncodeIsPlain`, both `RealGguf_ContentPathIsPlain_EncodeRawParses` |
| M8 | U+FDD0 markers not stripped at encode | `CallerSuppliedMarker_IsDroppedAtEncode`, `ChunkerEncodeRaw_...`, both `ContentPath_...` |
| M9 | Jinja `trim` is the identity | `Llama31_UserContent_IsTrimmed_InteriorKept`, `Llama31_SystemContent_IsTrimmed` |
| M10 | `tojson` of a string emits it raw | `Llama31_ToolContent_IsJsonStringEncoded` |

Not targeted by a code mutant: `Qwen3_UserAndToolContent_AreRenderedVerbatim` (golden render of the GGUF template, the
Qwen3 counterpart of the Llama-3.1 trim / tojson pins), the `["", "b"]` case of the empty-block rule (identical with or
without a separator by design), and `RealGguf_TemplateFixture_IsTheGgufMetadataTemplate` (fixture provenance).

### Conventions checklist

- [x] Targets `dev`, not `main`. `Closes #1543` would not auto-close on `dev`, and #1543 stays open for the later
      chunk_cache PRs, so this PR says `Refs #1543`.
- [x] Owning doc: new `docs/CHUNK_CACHE.md` ("Pinned server behaviour"); later PRs extend it and `docs/SERVER.md` for each
      new flag / endpoint.
- [x] STJ source-gen DTO rule: n/a (no DTO, no `JsonSerializerContext` change; no guard needed).
- [x] Correctness tests shown to fail against mutants (table above).
- [x] Flag-off identity: trivially held, no production code changes (there is no `--chunk-cache` flag yet).
- [x] No model weights committed; template fixtures were already in the repo.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
