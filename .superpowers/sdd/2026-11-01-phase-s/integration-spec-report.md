# Integration spec report (chunk cache for agent harnesses)

Deliverable: `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md`. Docs only: no code changed in any dotLLM
worktree or in CodeSharp, no GPU used, nothing pushed, and no other session messaged. codesharp-d1's answers came through
the controller and are folded in.

## Verified (read in source/docs or fetched)

**This repo**
- Accuracy and speed numbers: E1, E4 and G2 (`REPORT.md`, `experiments/G2-recompute-speed/README.md`). ATTN_QPOS is
  22× / 27× / 78× slower per row than ordinary prefill attention. Reuse with recompute ties at 2K / 5 % and loses
  elsewhere.
- Store costs: 288 KiB per token (F32); token ids are stored in each `.ckv`.
- Contracts:
  - `ChunkKey` with `ChunkPositioning` (`chunk-key/v3`)
  - `StoredContextAssembler.ForModel` and `GgufIdentity`
  - `ChunkRef`, `ChunkIndex.Status`, `RelativizeScan`, `StoreWideOrphans`, `AcquireStoreLock`
  - `ContextSelector.Select` signature and semantics
  - E7 re-encode costs

**dotLLM docs**
- The server has `/v1/chat/completions`, `/v1/messages` and Ollama endpoints.
- Unknown fields are ignored on both the OpenAI and Anthropic surfaces.
- Unknown Anthropic content block types are rejected with a 400. That is why the convention uses a field, not a new
  block type.
- `timings` carries `cache_n` / `prompt_n`, and `usage` carries `cached_tokens`.

**CodeSharp source**
- ADR-011 is in `decisions.md`, which also records that dotLLM is used over the OpenAI wire.
- `PrefixCacheLevel { None, PrefixCached, SingleSlot }` and `IPrefixCachePolicy` are in `src/CodeSharp.Core/PrefixCache/`.
  The answers said `CodeSharp.Models`, which is wrong.
- `AnthropicPromptCacheHandler.cs` remarks: MEAI drops per-block `cache_control` and `ChatOptions.AdditionalProperties`
  on the wire.
- Prefix-alignment rules A4 and B1–B9 come from its prefix-cache alignment spec.

**Web**
- Anthropic `cache_control`: ttl 5m / 1h, 4 breakpoints, tools → system → messages, usage fields.
- MCP 2025-06-18 tools: `outputSchema` and `structuredContent` (with a text copy "SHOULD").
- MEAI `RawRepresentationFactory`.
- LMCache blending keys, including `blend_special_str`.
- llama.cpp `cache_prompt` / `--cache-reuse` / `--slot-save-path`.
- vLLM APC block hash and `cache_salt`.

## Assumed or not verified (marked in the spec)

**Assumed (from recollection, not re-checked)**
- MAF / Semantic Kernel / LangChain type and hook names: `AIContextProvider`, `IChatReducer`, `IPromptRenderFilter`,
  `wrap_model_call`, `extra_body` merging.
- That hosted OpenAI and Anthropic APIs reject unknown fields. The spec therefore has the client strip annotations.
- Claude Code: `ANTHROPIC_BASE_URL`, and that hooks cannot edit API requests.
- Gemini / OpenAI caching details.

**Seen only in a search result**
- The openai-dotnet `JsonPatch` `Patch` property. I could not confirm it exists on `ChatCompletionOptions` at a pinned
  version.

**Taken from the user, not found in the repo**
- dotLLM #1540 as the pending kernel work. The repo docs only cite #1534 (ATTN_QPOS).

**New work the spec assumes**
- The `auto` cost model.
- `/v1/chunk-cache` endpoints (prewarm, explain).
- Background encode.
- LRU / age eviction (the store has no access-time bookkeeping).
- Chat-template span location (rendering the template with separately tokenised segments).

**Reported by codesharp-d1, not re-traced**
- CodeSharp stack positions and the mutators (ToolOutputGuard, MemoryIndexDedupe, hooks).
- SessionCompactor behaviour.
- The Hooks invalidation seam.

## Main design decisions

- **Two placements for annotations.** Inline `chunk` on a text part, or a top-level `chunk_cache` manifest with
  `{message, part, start, end}` (UTF-8 byte offsets). The manifest is the portable form (`extra_body`, HTTP body
  handler) and CodeSharp's path.
- **Identity is the exact text.** `sha256` over the UTF-8 bytes; the server re-hashes and tokenises the text alone.
  `id` is telemetry only. Stale chunks miss, and a client cannot poison the store.
- **Policies** are `exact`, `shadow`, `balanced`, `fast` and `auto`. `auto` falls back to `exact` until #1540 makes
  recompute pay. `shadow` measures hit rates with no quality risk.
- **Exact and approximate reuse are reported separately.** `cached_tokens` / `cache_n` stay exact-only, because
  CodeSharp's B9 monitor depends on that. Chunk reuse is reported in `chunk_cache` and in `timings.chunk_n`.
- **Render profiles.** Absolute line numbers inside chunk text defeat incremental reuse. Use `plain` with glue headers,
  or `numbered-relative`.
- **Transport.** HTTP is the reference. In-process hosting is only for GPL-compatible hosts, and is excluded for
  CodeSharp by ADR-011.
- **CodeSharp prefix-cache levels.** I propose a `ChunkReuse` capability flag next to `PrefixCacheLevel` rather than a
  fourth level, and leave the choice to them. The spec has a rule-relaxation table and a chunk-aware compaction planner.
- **Transparent mode.** Block-hash mode is opt-in on the server only, and treats a block as reusable from its second
  sighting. Delimiter mode is not recommended.

## Open questions

- The ten questions for codesharp-d1 are in §12.7 of the spec.
- For the user and the dotLLM session:
  1. Confirm #1540's scope (kernel speed for ATTN_QPOS).
  2. Server surface naming and endpoint ownership (`/v1/chunk-cache`).
  3. Licence of the client package: it must be permissive for CodeSharp under ADR-011.
  4. Whether prewarm may use a second slot on a single-slot server.
