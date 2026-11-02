# Integration spec report (chunk cache for agent harnesses)

Deliverable: `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md`. Docs only: no code changed in any dotLLM
worktree or in CodeSharp, no GPU used, nothing pushed, and no other session messaged. codesharp-d1's answers came through
the controller and are folded in.

## Verified (read in source/docs or fetched)

**This repo**
- Accuracy and speed numbers: E1, E4 and G2 (`REPORT.md`, `experiments/G2-recompute-speed/README.md`). ATTN_QPOS makes
  the whole forward 18–28× slower (kernel alone 26–31×; flat 13–19 µs per row × key). The first draft's "78× at 16K" was
  an anomalous run and is withdrawn (fix round 1). Reuse with recompute ties at 2K / 5 % and loses elsewhere; 16K / 5 %
  is an estimate of ~0.7–0.85×.
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

## Fix round 1 (review `integration-spec-review.md`)

The spec was rewritten as revision 2.

**Blocking items**
- **B1: text-first chunkers.** §5.3 item 4 makes "text-first" a wire constraint. `FixedSizeChunker` is confirmed to slice
  ids at `FixedSizeChunker.cs:41`. `lines-512` is proposed. Fixed-size chunks on the wire are blocked on E4c (§5.11),
  which also gets an extra arm with the query before the context.
- **B2: lineage and tokenisation.** Snapshot lineage is tagged `exact` / `approx`. `exact` and `shadow` tokenise as
  plain requests; segmented tokenisation is used only when reuse is applied. A `prefix_reused_approx` counter is added.
- **B3: chat templates.** Spans are located in the rendered prompt, and `chunk_template_altered` is added. Special
  tokens in chunk text are tokenised exactly as in the plain content path, else `chunk_special_tokens`.
- **B4: required changes.** A "Required library and engine changes" section (§14) lists L1–L9 with owners: server as
  sole writer, a server ledger counted by `StoredWideOrphans`, short-scope and per-index locks, the backend tag in the
  header, and engine assembly as I1/I5 work.

**Should-fix**
- **Numbers.** Corrected to 18–28× whole-forward and 26–31× kernel, a flat 13–19 µs, and 16K at ~0.7–0.85×.
- **Policies.**
  - The default is `exact`, with no change after #1540.
  - `auto` is opt-in, gated on a validated quality table (empty today) and on cost.
  - `balanced` is documented as below the bar with chunk starts or symbol chunks.
- **Query and ordering.** The query is the last user message, scored out of place. The ordering rules are scoped to
  harness-built context, and the history stays append-only.
- **`hybrid` selector.** Removed from v1.
- **Security.**
  - Counts-only responses by default.
  - `/v1/chunk-cache/*` behind API-key auth, with namespaces on by default for multi-client use.
  - `explain` and `prewarm` take text only; hash lists are dropped.
  - Encode admission (seen twice, idle only, required byte budget; ~28 GB per 100K-token session).
  - Deny-list, `no_store`, `--chunk-store-index-only`.
  - "Forget" eviction by path, namespace or all.
- **CodeSharp facts.**
  - ADR-009 is the wire choice.
  - The `AnthropicPromptCacheHandler` claim is scoped correctly.
  - There is no reload detection.
  - B3 and B9 are design-only; B5 is described in full, and B1's exception is included.
  - `RegistryPrefixCachePolicy` is in `CodeSharp.Models`.
  - `read_file` has no line numbers; its issues are CRLF and windowed reads.
  - Q3 has become a CRLF decision. Q8 records that CodeSharp has no default model. Q11 (B3 scheduling) is added.
- **External claims.**
  - LMCache in-process blending is deprecated; pin the version.
  - MCP 2025-11-25 is cited.
  - JsonPatch is marked unconfirmed for `ChatCompletionOptions`.
  - Hosted APIs' rejection of unknown fields is now taken from the reviewer.
- **Nits.**
  - `store` and `server` added to the schemas.
  - `compare` dropped from MCP v1; `lru_to_bytes` / `older_than` dropped.
  - `numbered-relative` reserved.
  - The response example's arithmetic is stated, and the example is labelled post-#1540.
  - UTF-16 vs UTF-8 offsets are explicit.
  - 400 instead of 422.
  - The Anthropic `message_delta` is named.
  - `status.missing` items are objects.
  - `GitCliInfo` is attributed to dotLLM.

**Unresolved**
- dotLLM's chat-template handling of multi-part content and of special-token strings in content is not verified (marked
  as pinned in I1).
- The Claude Code PostToolUse `updatedToolOutput` for built-in tools is unverified.
- The LMCache version to pin is not identified.
- #1540 is still not referenced in this repo.
- The ~28 GB figure (100K tokens × 288 KiB) assumes every token misses.
