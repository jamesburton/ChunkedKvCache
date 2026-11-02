# Chunk-level KV reuse: integration spec for agent harnesses

Status: draft for review, 2026-11-02. Companion to `2026-10-31-chunk-kv-reuse-design.md` (the research and engine
design) and the Phase S plan (`docs/superpowers/plans/2026-11-01-phase-s-store-cli-e4b.md`). The user has agreed to the
overall shape: a runtime wire convention in the dotLLM server, a library + `chunkcache` CLI + thin MCP control plane, and
harness integration with CodeSharp as the reference. The details below are the author's proposal unless marked
**[user]**.

Evidence labels used throughout:
- **[verified]**: read in this repo, in dotLLM or CodeSharp source/docs, or on a cited web page on 2026-11-02.
- **[reported]**: stated by another session (codesharp-d1 answers, `.superpowers/sdd/2026-11-01-phase-s/codesharp-answers.md`)
  and not re-traced by me.
- **[assumption]**: my inference or recollection; check it before building on it.

## 1. Goals, non-goals

**Goals**
1. Any harness that talks to a local dotLLM server over HTTP can mark parts of its prompt as **reusable chunks** and get
   position-independent KV reuse: the server assembles those chunks from its persistent store, recomputes a selected
   share of tokens, then generates. **[user]**
2. **Graceful degradation.** A request that carries chunk annotations is still a valid request. A server that does not
   understand them, or a model that cannot use them, gives the same answer as plain text with full prefill. **[user]**
3. **One identity rule for everything:** a chunk is its exact text. Ids, paths and line ranges are labels for telemetry.
   Lookup always goes text → server tokenisation → `ChunkKey` (model fingerprint, tokenizer, RoPE, schema version,
   backend, dtype, positioning, token ids; `experiments/store/README.md`). A stale chunk therefore **misses**; it can
   never hit wrongly.
4. A control plane (library, CLI, MCP) to build, prewarm, select, inspect and evict, so harnesses and humans can manage the
   store without touching the inference path. **[user]**
5. Harness guidance that keeps reuse high across the events that destroy an exact prefix cache: compaction, sub-agents,
   resumed sessions, reordered file reads, edits. **[user]**
6. Honest telemetry: every response says what was reused, recomputed, missed, and why.

**Non-goals (this spec)**
- Remote/cloud providers. Anthropic, OpenAI and Gemini only offer exact-prefix caching
  ([Anthropic](https://platform.claude.com/docs/en/build-with-claude/prompt-caching),
  [OpenAI](https://platform.openai.com/docs/guides/prompt-caching), [Gemini](https://ai.google.dev/gemini-api/docs/caching)).
  Annotations must be stripped before a request goes to them (§5.7).
- Recurrent and hybrid models (Gated DeltaNet / Mamba layers, e.g. `qwen4exp`). That is Phase T. v1 is attention-only
  (Qwen3-4B, Llama-3.1-8B class).
- Contextual (non-isolated) chunk encodings, chunks by reference without text, and multi-tenant shared stores. Fields are
  reserved but the semantics are deferred (§5.9).
- Opening PRs against other harnesses (Semantic Kernel, LangChain, Claude Code). Deferred **[user]**.

## 2. Honest limits (read before integrating)

1. **Needs a local runtime that owns the KV.** Reuse happens inside the inference engine. Only dotLLM implements it. An
   MCP server, a proxy in front of a hosted API, or a client library cannot make a remote model reuse KV (§7.1).
2. **Naive reuse loses accuracy; recompute is what fixes it, and recompute is currently slow.**
   - Naive concatenation (no recompute): KL vs full prefill 0.13 / 0.17 / 0.55 / 0.67 nats at 2K / 4K / 8K / 16K (E1). On
     the 2K masked-call tasks, exact match is 5 of 28 against 28 of 28 for full prefill (G2 quality table). **[verified]**
   - With recompute: chunk starts recover 0.65–0.82 of the naive→full gap at 5–20 %, and query relevance 0.70–0.83 with
     symbol chunks or 0.87–0.97 with fixed 512-token chunks (E4, `REPORT.md`). The 95 % / 20 % quality bar holds as a
     point estimate for fixed chunks with query relevance only. One model, small clustered samples. **[verified]**
   - **Speed (G2, Vulkan, Qwen3-4B):** naive assembly is 22× / 62× / 107× faster than full prefill at 2K / 8K / 16K. With
     recompute, reuse **ties at best (2K, 5 %: 1.07×) and loses everywhere else** (8K 20 %: 0.20×; 16K 5 %: 0.24×).
     **[verified]**
   - **The bottleneck is one kernel:** the per-query-position attention (`ATTN_QPOS`, dotLLM #1534) is 22× / 27× / 78×
     slower per row than ordinary prefill attention at 2K / 8K / 16K. With a kernel as fast as the ordinary one, 20 %
     recompute at 2K would be about 2.8× faster than full prefill, and 5 % at 16K about 5.7× (G2 control arm).
     **[verified]**
   - The kernel work is pending as **dotLLM #1540** **[user]**. Until it lands, the server's `auto` policy (§5.5) must
     choose full prefill for most requests. Integration work before then buys plumbing, hit-rate data and shadow
     measurements, not TTFT.
3. **Query relevance is the best selector, and it needs the query.** The query-attention probe is a lab implementation
   costing seconds on CPU. A fused probe is a separate dotLLM item, and the Vulkan probe is Phase S Task 5 on the Vulkan
   side. Until then: chunk starts (free, static) is the default; query relevance is opt-in.
4. **Storage is large.** F32 rows cost 288 KiB per token for Qwen3-4B. A 1.5 M-token repository is about 442 GB, and the
   2K-token context alone is 576 MiB. F16 / Q8_0 rows (≈ 0.5× / 0.27×) are deferred to the persistent-caching phase
   (progress ledger, "phase D"). **[verified]**
5. **Cold chunks cost as much as prefill.** A miss must be encoded (G2: 3.4× the full prefill at 2K, including the slow
   readback). Reuse pays only on the second and later uses of a chunk, so prewarming (§6) matters.
6. **Tokenisation seams.** A chunk is tokenised alone, so the prompt's token stream is the concatenation of separately
   tokenised segments. That can differ from tokenising the whole prompt at the seams. Symbol chunks already work this way
   (+0.4 % tokens corpus-wide, E7). Full-prefill A/B comparisons must use the same segmented tokenisation, or the
   difference must be reported. **[verified for the token count; quality effect unmeasured]**

## 3. Where reuse helps an agent, and why chunks beat the prefix cache

dotLLM already keeps prompt-prefix snapshots and reports `cached_tokens` / `cache_n` (`dotLLM/docs/SERVER.md`)
**[verified]**. An append-only conversation on one slot is served well by that, and CodeSharp's prefix-cache alignment
spec is built around keeping it alive **[verified]**. Chunk reuse adds value exactly where the exact prefix dies:

| event | prefix cache | chunk reuse |
|---|---|---|
| compaction rewrites the middle of history | miss from the first changed message onward | chunks re-emitted after the summary hit again |
| a sub-agent starts with another system prompt and re-reads the same files | miss (different prefix) | hit |
| a resumed session after a server restart or model reload | miss (snapshots are in memory) | hit (store is on disk) |
| files read in a different order, or a selection re-ranked | miss after the first difference | hit (position-independent) |
| one file edited | everything after it re-prefilled | only the edited chunk misses (E7: median 234 tokens re-encoded with symbol chunks) |
| a single-slot server evicted by a side call | full re-read | chunks hit; only glue and query are prefilled |

Combining both: on a request, the server first matches the exact prefix (bit-exact, free), then assembles annotated chunks
after it, then prefills the rest. After generation the resulting state is snapshotted as usual, so the **next** turn hits
the exact prefix again, including the recomputed chunks.

## 4. Architecture

```
harness (MAF / SK / LangChain / Claude Code / custom)
  ├─ chunk source: file reads → ChunkSpans (same chunker + render profile as the store)
  ├─ ChunkAnnotatingChatClient (records spans per request)
  └─ HTTP body handler → POST /v1/chat/completions (+ chunk_cache)   ──►  dotLLM server
                                                                          ├─ exact prefix match (existing)
control plane: chunkcache CLI / MCP / library ──► store root ◄────────────├─ chunk assembly from store (Phase S)
   build · prewarm · select · status · evict · compare · explain          ├─ selective recompute (G2; #1540)
                                                                          └─ prefill rest, generate, snapshot
```

- **Transport is HTTP by default.** CodeSharp's ADR-011 integrates GPL components (dotLLM) only across a process
  boundary **[verified, `CodeSharp/docs/architecture/decisions.md`]**, and CodeSharp talks to dotLLM only through OpenAI
  Chat Completions **[reported; verified that `decisions.md` records the choice of that wire]**. In-process hosting is an
  optional variant for harnesses that may link dotLLM (§8.4). It is not the reference path.
- **The store is shared by the server and the control plane** through a store root on disk, coordinated by
  `ChunkIndex.AcquireStoreLock(storeRoot, timeout)` (an exclusive `.chunkstore.lock`, held from update through put and save
  to eviction) **[verified, task-4 report]**. The server owns `Put`; the CLI owns index updates and eviction.

## 5. Wire convention (v1)

### 5.1 Two equivalent placements

The same annotation can travel in two ways; the server normalises both to one internal manifest.

**(A) Inline, on a text content part** (closest to Anthropic's per-block `cache_control`):

```json
{"role": "tool", "tool_call_id": "call_7", "content": [
  {"type": "text", "text": "// src/Store/ChunkIndex.cs (lines 365-412)\n"},
  {"type": "text", "text": "public IndexDiff Update(...)\n{ ... }\n",
   "chunk": {"v": 1, "id": "src/Store/ChunkIndex.cs:365-412@14211",
             "hash": "sha256:9f2c…", "render": "plain", "chunker": "symbol-512"}}
]}
```

**(B) Top-level manifest** (`chunk_cache` in the request body, which works through `extra_body`-style hooks that cannot
reach content parts):

```json
{"model": "qwen3-4b", "messages": [...],
 "chunk_cache": {"v": 1, "policy": "balanced",
   "chunks": [{"id": "src/Store/ChunkIndex.cs:365-412@14211", "hash": "sha256:9f2c…",
               "at": {"message": 3, "part": 1}},
              {"id": "src/Store/ChunkRef.cs:1-40@0", "hash": "sha256:41ab…",
               "at": {"message": 3, "part": 2, "start": 0, "end": 1830}}]}}
```

- **Why both.** Most client SDKs cannot add a field to one content part. The MEAI OpenAI and Anthropic bridges drop
  per-content `AdditionalProperties` on the wire (CodeSharp's wire capture in `AnthropicPromptCacheHandler.cs`
  **[verified]**). A top-level field can be added by `extra_body` (Python OpenAI SDK, LangChain `ChatOpenAI`) or by a
  body-rewriting HTTP handler **[assumption for the Python SDKs; standard documented behaviour]**. Inline is the canonical
  form for hand-built bodies.
- **Why not a new content-part type.** dotLLM's Anthropic surface **rejects unknown content block types with a 400**
  (`dotLLM/docs/ANTHROPIC_API.md`) **[verified]**. A new type would break degradation. Unknown *fields* are ignored on both
  dotLLM surfaces (`SERVER.md`: STJ source-gen skips unmapped members; `ANTHROPIC_API.md`: "Unknown fields are ignored,
  not rejected") **[verified]**.
- **Both placements in one request** are an error (`chunk_manifest_conflict`). It is a warning, and the request is
  served as plain text, unless the request is strict.

### 5.2 Fields

`chunk` (inline) or `chunk_cache.chunks[i]` (manifest):

| field | type | req | meaning |
|---|---|---|---|
| `v` | int | yes (inline; inherited from `chunk_cache.v` in the manifest) | convention version, `1` |
| `hash` | string | yes | `sha256:` + lowercase hex of the UTF-8 bytes of the chunk text exactly as sent (§5.3) |
| `id` | string ≤ 256 | yes | the caller's stable label, e.g. `ChunkRef.Id` (`path:startLine-endLine@offset`). Telemetry only; never used for lookup |
| `at` | object | manifest only | `{message, part[, start, end]}`: indices into `messages` and its `content` array. `start` / `end` are UTF-8 byte offsets into that part's text, end exclusive; omitted = the whole part |
| `render` | string | no | name of the render profile that produced the text (§5.4), e.g. `plain`, `numbered`; default `plain` |
| `chunker` | string | no | chunker name (`symbol-512`, `fixed-512`); lets `explain` and prewarm match the store's index |
| `source` | object | no | `{path, start_line, end_line, rev}`: provenance for telemetry and `explain`. Never read by the server in v1 |
| `positioning` | `"isolated"` | no | only `isolated` in v1 (encoded alone at positions 0..n-1, RoPE-shifted on assembly; `ChunkPositioning.Isolated`, key scheme `chunk-key/v3`) **[verified]**. `contextual` is reserved |
| `stability` | `"stable"` \| `"volatile"` | no | a hint: `volatile` chunks (e.g. a file being edited this turn) are not prewarmed and are first to lose recompute budget |

`chunk_cache` (request level):

| field | default | meaning |
|---|---|---|
| `v` | 1 | version |
| `policy` | `"auto"` | `exact` / `balanced` / `fast` / `auto` / `shadow` (§5.5) |
| `recompute` | server default | `{selector: "auto"\|"chunk_starts"\|"query_relevance"\|"hybrid"\|"none", budget: 0.0–1.0, max_tokens}` |
| `on_miss` | `"prefill"` | `prefill`: a missing chunk is prefilled in place like ordinary text (exact) and its isolated encode is queued in the background. `encode`: encode it now, store it, then assemble |
| `strict` | false | errors instead of degradation (§5.8) |
| `min_chunk_tokens` | 32 | chunks shorter than this are treated as plain text |
| `report` | `"summary"` | `none` / `summary` / `per_chunk` |
| `namespace` | none | reserved for multi-tenant stores (§10) |

### 5.3 Hashing and identity rules

1. The hash covers the **exact UTF-8 bytes** the model will see, with no normalisation: CRLF vs LF, BOM, trailing
   whitespace and tabs all count. The CodeSharp / Roslyn scanner normalises CRLF to LF before chunking
   (`experiments/solution-scan/README.md`) **[verified]**, so harnesses must send the same LF text or the chunk misses.
2. The server **recomputes the hash** from the text it received. A mismatch means the annotation is ignored and the span
   is served as plain text (warning `chunk_hash_mismatch`; an error if strict). A client therefore cannot make the server
   store KV for text it did not send. The KV is always computed by the server from the received text (no store poisoning
   through the wire).
3. `id` is never trusted for lookup. Two different texts with the same id are two chunks; the same text under two ids is
   one store entry (no path in the key) **[verified]**.
4. The server's key is `ChunkKey` over the token ids of the text tokenised **alone**. A chunk hits across files,
   sessions, harnesses and positions as long as the bytes and the model identity match.
5. Spans in one part must not overlap, must be in order, and must fall on UTF-8 character boundaries. Text between and
   around spans is glue (prefilled normally).

### 5.4 Render profiles: what the chunk text should look like

The chunk text must be what the model sees, so the harness's file-read formatting decides whether the store can hit.

- **Use `plain`.** Raw file text of the chunk, with a header such as `// path (lines a-b)` sent as **glue outside the
  span**. Then a line inserted above a method changes only the glue, not the chunk.
- **Avoid absolute line numbers inside chunk text** (`cat -n` style, `   1→…`). An insertion near the top of a file shifts
  every later line number, so every later chunk of the file misses, which wipes out the symbol-chunk advantage E7 measured
  (median 234 tokens re-encoded per edit vs the whole tail of the file). If a harness must number lines, use the
  `numbered-relative` profile (numbers restart at 1 in each chunk) and put the absolute start line in the glue header.
- Prewarming (§6) must use the same profile and chunker as the harness, or prewarmed entries never match.

### 5.5 Policies and the server's decision

| policy | what the server does |
|---|---|
| `exact` | no approximate reuse. Chunks are used only for reporting what would have hit and for background encode. Output is identical to plain text |
| `shadow` | as `exact`, plus the server computes the reuse plan (hits, selection, predicted cost) without using it, and reports it. Used to measure hit rates before trusting quality |
| `balanced` | reuse with recompute. Selector: `query_relevance` when a query segment exists and the probe is available on the backend, else `chunk_starts`. Budget 15 % (fixed chunks) or 20 % (symbol chunks) by default, following E4 |
| `fast` | reuse with chunk starts at 5 %, or naive when `budget: 0`. Documented as lossy |
| `auto` (default) | `balanced` when the cost model predicts reuse TTFT < full-prefill TTFT for this request, otherwise `exact`. The cost model uses the measured per (row × visible key) cost on the active backend (G2: about 15–18 µs at 2K–8K and 65 µs at 16K on the current ATTN_QPOS kernel) **[verified numbers; the cost model is new work]** |

- **Until dotLLM #1540 lands, `auto` resolves to `exact` for nearly every request** (G2 needed speedups table). That is
  intended: the convention can ship before it pays.
- **Query segment.** The tokens after the last chunk, up to the generation prompt. The selector uses them as the query.
  Hence the ordering rule in §5.6.
- **Prefix interplay.** Chunks inside the exact-prefix match are reported as `prefix` (exact, no recompute). Assembly
  starts after the matched prefix.
- **Model support.** On a recurrent or hybrid model, or on a backend without assembly support, every policy degrades to
  `exact` with reason `chunk_model_unsupported`.

### 5.6 Ordering rules

Reuse is position-independent, but quality and prefix reuse are not indifferent to order:

1. **System prompt and tool block first, byte-stable.** That part is served by the exact prefix cache.
2. **Stable chunks next, in a deterministic order** (e.g. `SelectionResult.InDocumentOrder()`, which is path then offset
   **[verified]**), so the exact prefix also survives across turns when the selection does not change.
3. **Volatile chunks after stable ones.**
4. **The question or task last.** Query relevance needs the query after the context, and the recompute's benefit falls on
   tokens that attend to the chunks.
5. Within one tool result, one part per chunk (or manifest spans) plus glue headers.

A violation is not an error. Out-of-order chunks are still assembled; the response notes `ordering` warnings (e.g.
`query_before_chunks`) so harness authors can see the cost.

### 5.7 Fallback behaviour

| situation | behaviour |
|---|---|
| server without the convention (llama.cpp, vLLM, Ollama, old dotLLM) | dotLLM and llama.cpp ignore unknown fields **[verified for dotLLM; assumption for llama.cpp]**. The request is plain text |
| hosted APIs (OpenAI, Anthropic) | **they reject unknown parameters** **[assumption from SDK behaviour; verify per provider]**. The client wrapper must strip `chunk` / `chunk_cache` unless the capability probe (§5.10) succeeded. CodeSharp's provider switch knows the provider, so this is cheap |
| hash mismatch, bad span, overlap | that annotation is ignored; warning |
| store unavailable or busy (`ChunkStoreBusyException`) | misses; the request is served (Task 3: store failures are misses) **[verified]** |
| unsupported model or backend | `exact`, with a reason |
| `strict: true` | any of the above becomes an error (§5.8) |

### 5.8 Errors and warnings

Error envelope as on the existing surfaces (`{"error": {"message", "type", "param", "code"}}` for OpenAI-style,
`{"type": "error", "error": {...}}` for Anthropic) **[verified]**. Codes are the same in strict errors and non-strict
`warnings[]`:

| code | HTTP (strict) | when |
|---|---|---|
| `chunk_version_unsupported` | 400 | `v` not in the server's `versions` |
| `chunk_hash_mismatch` | 400 | recomputed hash differs |
| `chunk_span_invalid` | 400 | `at` out of range, overlapping, not on a UTF-8 boundary, or the part is not text |
| `chunk_manifest_conflict` | 400 | inline and manifest both present |
| `chunk_model_unsupported` | 422 | model or backend cannot assemble |
| `chunk_policy_unavailable` | 422 | e.g. `query_relevance` with no probe on this backend |
| `chunk_store_unavailable` | 503 | store root missing, locked past timeout, out of space |
| `chunk_too_many` | 400 | above the server's `max_chunks_per_request` |

Warnings only: `chunk_ignored_too_short`, `query_before_chunks`, `chunk_render_unknown`, `chunk_encode_queued`.

### 5.9 Response metadata

A top-level `chunk_cache` object in the blocking response, in the final streaming chunk (next to `usage` and `timings`), and
on the Anthropic surface as a top-level field of the message:

```json
"chunk_cache": {
  "v": 1, "policy_requested": "auto", "policy_applied": "balanced", "reason": "cost_model_win",
  "chunks": {"annotated": 14, "prefix": 3, "hit": 9, "miss": 1, "repeat": 0, "ignored": 1},
  "tokens": {"prompt": 18340, "prefix_reused": 2210, "chunk_reused": 13420, "chunk_recomputed": 2013,
             "encoded": 412, "prefilled": 2298},
  "recompute": {"selector": "query_relevance", "budget": 0.15, "rows": 2013, "forwards": 1, "attn_kernel": "qpos"},
  "timings_ms": {"assembly": 76, "recompute": 1540, "encode": 0, "probe": 12, "prefill": 410,
                 "full_prefill_estimate": 6100},
  "warnings": [{"code": "chunk_ignored_too_short", "id": "src/A.cs:1-3@0"}],
  "per_chunk": [{"id": "...", "hash": "sha256:…", "status": "hit", "tokens": 486, "recomputed": 73}]
}
```

- `per_chunk` appears only with `report: "per_chunk"`.
- **`usage.prompt_tokens_details.cached_tokens` and `timings.cache_n` keep meaning exact prefix reuse only.** Approximate
  chunk reuse is not mixed into them. CodeSharp's cache-miss monitor (B9) compares `cached_tokens` with the previous
  prompt length **[verified, CodeSharp prefix-cache spec]**, and Anthropic and OpenAI define these counts as exact cache
  reads **[verified for Anthropic]**. New `timings` fields beside the llama.cpp names: `chunk_n` (reused) and
  `chunk_recomputed_n`.
- `/metrics` gains counters: hits, misses, recomputed rows, store bytes, and policy decisions by reason.

### 5.10 Versioning and capabilities

- `GET /v1/chunk-cache` returns:

  ```json
  {"versions": [1], "policies": ["exact", "shadow", "balanced", "fast", "auto"],
   "selectors": ["chunk_starts", "query_relevance"], "renders": ["plain", "numbered-relative"],
   "model": {"id": "...", "supported": true, "reason": null, "fingerprint": "gguf-sha256:…"},
   "store": {"root_id": "…", "entries": 0, "bytes": 0, "dtype": "f32"}, "max_chunks_per_request": 4096}
  ```

  The store path is not exposed, only an opaque `root_id`. A 404 means "no convention: strip annotations".
- Additive fields keep `v: 1`. A change in meaning (hash rule, positioning, span units) bumps `v`. Servers list every
  version they accept.
- Store-format changes are invisible on the wire: they change `ChunkKey` (schema version, key scheme), so old entries
  simply miss **[verified]**.

## 6. Transparent mode (server recognises stable blocks itself)

**Feasible, opt-in on the server only, never the default.**

- **Mechanism (block-hash mode).** With `--chunk-transparent`, the server treats every text part, or every tool-result
  content, of at least `min_chunk_tokens` as a candidate chunk. Its identity is the part's own text hash, exactly as if it
  had been annotated with `at: {message, part}`.
  - A candidate becomes reusable after it has been seen `N` times (default 2), so one-off text is not encoded.
  - Harnesses that already send one file read per tool result get reuse with no client change. This is the only route for
    Claude Code via `ANTHROPIC_BASE_URL` (§9).
- **Delimiter mode: not recommended.** For example, LMCache marks chunk boundaries in-band with a separator string
  (`blend_special_str`, default `" # # "`, with `enable_blending` and `blend_recompute_ratios`;
  [LMCache configuration](https://docs.lmcache.ai/api_reference/configurations.html) **[verified]**). Its risks:
  - A server without the convention passes the delimiters to the model as text.
  - File content can contain the delimiter. Prompt injection could forge chunk boundaries. A per-server nonce in the
    delimiter (read from `/v1/chunk-cache`) mitigates this, but requires the client to know the nonce, at which point it
    could annotate properly.
  - Stripping the delimiters changes the text the model sees compared with the same request on a plain server.
- **Risks of transparent mode in general:**
  - It silently changes outputs for clients that did not ask for approximate reuse. Unless the operator sets a default
    policy, it therefore applies only `exact` or `shadow` behaviour, and a client opts in per request with
    `chunk_cache.policy`.
  - Granularity is the whole block. A file read as one block is one chunk, so an edit anywhere in it misses the whole file
    (the fixed-chunk problem from E7, but worse).
  - It cannot see render profiles or ids, so telemetry is hash-only.
  - It is a timing side channel across clients of the same server (§10).

## 7. Control plane: library, `chunkcache` CLI, MCP

### 7.1 What MCP can and cannot do

- **Can:** expose store management as tools (build, prewarm, select, status, evict, compare, explain) with typed inputs
  and outputs (`inputSchema`, optional `outputSchema`, `structuredContent` plus a serialised text copy for compatibility;
  [MCP 2025-06-18 tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) **[verified]**). `select`
  can return chunk text as its result. When the host model is served by dotLLM in transparent mode, those returned blocks
  are then reusable.
- **Cannot:** change how the host builds its prompt, add fields to the host's API request, or touch the KV of a model it
  does not run. A tool result is just content the host places where it likes. With a hosted model behind the host (Claude
  Code with Anthropic's API), MCP only manages a local store and selects context. It gives **no** TTFT benefit.
- Hence: "thin" control plane. The inference path is the HTTP convention, and MCP is for agents and humans to manage the
  store.

### 7.2 Tools

The CLI verbs (`chunkcache build|select|status|evict|compare`, plan Task 7) map one to one. `prewarm` and `explain` are
added here. Every tool takes `store` (a store root; default from config) and returns `structuredContent` matching its
`outputSchema`. The schemas are abbreviated to their properties; all objects have `additionalProperties: false` except
where noted.

**`chunkcache_build`**: scan a solution or folder, chunk it, update the index, and (with `encode`) encode missing chunks.
```json
{"input": {"type": "object", "required": ["path"], "properties": {
   "path": {"type": "string", "description": ".sln/.slnx/.csproj or folder"},
   "model": {"type": "string", "description": "model id/path; required when encode=true"},
   "chunker": {"enum": ["symbol-512", "fixed-512"], "default": "symbol-512"},
   "render": {"enum": ["plain", "numbered-relative"], "default": "plain"},
   "configuration": {"type": "string", "default": "Release"},
   "encode": {"type": "boolean", "default": false},
   "max_encode_tokens": {"type": "integer"}, "strict_model_id": {"type": "boolean", "default": false}}},
 "output": {"type": "object", "properties": {
   "files": {"type": "integer"}, "chunks": {"type": "integer"}, "tokens": {"type": "integer"},
   "added": {"type": "integer"}, "removed": {"type": "integer"}, "unchanged": {"type": "integer"},
   "encoded_tokens": {"type": "integer"}, "store_bytes": {"type": "integer"},
   "skipped_projects": {"type": "array", "items": {"type": "object", "properties": {
       "project": {"type": "string"}, "reason": {"type": "string"}}}},
   "elapsed_ms": {"type": "integer"}}}}
```

**`chunkcache_select`**: `ContextSelector.Select` over the index and graph **[verified API, selection-tools README]**.
```json
{"input": {"type": "object", "properties": {
   "paths": {"type": "array", "items": {"type": "string"}}, "exclude": {"type": "array", "items": {"type": "string"}},
   "symbol": {"type": "string"}, "hops": {"type": "integer", "default": 1, "maximum": 100},
   "changed_since": {"type": "string"}, "token_budget": {"type": "integer"},
   "include_text": {"type": "boolean", "default": false},
   "order": {"enum": ["rank", "document"], "default": "document"}}},
 "output": {"type": "object", "properties": {
   "chunks": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "path": {"type": "string"}, "start_line": {"type": "integer"},
      "end_line": {"type": "integer"}, "tokens": {"type": "integer"}, "hash": {"type": "string"},
      "reason": {"type": "string"}, "detail": {"type": "string"}, "hop": {"type": "integer"},
      "stored": {"type": "boolean"}, "text": {"type": "string"}}}},
   "selected_tokens": {"type": "integer"}, "candidate_tokens": {"type": "integer"},
   "trimmed": {"type": "integer"}, "unmatched_patterns": {"type": "array", "items": {"type": "string"}},
   "notes": {"type": "array", "items": {"type": "string"}}}}}
```
`hash` here is the wire hash of the chunk's rendered text under the index's render profile, so a harness can annotate
without re-hashing.

**`chunkcache_status`**: `ChunkIndex.Status(store, currentFiles)` **[verified API]**.
```json
{"input": {"type": "object", "properties": {"path": {"type": "string"}, "model": {"type": "string"},
   "list_missing": {"type": "boolean", "default": false}}},
 "output": {"type": "object", "properties": {
   "total_chunks": {"type": "integer"}, "missing_chunks": {"type": "integer"}, "missing_tokens": {"type": "integer"},
   "up_to_date": {"type": "boolean"}, "stale_files": {"type": "array", "items": {"type": "string"}},
   "new_files": {"type": "array", "items": {"type": "string"}}, "deleted_files": {"type": "array", "items": {"type": "string"}},
   "missing": {"type": "array", "items": {"type": "string", "description": "path:a-b missing (n tokens)"}},
   "store_bytes": {"type": "integer"}, "entries": {"type": "integer"}, "temp_files": {"type": "integer"}}}}
```

**`chunkcache_evict`**: only keys no index under the store references (`EvictableOrphans` / `StoreWideOrphans`, under the
store lock) **[verified]**, or a size or age budget over those.
```json
{"input": {"type": "object", "properties": {
   "mode": {"enum": ["orphans", "lru_to_bytes", "older_than"], "default": "orphans"},
   "target_bytes": {"type": "integer"}, "older_than_days": {"type": "integer"},
   "dry_run": {"type": "boolean", "default": true}}},
 "output": {"type": "object", "properties": {
   "evicted": {"type": "integer"}, "freed_bytes": {"type": "integer"}, "kept_referenced": {"type": "integer"},
   "dry_run": {"type": "boolean"}}}}
```
`lru_to_bytes` and `older_than` need access-time bookkeeping the store does not have yet **[assumption: new work]**.

**`chunkcache_prewarm`**: encode the chunks a likely next request needs (`select` output, or explicit hashes) through the
server, so the encode happens off the critical path. It is an HTTP call to `POST /v1/chunk-cache/prewarm`, which uses the
server's loaded model, so the keys match what requests will look up.
```json
{"input": {"type": "object", "properties": {
   "select": {"type": "object", "description": "same shape as chunkcache_select input"},
   "texts": {"type": "array", "items": {"type": "object", "properties": {
       "id": {"type": "string"}, "text": {"type": "string"}}}},
   "server": {"type": "string", "default": "http://127.0.0.1:8080"},
   "max_tokens": {"type": "integer"}, "priority": {"enum": ["idle", "now"], "default": "idle"}}},
 "output": {"type": "object", "properties": {
   "requested": {"type": "integer"}, "already_stored": {"type": "integer"}, "encoded": {"type": "integer"},
   "encoded_tokens": {"type": "integer"}, "queued": {"type": "integer"}, "elapsed_ms": {"type": "integer"}}}}
```
`priority: "idle"` must respect a single-slot server: prewarm is a side call that would evict the session snapshot (the
`SideCallEvictsSession` rule in CodeSharp **[verified]**). The server should run prewarm only while idle, or into a
separate slot.

**`chunkcache_compare`**: the plan's `compare` (quality vs prefill table) over a task file.
```json
{"input": {"type": "object", "required": ["task_file", "model"], "properties": {
   "task_file": {"type": "string"}, "model": {"type": "string"},
   "selectors": {"type": "array", "items": {"type": "string"}, "default": ["chunk_starts", "query_relevance"]},
   "budgets": {"type": "array", "items": {"type": "number"}, "default": [0.05, 0.1, 0.2]},
   "chunkers": {"type": "array", "items": {"type": "string"}, "default": ["fixed-512", "symbol-512"]},
   "backend": {"enum": ["cpu", "vulkan"], "default": "vulkan"}}},
 "output": {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "object", "properties": {
   "chunker": {"type": "string"}, "selector": {"type": "string"}, "budget": {"type": "number"},
   "kl": {"type": "number"}, "top1": {"type": "number"}, "em": {"type": "number"},
   "recomputed_tokens": {"type": "integer"}, "forwards": {"type": "integer"},
   "reuse_ms": {"type": "number"}, "full_prefill_ms": {"type": "number"}, "path": {"type": "string"}}}}}}}
```
It runs model forwards. On a shared GPU that needs the user's go-ahead (machine policy), so the tool must say so in its
description and refuse unless invoked with an explicit `confirm_gpu: true` (not shown).

**`chunkcache_explain`**: why a request did or did not reuse. Given a request body (or a hash list) and the server, it
returns the per-chunk analysis without generating.
```json
{"input": {"type": "object", "properties": {
   "request": {"type": "object", "additionalProperties": true},
   "hashes": {"type": "array", "items": {"type": "string"}}, "server": {"type": "string"}}},
 "output": {"type": "object", "properties": {
   "policy_would_apply": {"type": "string"}, "reason": {"type": "string"},
   "chunks": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "status": {"enum": ["prefix", "hit", "miss", "ignored"]},
      "why": {"type": "string", "description": "e.g. hash mismatch, render differs from index, too short, other model"},
      "nearest_index_entry": {"type": "string"}}}},
   "predicted_ms": {"type": "object", "properties": {"reuse": {"type": "number"}, "full_prefill": {"type": "number"}}},
   "warnings": {"type": "array", "items": {"type": "string"}}}}}
```
It is served by `POST /v1/chunk-cache/explain` (a dry run of §5.5). `nearest_index_entry` looks up the same `id` / path in
the index to diagnose "the file changed" vs "the render differs".

## 8. .NET wrapper abstractions

### 8.1 Design constraints (from CodeSharp's experience)

- **Do not rely on `AIContent.AdditionalProperties` reaching the wire.** CodeSharp observed `ChatOptions.AdditionalProperties`
  silently dropped (`reasoning_effort` "for months") and no per-block `cache_control` in the MEAI Anthropic bridge (wire
  capture) **[verified, `AnthropicPromptCacheHandler.cs` remarks]**.
- `ChatOptions.RawRepresentationFactory` lets a caller pre-build the provider's options object
  ([docs](https://learn.microsoft.com/en-us/dotnet/api/microsoft.extensions.ai.chatoptions.rawrepresentationfactory))
  **[verified]**. Extra JSON on OpenAI .NET models goes through the experimental `JsonPatch Patch` property
  (openai-dotnet [PR #834](https://github.com/openai/openai-dotnet/pull/834.diff); used by Semantic Kernel
  [PR #13934](https://github.com/microsoft/semantic-kernel/pull/13934)) **[reported by search results; not verified for
  `ChatCompletionOptions` at our pinned version]**. That reaches top-level fields only, and is fragile.
- **Therefore the reference transport is an HTTP body handler**, the seam CodeSharp already uses for Anthropic
  `cache_control`, Claude Code identity and thinking summaries: an MEAI decorator records the annotations, and a
  `DelegatingHandler` on the provider's `HttpClient` writes the `chunk_cache` manifest (placement B) into the JSON body.

### 8.2 Interfaces (sketch; package `DotLLM.ChunkCache.Client`, MIT-compatible, no dotLLM engine reference)

```csharp
namespace DotLLM.ChunkCache.Client;

/// One chunk inside one message part, identified by its exact text.
public sealed record ChunkSpan(
    string Id, string Hash,                 // "sha256:<hex>" of UTF-8 bytes of the span text
    int Start = 0, int? End = null,         // UTF-8 byte offsets inside the part's text; null End = to the end
    string Render = "plain", string? Chunker = null,
    ChunkSourceInfo? Source = null, bool Volatile = false);

public sealed record ChunkSourceInfo(string Path, int StartLine, int EndLine, string? Revision);

/// Produces chunked, rendered text for a file the harness is about to show the model.
public interface IChunkSource
{
    /// Reads and chunks the file (same chunker and render profile as the store's index).
    ValueTask<ChunkedText> ReadAsync(string path, LineRange? range, CancellationToken ct);
}
public sealed record ChunkedText(string Text, IReadOnlyList<ChunkSpan> Spans, string ContentSha256);
public readonly record struct LineRange(int Start, int End);

/// Tells the harness (and the store) that sources changed. Chunk identity is content, so this is an optimisation:
/// without it, stale chunks simply miss.
public interface IInvalidationSignal
{
    IAsyncEnumerable<ChunkInvalidation> ReadAllAsync(CancellationToken ct);
}
public sealed record ChunkInvalidation(string Path, InvalidationKind Kind, string? NewContentSha256, string Origin);
public enum InvalidationKind { Modified, Deleted, Renamed, Unknown }   // Origin: "edit-tool", "fs-watch", "git", ...

/// Decides the request-level policy from what the harness knows.
public interface IRecomputePolicy
{
    ChunkRequestOptions Decide(ChunkRequestContext context);
}
public sealed record ChunkRequestContext(
    string ModelId, int PromptTokensEstimate, int ChunkTokens, bool HasQuerySegment,
    ChunkCacheCapabilities? ServerCapabilities, bool IsSubAgent, bool AfterCompaction);
public sealed record ChunkRequestOptions(
    string Policy = "auto", string Selector = "auto", double? Budget = null,
    string OnMiss = "prefill", bool Strict = false, string Report = "summary");

/// Annotations collected for one outgoing request; read by the body handler.
public sealed class ChunkManifest
{
    public List<(int Message, int Part, ChunkSpan Span)> Entries { get; } = new();
    public ChunkRequestOptions Options { get; set; } = new();
}

/// Control plane (HTTP to the server's /v1/chunk-cache endpoints, or the CLI's library).
public interface IChunkCacheClient
{
    ValueTask<ChunkCacheCapabilities?> GetCapabilitiesAsync(CancellationToken ct);   // null = convention absent
    ValueTask<SelectResult> SelectAsync(SelectRequest request, CancellationToken ct);
    ValueTask<PrewarmResult> PrewarmAsync(PrewarmRequest request, CancellationToken ct);
    ValueTask<StatusResult> StatusAsync(StatusRequest request, CancellationToken ct);
    ValueTask<EvictResult> EvictAsync(EvictRequest request, CancellationToken ct);
    ValueTask<ExplainResult> ExplainAsync(JsonObject requestBody, CancellationToken ct);
}
```

### 8.3 Pipeline pieces

```csharp
/// MEAI decorator. Finds chunk-bearing text in outgoing messages, builds the ChunkManifest, publishes it to the
/// handler through an AsyncLocal scope, and lifts the response's chunk_cache into ChatResponse.AdditionalProperties.
public sealed class ChunkAnnotatingChatClient : DelegatingChatClient
{
    public ChunkAnnotatingChatClient(IChatClient inner, IChunkSpanRegistry registry, IRecomputePolicy policy,
                                     IChunkCacheClient control) : base(inner) { }

    public override async Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages,
        ChatOptions? options = null, CancellationToken ct = default)
    {
        var list = messages as IList<ChatMessage> ?? messages.ToList();
        using var scope = ChunkManifestScope.Begin(BuildManifest(list));   // AsyncLocal<ChunkManifest?>
        var response = await base.GetResponseAsync(list, options, ct);
        ChunkCacheReport.Attach(response, scope.ResponseReport);           // AdditionalProperties["chunk_cache"]
        return response;
    }
    // GetStreamingResponseAsync: same; the report arrives with the final update.
}

/// Text → spans for content the decorator cannot see the origin of (tool results). Keyed by content SHA-256 of the
/// whole part: the file-read tool registers what it returned; the decorator looks the part up by hash.
public interface IChunkSpanRegistry
{
    void Register(string partText, IReadOnlyList<ChunkSpan> spans);
    bool TryGet(string partText, out IReadOnlyList<ChunkSpan> spans);
}

/// HTTP body handler on the provider's HttpClient (OpenAI Chat Completions JSON). Writes "chunk_cache" with
/// placement B (message/part indices), after verifying each span's text hash against the serialised body, so a
/// later mutator that changed the text produces no annotation rather than a wrong one. Strips nothing on
/// providers without the capability: it is only installed on chunk-capable providers.
public sealed class ChunkCacheBodyHandler : DelegatingHandler
{
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
    {
        // 1. read JSON body; 2. map ChunkManifest entries to (message, part) of the *serialised* messages by
        //    re-hashing the part texts (indices in MEAI and on the wire can differ); 3. add "chunk_cache";
        // 4. send; 5. parse "chunk_cache" from the response (or the final SSE chunk) into the scope.
        return await base.SendAsync(request, ct);
    }
}
```

- **Mapping by hash, not by index.** MEAI's message list and the serialised `messages` array differ: system extraction,
  tool-call messages, and string vs parts content. The handler therefore locates each registered part by re-hashing the
  serialised part texts. A string `content` is addressed as part 0.
- **Mutators run before the handler.** In CodeSharp's stack the tool-output guard, memory dedupe and hook rewrites run in
  the engine and session layers, above the provider's `HttpClient` **[reported]**. Because spans are verified against the
  final body, a mutated result degrades to plain text instead of a wrong annotation.
- **Capability probe.** At provider construction, `GetCapabilitiesAsync` is called once (and again after a model reload,
  which CodeSharp already detects from `/v1/status`). Without the capability the handler is not installed.

### 8.4 Transports

| transport | when | notes |
|---|---|---|
| **HTTP, OpenAI Chat Completions + `chunk_cache`** (reference) | any harness, any licence | the convention above; CodeSharp's wire |
| HTTP, Anthropic Messages + `chunk_cache` | harnesses on the Anthropic wire to dotLLM (Claude Code via `ANTHROPIC_BASE_URL`) | the same fields. CodeSharp chose not to use this wire for dotLLM **[verified, `decisions.md`]** |
| in-process (`DotLLM.Engine` + `DotLLM.ChunkReuse` linked) | GPL-compatible hosts only | **not for CodeSharp: ADR-011 forbids linking GPL code into the core** **[verified]**. Offered as an `IChatClient` over the engine with `StoredContextAssembler.ForModel(config, modelId, quant, tokenizerId)` and `GgufIdentity` ids **[verified API]**. Gated on an ADR decision in any host that has one |

## 9. Adapter matrix

| framework | where annotations go in | what it can do | what it cannot | effort |
|---|---|---|---|---|
| **Microsoft Agent Framework (.NET)** | `ChunkAnnotatingChatClient` in the chat-client pipeline (`ChatClientBuilder.Use`) + `ChunkCacheBodyHandler` on the provider `HttpClient`. `AIContextProvider` to inject selected chunks as messages; MEAI `IChatReducer` for chunk-aware compaction **[assumption on MAF type names; CodeSharp uses context providers and reducers, verified by file names]** | full convention, sub-agent reuse, telemetry | rely on `AdditionalProperties` reaching the wire | M (reference; CodeSharp) |
| **Semantic Kernel (.NET)** | SK chat services bridge to `IChatClient`, so the same decorator + handler apply. `IPromptRenderFilter` or `IFunctionInvocationFilter` to register file-read outputs **[assumption on names]** | full convention through the bridge | `PromptExecutionSettings.ExtensionData` reaching the wire is unconfirmed | S–M (reuses the .NET package) |
| **LangChain / LangGraph (Python)** | `ChatOpenAI(extra_body={"chunk_cache": {...}})` for placement B; a v1 agent middleware (`wrap_model_call`) builds the manifest per call **[assumption on names]** | full convention via B; `SummarizationMiddleware` can be replaced by a chunk-preserving one | per-part inline fields depend on the provider adapter | M (new Python package; deferred) |
| **Claude Code** | MCP server for the control plane; `ANTHROPIC_BASE_URL` → dotLLM `/v1/messages` with server transparent mode **[assumption on env var; documented for LLM gateways]** | store management, `select` returning chunk text; block-hash reuse of repeated tool results when a local model serves it | annotate its own requests; reuse with Anthropic-hosted models; hooks cannot edit the API request **[assumption]**; its Read tool numbers lines absolutely (§5.4), so prewarm cannot match | S (MCP) / L (to make reuse useful) |
| **Generic OpenAI-compatible client** | `chunk_cache` top-level via `extra_body` or a raw body | full convention | inline fields where the SDK has no raw content parts | S |
| **llama.cpp / vLLM / LMCache servers (as targets)** | none | requests degrade to plain text. For alignment: llama.cpp `cache_prompt` and `--cache-reuse` (KV shifting of matching chunks; [README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) **[verified]**); vLLM APC hashes blocks with a parent hash, tokens and extra keys, and partitions by `cache_salt` ([design doc](https://docs.vllm.ai/en/latest/design/prefix_caching.html) **[verified]**); LMCache CacheBlend uses an in-band separator (§6) | a shared convention: none of them offers per-block, position-independent annotations | n/a |

**Naming alignment.**
- The per-block marker follows Anthropic's `cache_control`-on-a-block placement, but uses its own key (`chunk`), because
  `cache_control` means exact prefix breakpoints and dotLLM may honour that meaning one day.
- `namespace` mirrors vLLM's `cache_salt`.
- Counters follow `cache_read_input_tokens` / `cache_n` style but with distinct names (`chunk_reused`, `chunk_n`), so they
  are never confused with exact reuse.
- `budget` is the fraction LMCache calls `blend_recompute_ratios` (default 0.15 there, which matches our `balanced`
  default for fixed chunks).

## 10. Security and privacy

- **The store is the source code.** Each `.ckv` file stores the chunk's **token ids** beside the K/V
  (`experiments/store/README.md`) **[verified]**, so detokenising recovers the text. The index JSON holds paths, line
  ranges and hashes. Treat the store root like the repository:
  - same ACLs;
  - outside synced or shared folders;
  - in `.gitignore`;
  - excluded from crash dumps and telemetry uploads.
  - Even without the token ids, KV is derived data from which text can plausibly be reconstructed **[assumption]**.
- **Cross-client side channel.** A shared server reveals through TTFT and `chunk_cache` counts whether some text was seen
  before. Prompt-caching timing attacks are a known class, which is why vLLM salts its cache ([design
  doc](https://docs.vllm.ai/en/latest/design/prefix_caching.html) **[verified]**). Rules:
  - single-user local servers only in v1;
  - `namespace` (salted into `ChunkKey`) before any multi-user use;
  - `per_chunk` reports limited to the requesting client's own spans.
- **Poisoning.** The KV for a chunk is always computed by the server from text it received and re-hashed (§5.3). Model
  identity is content-based (`GgufIdentity`; `--strict-model-id` for the full-file hash) **[verified]**. A wrong model
  cannot write under another model's keys through the assembler (`ForModel`).
  - **Residual risk:** the sampled model id misses interior-only tensor edits (documented). A shared store therefore
    wants the full hash.
- **No server-side file reads in v1.** `source.path` is telemetry. If a later version reads files by reference, it must
  use the `ChunkIndex.NormalizePath` rules (reject rooted paths and `..`, case rules) and an allow-listed root
  **[verified rules]**.
- **Hash leakage.** Hashes of short, low-entropy chunks can be confirmed by guessing. That is why there is a 32-token
  minimum, and why hashes are not logged at Information level by the server.
- **MCP tools** follow the MCP security guidance ([spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)):
  - `evict` defaults to `dry_run`;
  - `compare` and `prewarm` with `priority: "now"` state their GPU cost;
  - `build` only reads under the given path;
  - git refs go through the existing `GitCliInfo` validation (no shell; leading `-` rejected) **[verified]**.

## 11. Harness integration checklist

For harness authors. Each item names the failure it prevents.

1. **Probe capabilities** (`GET /v1/chunk-cache`) and install the annotating path only on a chunk-capable dotLLM.
   Otherwise strip everything. *Prevents 400s from hosted APIs.*
2. **Mark file reads.** Read files through an `IChunkSource` that uses the store's chunker and the `plain` render profile.
   Return one tool result with glue headers plus chunk spans, and register the spans by part text (`IChunkSpanRegistry`).
   *Without spans there is no reuse; with absolute line numbers in the chunk text there is little.*
3. **Stable order.** Keep the system prompt and tools byte-stable, put chunks in document order, volatile chunks after
   stable ones, and the query last (§5.6). *Prevents prefix misses and weak query-relevance selection.*
4. **Do not mutate chunk text after registration.** Truncation, dedupe and hook rewriting of a chunk-bearing result must
   either keep chunk spans whole or drop the annotation. The body handler's re-hash catches violations, but they cost
   reuse.
5. **Invalidation.** Content identity makes this an optimisation, not a correctness need: an edited chunk misses.
   - Emit `IInvalidationSignal` events from edit tools so the harness can re-read (and prewarm) changed chunks before the
     next turn.
   - External edits (user, git) need no watcher for correctness. The next read hashes the new text, and the server
     misses on it.
   - Optionally run `chunkcache status` on session resume to prewarm stale chunks.
6. **Compaction that keeps chunks.** Never flatten chunk-bearing parts into a summary. Keep them as parts (or drop them
   whole), summarise only the conversation around them, and re-emit kept chunks after the summary in stable order.
   *Prefix caches die on compaction; chunks survive only if the text survives byte for byte.*
7. **Sub-agents.** Pass the parent's selected chunk ids/hashes (not the conversation) to the sub-agent, and have it read
   files through the same `IChunkSource`. On a single-slot server, the sub-agent still evicts the parent's prefix
   snapshot, but the parent's chunks hit on resume.
8. **Session persistence.** Persist, per session, the ordered list of `(id, hash, path, range, render, chunker)` the
   conversation contains, so a resumed session can prewarm and `explain` misses. MEAI/MAF serialisation of
   `AdditionalProperties` is unverified, so keep this list in the harness's own state.
9. **Policy.** Start with `shadow` on real sessions to measure hit rates, and use `auto` thereafter. Expose `exact` as
   the user's "no approximation" switch.
10. **Telemetry.** Log `chunk_cache` per call:
    - policy applied and reason;
    - hit / miss / prefix counts;
    - reused and recomputed tokens;
    - TTFT and `full_prefill_estimate`.

    Keep exact-prefix monitoring (`cached_tokens`) separate.
11. **Prewarm when idle**, never as a side call that evicts a single-slot session snapshot.

## 12. Reference integration: CodeSharp

CodeSharp (`C:\Development\CodeSharp`, .NET 10, Microsoft Agent Framework, session codesharp-d1) is the reference. Facts
below are from codesharp-d1's answers **[reported]** unless I re-read the file **[verified]**.

### 12.1 Fit with CodeSharp's design

- **Provider seam.** `ChatClientFactory` (`IChatClientFactory`) builds the provider stack. dotLLM goes through
  `BuildOpenAiCompatibleClient` with `DotLlmMaxTokensHandler` and a `GET /v1/status` probe (`ChatClientFactory.cs`
  ~420–461) **[reported]**. The chunk path is:
  - a new provider-stack option on the dotLLM case, which installs `ChunkCacheBodyHandler` next to `DotLlmMaxTokensHandler`;
  - `ChunkAnnotatingChatClient` placed above `UniqueToolCallId` and below `RetryingChatClient` (retries resend the same
    manifest). This placement is **[assumption]**.
- **Prefix-cache policy.** CodeSharp has
  `PrefixCacheLevel { None, PrefixCached, SingleSlot }` and `IPrefixCachePolicy.LevelFor(modelId)` /
  `SideCallEvictsSession(...)` in `src/CodeSharp.Core/PrefixCache/` **[verified]**. The answers placed it under
  `CodeSharp.Models`; the files are in `CodeSharp.Core`.
- **Proposal: add a capability, not a fourth level.** The existing levels describe the *prefix* slot model, and a
  chunk-capable server is still single-slot or multi-slot. So add `bool ChunkReuse` (or a `[Flags]` capability set) next
  to the level. `RegistryPrefixCachePolicy` sets it from the `/v1/chunk-cache` probe. If CodeSharp prefers one enum, the
  value would be `ChunkReuse` meaning "prefix-cached plus chunks", with single-slot kept as a separate flag. Their call
  (open question 1).
- **Rule relaxations when `ChunkReuse` is set.** CodeSharp's prefix-alignment spec rules **[verified, its §A/§B]**:

  | rule | today | with chunk reuse |
  |---|---|---|
  | A4 no piecemeal spill on dotLLM | skip "spill older results one at a time"; one compaction instead | spilling a **non-chunk** result is still a prefix break; spilling a chunk-bearing result whole and re-reading it later is cheap (its chunks hit). Keep A4 for non-chunk results, relax it for chunk-bearing ones |
  | B1 sub-agents foreground on single slot | the main conversation re-reads everything on resume | the re-read hits chunks. Only glue, conversation and query are prefilled. Keep the notice, but its cost estimate drops |
  | B3 append-only history (`MemoryIndexDedupe` never removes) | strict | unchanged for non-chunk content; a memory index could itself be a chunk (stable text) |
  | B4 prefix-stability notices | prints the cost | report the chunk-adjusted cost (`explain`) |
  | B5 compact once, sized to the window | a full prefix miss by design | the miss is limited to non-chunk text if the planner keeps chunks (§12.3) |
  | B9 cache-miss monitoring | compares `cached_tokens` | unchanged (exact only); add a separate chunk hit-rate line from `chunk_cache` |

- **Prefix-breakers listed by codesharp-d1** **[reported]** and their chunk-mode treatment:
  - `MemoryIndexDedupe` mid-history edits: B3 already fixes this for dotLLM.
  - `ToolOutputGuard` in-place replacement of oversized results: a chunk-aware guard truncates at chunk-span boundaries
    and drops annotations of cut spans.
  - Hook output appended to tool results: append as a separate part, so chunk spans stay intact.
  - `UniqueToolCallId` rewriting colliding ids: harmless to chunks (ids are not hashed).
  - SessionStart context injected once then cleared: a prefix break; chunks unaffected.
  - Compaction rewriting the middle: §12.3.
- **Invalidation.** CodeSharp's `src/CodeSharp.Core/Hooks/` (`PostToolUseHookFunction` wraps every tool; `HookContext`
  has the tool name and result) **[reported]** is the edit-tool signal: an `IInvalidationSignal` fed by PostToolUse on
  edit/write tools. External edits have no signal today, and none is required: content hashing makes the next read miss
  correctly. Optional: `chunkcache status` on session resume, prewarming the stale chunks.

### 12.2 File reads

The spike needs CodeSharp's read-file tool to return `plain`-rendered text with glue headers, chunked by the store's
chunker (symbol-512 for C#, fixed-512 for other files), and to register spans. Whether its current output numbers lines is
open question 3. If it does, the spike uses `numbered-relative` for chunk text, or a separate chunk-aware read tool.

### 12.3 Chunk-aware compaction planner

`SessionCompactor.Plan(state, keepFirstTurns, keepLastTurns)` keeps the head and tail verbatim and flattens the middle
(`CompactionFlattener`), so per-block metadata survives only in the head and tail **[reported]**. Chunk-aware variant:
1. **Collect** every chunk-bearing part in the middle, with its spans (from the session's persisted chunk list, §11.8).
2. **Choose** which chunks to keep: those referenced by the tail turns or still in the current selection, the newest read
   of each path (an older read of an edited file is superseded), within a token budget (B5 target 45 % of the window),
   ranked by `ContextSelector` priorities if a graph exists.
3. **Summarise** the middle conversation text **without** the kept chunks (the summary may name them).
4. **Emit:** head turns, then a summary message, then one synthetic user or tool message holding the kept chunks in
   document order with glue headers (byte-identical chunk text), then the tail turns.
5. **Persist** the new chunk list. The next request: prefix hit through the head, chunk hits for the kept chunks, prefill
   for the summary and tail.

`WorkerCompactionReducer` (per-call worker compaction) gets the same rule: never flatten a chunk-bearing part.

### 12.4 Spike scope

- **In:**
  - capability probe;
  - `ChunkCacheBodyHandler` + `ChunkAnnotatingChatClient` on the dotLLM provider;
  - chunk-aware read-file output;
  - PostToolUse invalidation feed;
  - `chunk_cache` telemetry to logs and a TUI status line;
  - `shadow` and `auto` policies;
  - the compaction planner behind a setting;
  - sub-agent chunk hand-off.
- **Out:**
  - in-process hosting (ADR-011);
  - transparent mode;
  - Python adapters;
  - recurrent models.
- **Server side** (dotLLM, coordinated with the dotLLM session; nothing pushed without the user):
  - the `chunk_cache` parser;
  - assembly after the prefix match;
  - `shadow` / `exact` / `auto`;
  - `/v1/chunk-cache` with prewarm and explain;
  - background encode.

  The `balanced` path uses the existing `SelectiveRecomputer`.

### 12.5 Success metrics

Measured on a replayed corpus of real CodeSharp sessions (recorded requests, so runs are comparable). Each metric with
3 seeds or session sets and bootstrap intervals, per the repo's rules.

| metric | definition | target (initial) |
|---|---|---|
| chunk hit rate | `chunk_reused` / annotated chunk tokens, after compaction, sub-agent and resume events | ≥ 0.8 on resumed sessions and after compaction (assumption: these events dominate the loss of prefix reuse) |
| TTFT ratio | full-prefill TTFT / chunk TTFT on the same request, Vulkan, Qwen3-4B | `shadow` predicted vs measured within 20 %; real wins expected only after #1540 |
| accuracy delta | task success (scripted CodeSharp tasks with an executable or exact-match check) under `balanced` vs `exact` | ≥ 95 % of `exact` at ≤ 20 % recompute (the project's quality bar) |
| logit-level delta | KL / top-1 of the first 32 generated positions, `balanced` vs `exact`, on recorded requests | report; no target |
| plumbing loss | annotations dropped by the re-hash check / registered spans | < 5 %; every drop attributed to a mutator |
| overhead | handler + decorator time per request; store bytes per session | < 5 ms; report bytes |

### 12.6 Test plan

- **Unit (CodeSharp):**
  - the handler writes a manifest matching registered spans;
  - a mutated part is dropped;
  - string vs parts content;
  - streaming report parsing;
  - capability absent → body byte-identical to today;
  - the compaction planner keeps chunk bytes identical;
  - mutation evidence, as in this repo.
- **Contract (dotLLM):**
  - unknown fields still ignored;
  - `strict` errors with the §5.8 codes;
  - hash mismatch → plain text;
  - `exact` and `shadow` outputs bit-identical to a request without `chunk_cache`;
  - `cached_tokens` unchanged in meaning.
- **Integration (local Vulkan iGPU, under the GPU lock; any T5500 use needs the user's approval):**
  - replay N recorded sessions under `exact`, `shadow` and `balanced`;
  - compare hit rates, TTFT and task success;
  - include a compaction, a sub-agent, a server restart and an external edit in each replay.
- **Regression:** CodeSharp's provider-conformance suite passes with the chunk path installed and the capability absent.

### 12.7 Open questions for codesharp-d1

1. Capability flag next to `PrefixCacheLevel`, or a new enum value `ChunkReuse` (§12.1)? Who owns
   `RegistryPrefixCachePolicy`'s probe?
2. Is the HTTP-body handler acceptable on the dotLLM OpenAI-compatible provider, next to `DotLlmMaxTokensHandler`? And at
   which stack position should `ChunkAnnotatingChatClient` sit relative to `RetryingChatClient` and `UniqueToolCallId`?
3. What does the read-file tool output look like (line numbers? headers? truncation)? Can it return multiple text parts
   per result, or is the result one string?
4. Does `ToolOutputGuardChatClient`'s in-place replacement have access to the original part, so it can cut at span
   boundaries?
5. Does MAF's session JSON round-trip `AdditionalProperties` on `TextContent` / `FunctionResultContent`? If not, where
   should the per-session chunk list live (the session blob vs a sidecar)?
6. How do sub-agents receive history today (`ISubAgentSessionStore`, `SubAgentBootstrap`)? Is passing a chunk list into
   the sub-agent's first message acceptable?
7. Can the compaction planner (§12.3) replace `CompactionFlattener` behind a setting, and does B5's 45 % target count kept
   chunks?
8. Which models does CodeSharp run on dotLLM in practice? v1 supports attention-only models, so a hybrid or recurrent
   default (Qwen3.8 / Flash-Next) means the spike has to pin Qwen3-4B or Llama-3.1-8B.
9. Is there a recorded-session corpus to replay (privacy: it contains source), and a scripted task set with checkable
   outcomes?
10. Should `chunk_cache` telemetry flow into the existing OpenTelemetry spans (`UsageSpanTagging`), and under which
    attribute names?

## 13. Phased delivery

| phase | content | depends on | outward-facing? |
|---|---|---|---|
| I0 | this spec; answers to §12.7 | codesharp-d1 | no |
| I1 | dotLLM server: `chunk_cache` parsing (both placements), hash check, `exact` / `shadow`, `/v1/chunk-cache` (capabilities, prewarm, explain), background encode, response metadata, contract tests | Phase S Tasks 2–4 (done), the dotLLM session's agreement on the server surface | dotLLM PR only with the user's approval (issue first, target `dev`) |
| I2 | `DotLLM.ChunkCache.Client` (.NET): records, `ChunkAnnotatingChatClient`, `ChunkCacheBodyHandler`, `IChunkSource` over `SymbolChunker` / fixed, registry, policy | I1 contract | NuGet with the dotLLM release path (Phase S Task 9); licence of the client package to be decided (permissive, so CodeSharp can reference it under ADR-011) |
| I3 | `chunkcache` CLI (Phase S Task 7) + MCP server wrapping it (§7.2) | Phase S Task 7 | tool package |
| I4 | CodeSharp spike in `shadow`: hit rates on replayed sessions, the compaction planner, sub-agent hand-off | I1–I2, codesharp-d1 | CodeSharp branch, their review |
| I5 | `balanced` / `auto` with a real cost model; accuracy A/B; TTFT measurements | **dotLLM #1540** (ATTN_QPOS speed), Vulkan query probe | report to the user |
| I6 | compact rows F16 / Q8_0, direct-to-device loading, cold-disk TTFT (the "phase D" user direction) | dotLLM Vulkan owner | — |
| I7 | transparent block-hash mode (server flag), the Claude Code recipe (MCP + `ANTHROPIC_BASE_URL`) | I1 | docs |

**Deferred:**
- PRs or packages for Semantic Kernel, LangChain and Claude Code **[user]**;
- `contextual` positioning;
- chunks by reference without text;
- multi-tenant namespaces;
- recurrent and hybrid models (Phase T);
- LRU eviction bookkeeping;
- the edit-local repair quality half of E7.

## 14. Sources

Local (verified):
- `REPORT.md`
- `experiments/{E4-structure-aware,G2-recompute-speed,store,E7-incremental,selection-tools,solution-scan}/README.md`
- `.superpowers/sdd/2026-11-01-phase-s/task-3-report.md`, `task-4-report.md`, `codesharp-answers.md`
- `dotLLM/docs/SERVER.md`, `dotLLM/docs/ANTHROPIC_API.md`
- CodeSharp `docs/architecture/decisions.md` (ADR-011), `docs/superpowers/specs/2026-10-22-dotllm-prefix-cache-alignment-design.md`,
  `src/CodeSharp.Core/PrefixCache/*.cs`, `src/CodeSharp.Models/AnthropicPromptCacheHandler.cs`

Web (fetched 2026-11-02):
- Anthropic prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- MCP 2025-06-18 tools: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MEAI `ChatOptions.RawRepresentationFactory`: https://learn.microsoft.com/en-us/dotnet/api/microsoft.extensions.ai.chatoptions.rawrepresentationfactory
- LMCache configuration (blending keys): https://docs.lmcache.ai/api_reference/configurations.html
- llama.cpp server README: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- vLLM prefix caching design: https://docs.vllm.ai/en/latest/design/prefix_caching.html
- openai-dotnet JsonPatch (search result only): https://github.com/openai/openai-dotnet/pull/834.diff; Semantic Kernel use:
  https://github.com/microsoft/semantic-kernel/pull/13934

Not fetched (recollection, marked **[assumption]** where used): OpenAI prompt caching
(https://platform.openai.com/docs/guides/prompt-caching), Gemini context caching (https://ai.google.dev/gemini-api/docs/caching),
Microsoft Agent Framework docs (https://learn.microsoft.com/agent-framework/), Semantic Kernel filters, LangChain v1
middleware (https://docs.langchain.com/oss/python/langchain/middleware), Claude Code hooks / LLM gateway docs.
