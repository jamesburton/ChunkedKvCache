# Chunk-level KV reuse: integration spec for agent harnesses

Status: draft, **revision 2** (2026-11-02), after the review in
`.superpowers/sdd/2026-11-01-phase-s/integration-spec-review.md` (blocking items B1–B4 addressed in §5.3, §5.5, §5.6,
§5.11 and §14). Companion to `2026-10-31-chunk-kv-reuse-design.md` and the Phase S plan
(`docs/superpowers/plans/2026-11-01-phase-s-store-cli-e4b.md`).

The user agreed to the overall shape **[user]**:
- a runtime wire convention in the dotLLM server;
- a library, a `chunkcache` CLI and a thin MCP control plane;
- harness integration with CodeSharp as the reference.

Everything else is the author's proposal.

Evidence labels:
- **[verified]**: read in this repo, in dotLLM or CodeSharp source or docs, or on a cited page on 2026-11-02.
- **[reported]**: from codesharp-d1's answers (`.superpowers/sdd/2026-11-01-phase-s/codesharp-answers.md`) or the
  reviewer, not re-traced by me.
- **[assumption]**: my inference; check it before building on it.

## 1. Goals, non-goals

**Goals**
1. A harness that talks to a local dotLLM server over HTTP can mark parts of its prompt as **reusable chunks**. The
   server can then assemble them from its persistent store, recompute a selected share of tokens and generate **[user]**.
2. **Graceful degradation, and no silent approximation.**
   - An annotated request is a valid plain request.
   - The default policy gives output identical to the same request without annotations.
   - Approximate reuse happens only when the caller asks for it (§5.5).
3. **Identity is exact text.** Ids, paths and line ranges are labels.
   - Lookup always goes: text → the server's tokenisation → `ChunkKey`. The key covers the model fingerprint, tokenizer,
     RoPE, schema version, backend, dtype, positioning and token ids (`experiments/store/README.md`) **[verified]**.
   - A stale chunk therefore misses; it never hits wrongly.
4. A control plane (library, CLI, MCP) to build, prewarm, select, inspect and evict.
5. Harness guidance that keeps reuse high across the events that destroy an exact prefix: compaction, sub-agents,
   resumed sessions, re-ranked selections, edits.
6. Honest telemetry.
   - Every response reports reuse as counts.
   - Exact and approximate reuse are never mixed in one counter.

**Non-goals (v1)**
- **Hosted providers.**
  - Anthropic, OpenAI and Gemini offer exact-prefix caching only
    ([Anthropic](https://platform.claude.com/docs/en/build-with-claude/prompt-caching); OpenAI and Gemini docs not fetched).
  - They reject unknown request fields, so annotations must be stripped before reaching them (§5.7).
- **Recurrent and hybrid models** (Gated DeltaNet, Mamba; e.g. `qwen4exp`): Phase T. v1 supports attention-only models
  only (Qwen3-4B, Llama-3.1-8B class).
- **Deferred** (fields are reserved, semantics deferred):
  - `contextual` positioning;
  - chunks by reference without their text;
  - the `hybrid` (graph) selector;
  - the `numbered-relative` render profile;
  - multi-tenant stores.
- **PRs and packages for other harnesses** (Semantic Kernel, LangChain, Claude Code) **[user]**.

## 2. Honest limits

1. **Needs a local runtime that owns the KV.** Only dotLLM implements reuse. MCP servers, proxies and client libraries
   cannot make a hosted model reuse KV (§7.1).
2. **Naive reuse loses accuracy.** Naive concatenation's KL against full prefill is 0.13 / 0.17 / 0.55 / 0.67 nats at
   2K / 4K / 8K / 16K (E1). On the 2K masked-call tasks it gets exact match on 5 of 28, against 28 of 28 for full prefill
   (G2) **[verified]**.
3. **Recompute repairs much of the gap, but meets the quality bar in one configuration only** (E4, `REPORT.md`)
   **[verified]**:
   - **Recovered share of the naive→full gap at 5–20 %:** chunk starts 0.65–0.82, query relevance (QR) 0.70–0.83 with
     symbol chunks; QR 0.87–0.97 with fixed 512-token chunks.
   - **The 95 % / 20 % bar** (≥ 95 % of full-prefill exact match at ≤ 20 % recompute):
     - holds as a point estimate **only** for fixed chunks with QR or Hybrid (EM 1.00; 0.96 in E4b);
     - fixed chunk starts reach EM 0.91;
     - symbol chunks reach 0.81 (E4) and at best 0.93 (E4b).
   - One model; small, clustered samples.
   - **E4's fixed chunks were token-id slices, which are not guaranteed to round-trip on the wire** (§5.3, item 4). The
     quality of wire-eligible `lines-512` chunks is not yet validated (§5.11).
4. **Recompute is currently slower than full prefill.** G2 measured Vulkan with Qwen3-4B **[verified, G2 README as revised]**.

   | ctx | naive assembly vs full prefill | with recompute (reuse TTFT vs full prefill) |
   |---|---|---|
   | 2K | 22× faster | tie at 5 % (1.07×); 0.56× at 10 %; 0.28× at 20 % |
   | 8K | 62× faster | tie at 5 % (0.96×); 0.20× at 20 % |
   | 16K | 107× faster | ~0.7–0.85× at 5 % (estimate; the measured 16K arms were an anomalous slow run) |

   - **The cause is one kernel.** The per-query-position attention (`ATTN_QPOS`, dotLLM #1534) makes the whole forward
     18–28× slower than ordinary prefill attention on the same rows. The kernel alone is 26–31× slower (GPU timestamps).
   - The cost is a flat **13–19 µs per (recomputed row × visible key)** from 2K to 16K, and 97–99.6 % of the forward is
     attention.
   - The earlier "78× / 65 µs at 16K" was an anomaly and is withdrawn.
   - **What a fast kernel would give:** with a kernel as fast as the ordinary one, 20 % at 2K would be about 2.8× faster
     than full prefill, and 5 % at 16K about 5.7× (G2 control arm).
   - The pending kernel work is **dotLLM #1540** **[user; not referenced in this repo]**.
5. **Selectors are not production-ready on the GPU.** The QR probe is a CPU lab implementation (16.5 s per request), with
   no Vulkan probe yet. Without it, the only runnable selector is chunk starts. Chunk starts are below the bar except on
   fixed chunks at 20 % (EM 0.91), and that cell is also below it.
6. **Storage is large.** F32 rows cost 288 KiB per token for Qwen3-4B, so:
   - a 1.5 M-token repository needs about 442 GB;
   - a 100K-token session's misses about 28 GB.

   F16 / Q8_0 rows (≈ 0.5× / 0.27×) are deferred to the persistent-caching phase **[verified]**.
7. **A miss costs more than prefill.** In G2 an isolated encode cost 3.4× the full prefill at 2K, including the slow
   readback. Reuse pays only from the second use of a chunk.
8. **The libraries are CPU-only today.**
   - `StoredContextAssembler` hard-codes backend `"cpu"`, writes F32 rows only, and needs an exact host F32 destination.
   - Vulkan assembly lives on another branch.
   - Assembling into the server's real paged, possibly quantised, multi-slot KV is **engine work** (§14) **[reported by
     review; consistent with the store README]**.

## 3. Where reuse helps an agent

dotLLM keeps prompt-prefix snapshots and reports `cached_tokens` / `cache_n` **[verified, `dotLLM/docs/SERVER.md`]**.
- Snapshots live in memory. A disk spill exists (`--prefix-snapshot-disk-dir`), but its files are not reused after a
  restart **[reported by review, `SERVER.md`]**.
- An append-only conversation on one slot is served well by snapshots. CodeSharp's prefix-cache alignment spec is built
  around keeping them alive.

Chunk reuse adds value where the exact prefix dies:

| event | prefix cache | chunk reuse |
|---|---|---|
| compaction rewrites the middle of the history | miss from the first changed message | chunks re-emitted byte-identical after the summary hit again |
| a sub-agent with another system prompt reads the same files | miss | hit |
| resumed session after a server restart or model reload | miss | hit (the store is on disk) |
| a selection re-ranked or re-ordered | miss after the first difference | hit (position-independent) |
| one file edited | everything after it is re-prefilled | only the edited chunk misses (E7: median 234 tokens re-encoded, symbol chunks) |
| a single-slot server evicted by a side call | full re-read | chunks hit; glue, conversation and query are prefilled |

How a request is served:
1. The server first matches the exact prefix.
2. When reuse is applied, it assembles annotated chunks after the prefix, recomputes, and prefills the rest.
3. The snapshot taken afterwards is **tagged approximate** (§5.5), and only requests that accept approximation may
   restore it.

## 4. Architecture

```
harness ── ChunkAnnotatingChatClient ── HTTP body handler ──►  dotLLM server (sole store writer)
   │          (records spans)          (adds chunk_cache)          ├─ exact prefix match (lineage-aware)
   └─ chunk source (text-first chunker, plain render)              ├─ chunk assembly from the store
                                                                   ├─ selective recompute (opt-in)
control plane: chunkcache CLI / MCP ── HTTP ──► /v1/chunk-cache/*  └─ background encode (budgeted)
   (index, select, status; encode and evict go through the server)        │
                                                             store root (.ckv + indexes + server ledger)
```

- **HTTP is the reference transport** (`CodeSharp/docs/architecture/decisions.md:202-228`) **[verified]**:
  - ADR-009 makes dotLLM an optional, process-isolated provider on the OpenAI wire. The Anthropic and Ollama wires are
    "deliberately not used".
  - ADR-011 supplies the licensing rationale: GPL components are integrated only across a process boundary.
- In-process hosting is an option only for GPL-compatible hosts (§8.4).
- **The server is the only writer of K/V entries** (§14, L1). The CLI builds indexes and selections from text and
  tokenizer only, and asks the server to encode (`prewarm`) or evict.

## 5. Wire convention (v1)

### 5.1 Two equivalent placements

**v1 surfaces (Task 9 pin, ruling 19).** On the OpenAI surface v1 annotates **string** `content` only, through the
manifest (B) with `part: 0` and byte ranges; array-of-parts content stays a 400 as today, so inline (A) is
**Anthropic-only in v1** (text blocks; part indices map through the Anthropic converter's `'
'` joins and `tool_result`
splitting). The example below shows the shape on an Anthropic `tool_result` / text block list.

**(A) Inline**, a `chunk` field on a text content part:

```json
{"role": "tool", "tool_call_id": "call_7", "content": [
  {"type": "text", "text": "// src/Store/ChunkIndex.cs (lines 365-412)\n"},
  {"type": "text", "text": "public IndexDiff Update(...)\n{ ... }\n",
   "chunk": {"v": 1, "id": "src/Store/ChunkIndex.cs:365-412@14211", "hash": "sha256:9f2c…", "chunker": "symbol-512"}}
]}
```

**(B) Top-level manifest**, a `chunk_cache` object in the request body:

```json
{"model": "qwen3-4b", "messages": [...],
 "chunk_cache": {"v": 1, "policy": "shadow",
   "chunks": [{"id": "src/Store/ChunkIndex.cs:365-412@14211", "hash": "sha256:9f2c…", "at": {"message": 3, "part": 1}},
              {"id": "src/Store/ChunkRef.cs:1-40@0", "hash": "sha256:41ab…",
               "at": {"message": 3, "part": 2, "start": 0, "end": 1830}}]}}
```

- **Why both.**
  - Many client stacks cannot add a field to one content part.
  - CodeSharp found that the MEAI **Anthropic** bridge exposes no per-block `cache_control`, and that
    `ChatOptions.AdditionalProperties` (`reasoning_effort`) was silently dropped on the wire (`AnthropicPromptCacheHandler.cs`
    remarks) **[verified]**.
  - Whether the MEAI OpenAI bridge forwards per-content `AdditionalProperties` is **[assumption: no]**.
  - A top-level field can be added through `extra_body` or a body-rewriting handler. B is the portable form; A is for
    hand-built bodies.
- **Why a field and not a new part type.** dotLLM's Anthropic surface rejects unknown content block types with a 400, and
  both surfaces ignore unknown fields (`ANTHROPIC_API.md:79,101,250`; `SERVER.md:61`) **[verified]**.
- **Both placements in one request:** warning `chunk_manifest_conflict`, and the request is served as if unannotated.
  It is an error only when the request is strict.

### 5.2 Fields

Per chunk: `chunk` (inline) or `chunk_cache.chunks[i]` (manifest).

| field | type | req | meaning |
|---|---|---|---|
| `v` | int | inline yes; manifest inherits `chunk_cache.v` | convention version, `1` |
| `hash` | string | yes | `sha256:` + lowercase hex of the UTF-8 bytes of the decoded chunk text (§5.3 item 1) |
| `id` | string ≤ 256 | yes | the caller's label (e.g. `ChunkRef.Id`, `path:startLine-endLine@offset`, whose offset is in **UTF-16 chars**). Telemetry only; never used for lookup |
| `at` | object | manifest only | `{message, part[, start, end]}`: indices into the **serialised** `messages` and its `content` array. A string `content` is part 0 (the only form on the OpenAI surface in v1). `start` / `end` are **UTF-8 byte** offsets into that part's text, end exclusive. Omitted means the whole part |
| `chunker` | string | no | a wire-eligible chunker name (§5.3, item 4). Lets the server pick budget defaults and lets `explain` match the index |
| `source` | object | no | `{path, start_line, end_line, rev}`: provenance for telemetry. Never read by the server |
| `positioning` | `"isolated"` | no | v1 accepts only `isolated`: encoded alone at positions 0..n-1 and RoPE-shifted on assembly (`ChunkPositioning.Isolated`, key scheme `chunk-key/v3`) **[verified]** |
| `stability` | `"stable"` \| `"volatile"` | no | hint: `volatile` chunks are not queued for background encode |
| `no_store` | bool | no | never persist this chunk's K/V or sighting (secrets; §10) |

Request level (`chunk_cache`):

| field | default | meaning |
|---|---|---|
| `v` | 1 | version |
| `policy` | **`exact`** | `exact` / `shadow` / `balanced` / `fast` / `auto` (§5.5) |
| `recompute` | server default | `{selector: "chunk_starts" \| "query_relevance", budget: 0.0–1.0, max_tokens}`. `hybrid` is reserved |
| `query` | last user message | `{message: i}` or `{text: "..."}`: what query-aware selection scores against (§5.6) |
| `on_miss` | `prefill` | `prefill`: a missing chunk is prefilled in place as ordinary text; its isolated encode may be queued under the admission rules (§5.10). `encode`: encode now, store, then assemble |
| `strict` | false | errors instead of degradation (§5.8) |
| `min_chunk_tokens` | 32 | shorter chunks are treated as plain text |
| `report` | `summary` | `none` / `summary` (counts). `per_chunk` only for an authenticated caller within its own namespace (§10) |
| `namespace` | per API key | the store partition, salted into `ChunkKey` (§10) |

Fields at their default values may be omitted, and the reference client omits them (`policy: exact`, `on_miss: prefill`, `report: summary`, `strict: false`, `recompute` with neither selector nor budget); a server must treat an omitted field exactly as its default.

### 5.3 Identity, hashing, tokenisation

1. **The hash covers the UTF-8 encoding of the decoded JSON string value**, with no normalisation. JSON escapes such as
   `\uXXXX`, which serialisers like `ToJsonString` emit for non-ASCII, are resolved first, so the wire bytes are not
   hashed. CRLF vs LF, BOM and trailing whitespace all count. The Roslyn scanner normalises to LF before chunking (`experiments/solution-scan/README.md`) **[verified]**, so a
   harness that sends CRLF text misses every prewarmed chunk (CodeSharp: §12.2).
2. **The server recomputes the hash.** On a mismatch the annotation is ignored and the span is plain text (warning
   `chunk_hash_mismatch`). The server always computes K/V itself from the received text, so a client cannot poison the
   store.
3. **`id` never takes part in lookup.** The same text under two ids is one entry; different texts under one id are two
   entries.
4. **Wire-eligible chunkers are text-first** (constraint; blocking item B1).
   - **The rule.** A chunker may be used on the wire, and for store entries the wire must hit, only if it **cuts the text
     first (at character or line boundaries) and then tokenises each piece alone**, with the same tokenisation the server
     uses for chunk text (item 6).
   - **The key.** The store key is over those per-piece ids, which equal what the server computes from the received text.
   - **`SymbolChunker` qualifies** (each chunk's text goes through `EncodeRaw` alone) **[verified]**, **except** the pieces
     of an over-long single line, which it cuts as token slices. `build` marks those pieces wire-ineligible.
   - **`FixedSizeChunker` (`fixed-512`) does not qualify.** It tokenises the whole file and slices the ids
     (`Corpus/FixedSizeChunker.cs:41`) **[verified]**. Its chunk text `Decode(slice)` is **not guaranteed to round-trip**
     to the slice: measured 2 / 3,972 failures (1 in 2,518 cuts), both at cuts inside a multi-byte UTF-8 character
     (E4c review); the rate depends on corpus and tokenizer. Pre-tokenisation can also split differently at a cut. The
     text-first-only rule stays: rare is not never.
   - **The wire chunker is `lines-512`:** accumulate whole lines up to 512 tokens (tokenising each candidate piece
     alone), and split an over-long line at a character boundary. It exists as `TextFirstFixedChunker` (`fixed-text-512`,
     used by E4c) and is renamed `lines-512` in Phase I (user decision, 2026-11-02).
   - **`build` asserts the round trip.** For every chunk it checks `EncodeRaw(MarkUntrustedSpecials(text)) == ids` (item 6)
     and flags or drops the rest.
   - **`lines-512` is wire-eligible** (E4c review: correctness, 0 / 3,996 round-trip failures). Its **quality is not
     validated**: E4's fixed-chunk numbers come from id-sliced chunks and do not transfer; validation is §5.11, in I5.
5. **Spans are located in the rendered prompt** (blocking item B3).
   - **How.** The server renders the chat template with each chunk span replaced by a unique placeholder, then checks that
     the rendered output contains the placeholder intact and that the text around it is what the template produced for
     the unannotated request. Implementation choice for dotLLM: sentinel rendering, or rendering twice and diffing.
   - **If the template altered the span's text, the span is ignored** (warning `chunk_template_altered`). The comparison
     uses the span text as the chat path marks it (U+FDD0 inserted into special-token spellings, #1339; `ControlTokenGuard`
     strips it at encode time), or strips U+FDD0 from both sides. Pinned in Task 9 **[verified]**:
     - Llama-3.1's template trims user / assistant / system content and JSON-encodes tool content, so on Llama-3.1
       tool-result spans are never reusable in v1, and spans at a part edge lose whitespace;
     - Qwen3 keeps content verbatim.
   - **Advice:** put chunk spans in the middle of a part, after a glue header, and end them with a newline the template
     does not trim.
6. **Special tokens.** Chunk text is tokenised exactly as the plain request path tokenises message content (Task 9
   pin, ruling 21) **[verified]**.
   - The chat path does not parse special-token strings in caller content: the template marks them with U+FDD0 and
     `ControlTokenGuard` strips the mark at encode time (not on decode). Bare `EncodeRaw` **does** parse them, so the chunkers were not equivalent.
   - So chunk text is tokenised as `EncodeRaw(MarkUntrustedSpecials(text))` by the store, the wire path, `build` and
     prewarm alike; a chunk containing `<think>` is plain text on both sides. `chunk_special_tokens` stays reserved.
   - Either way, a file cannot inject control tokens through the chunk path that it could not inject as plain content.
   - dotLLM's current behaviour for content is pinned in I1 **[assumption: unverified]**.
7. **Tokenisation by policy** (blocking item B2).
   - **`exact` and `shadow`:** the prompt is tokenised exactly as a plain request (whole rendered prompt), so their
     output equals the unannotated request.
   - **Applied reuse (`balanced`, `fast`, `auto` when it reuses):** segmented tokenisation. Glue and chunks are tokenised
     separately, and the token stream is their concatenation.
   - **The seam cost.** Segmented tokenisation can differ from whole-prompt tokenisation at the seams (+0.4 % tokens
     corpus-wide for symbol chunks, E7). An exact prefix match across a change of policy may stop at the first seam.
   - A/B comparisons report both tokenisations.
8. **Snapshot lineage** (blocking item B2).
   - **Tagging.** Every prefix snapshot is tagged `exact` or `approx`. A snapshot is `approx` from the first row whose K/V
     came from assembly or recompute; rows before that row are exact.
   - **Who may restore what.** A request under `exact` or `shadow`, or without annotations, restores only up to the first
     approximate row, then prefills. Requests that apply reuse may restore approximate rows.
   - **Counting.** `cached_tokens` / `cache_n` count exact rows only. Approximate rows restored from a snapshot are
     reported as `chunk_cache.tokens.prefix_reused_approx`.

### 5.4 Render profile

- v1 defines one profile, `plain`: the raw file text of the chunk, with any header (path, line range, "showing lines
  a–b") sent as **glue outside the span**.
- **Line numbers.** Absolute line numbers inside chunk text (`cat -n` style, as in Claude Code's Read output) defeat
  incremental reuse: an insertion near the top changes every later chunk of the file. A `numbered-relative` profile is
  reserved.
- **Windows and caps.** A harness that reads a window of a file (offset, limit, or a line cap) can annotate only the
  chunks wholly inside the window. Prefer chunk-aligned windows.

### 5.5 Policies (default `exact`; nothing lossy without an explicit opt-in)

| policy | behaviour |
|---|---|
| **`exact`** (default) | output identical to the unannotated request (§5.3, items 7–8). Annotations are used for counts and, under the admission rules, for background encode |
| `shadow` | as `exact`, plus the server computes the reuse plan without using it: hits, misses, predicted rows, predicted TTFT from the cost model. Use it to measure hit rates on real traffic |
| `balanced` | reuse with recompute. Selector: `query_relevance` if the probe exists on the backend, else `chunk_starts`. Budget 20 %. **Below the 95 / 20 bar** with `chunk_starts`, and with symbol chunks under any selector (§2.3); the response says which applied. The only configuration that met the bar (QR on id-sliced fixed chunks) needs `lines-512` validation (§5.11) and a GPU probe |
| `fast` | chunk starts at 5 %, or naive with `budget: 0`. Documented as lossy |
| `auto` | **opt-in only.** Reuse is applied when both gates pass; otherwise `exact` is applied, with a reason |

`auto`'s two gates:
- **Quality floor.** The (chunker kind × selector × budget) combination is in the server's validated table. A combination
  enters the table only after an E4-style measurement meets the bar on that model. Today the table is empty.
- **Cost model.** Predicted reuse TTFT is below full prefill. The prediction is the per (row × visible key) cost on the
  active backend (today 13–19 µs on Vulkan with ATTN_QPOS) plus assembly.

Other rules:
- **No default change after #1540.** The default stays `exact` even once #1540 lands; the harness opts in to
  `auto` / `balanced` per request or per session. #1540 changes only what `auto` can choose.
- **Prefix interplay.** Chunks inside an exact prefix match are reported as `prefix` (exact).
- **Unsupported model or backend.** On a recurrent or hybrid model, or a backend without assembly, every policy degrades
  to `exact` with the reason `chunk_model_unsupported`.

### 5.6 Query and ordering

- **The query is the last user message** (or `chunk_cache.query`), **wherever it sits.**
  - In an agent loop the task comes **before** the file reads: user → assistant tool call → tool results. "The text after
    the last chunk" is tool-call JSON or nothing.
  - So the server scores relevance **out of place**: it forwards the query tokens after the assembled context in a scratch
    pass that is rolled back. This is how the lab QR probe works **[verified, E2/E4 harness]**. It then selects the rows
    to recompute.
  - **Caveat:** E4 measured QR with the query after the context, in the prompt as well. Whether QR keeps its lead when the
    prompt's own query precedes the chunks is **unmeasured**. It is an extra arm of E4c (§5.11).
- **Ordering rules apply to harness-built context, not to the conversation.**
  - Conversation history stays chronological and append-only. Tool results land where they happened, and reordering past
    turns would break the exact prefix.
  - The rules apply when the harness itself composes a block of context: an initial selection, a compaction re-emit
    (§12.3), or a sub-agent hand-off:
    1. the system prompt and tool block stay byte-stable;
    2. chunks go in a deterministic order (`SelectionResult.InDocumentOrder()`: path, then offset **[verified]**), stable
       before volatile;
    3. one part per chunk, or manifest spans, with glue headers.

### 5.7 Fallback

| situation | behaviour |
|---|---|
| a server without the convention (older dotLLM, llama.cpp, Ollama) | unknown fields are ignored (dotLLM **[verified]**; llama.cpp observed behaviour **[reported]**). Plain text |
| hosted APIs | OpenAI 400s "Unrecognized request argument"; Anthropic 400s "Extra inputs are not permitted" **[reported by review; consistent with my recollection]**. The client must strip annotations unless the capability probe (§5.9) succeeded |
| a server that advertises the convention but refuses a non-strict manifest with a `chunk_*` error (non-conforming) | the reference client resends the request once without `chunk_cache` and treats the server as not capable for the probe failure period (30 s), so a server that keeps refusing costs one extra request per period. Strict requests get the error |
| hash mismatch, bad span, template-altered span, special tokens | that annotation is ignored; warning |
| store unavailable, busy or full | misses (store failures are misses, Task 3 **[verified]**); `chunk_store_unavailable` warning |
| unsupported model or backend | `exact`, with a reason |
| `strict: true` | the above become errors |

### 5.8 Errors and warnings

Envelopes as on the existing surfaces **[verified]**. All strict errors are **400 `invalid_request_error`** with a
`code`, except `chunk_store_unavailable` (503 `api_error`). dotLLM and Anthropic do not use 422.

- **Errors when strict, warnings otherwise:**
  - `chunk_version_unsupported`
  - `chunk_hash_mismatch`
  - `chunk_span_invalid` (`at` out of range, overlap, not on a UTF-8 boundary, a non-text part)
  - `chunk_manifest_conflict`
  - `chunk_template_altered`
  - `chunk_special_tokens`
  - `chunk_model_unsupported`
  - `chunk_policy_unavailable` (e.g. `query_relevance` with no probe on this backend)
  - `chunk_too_many`
  - `chunk_store_unavailable` (root missing, write budget exhausted, lock timeout)
- **Warnings only:**
  - `chunk_ignored_too_short`
  - `chunk_not_wire_eligible` (the `chunker` named is not text-first)
  - `chunk_encode_skipped` (admission refused, §5.10)
  - `chunk_encode_queued`

The `explain` endpoint (§7.2) uses the same codes and status mapping.

### 5.9 Response metadata, capabilities, versioning

The response carries a top-level `chunk_cache` object:
- in a blocking response;
- in the final streaming chunk next to `usage` and `timings`;
- on the Anthropic stream, in the `message_delta` event beside `usage`.

**Illustration**, after #1540 (with today's kernel the recompute below would take minutes, not 1.5 s):

```json
"chunk_cache": {
  "v": 1, "policy_requested": "auto", "policy_applied": "balanced", "reason": "gates_passed",
  "chunks": {"annotated": 14, "prefix": 3, "hit": 9, "miss": 1, "ignored": 1},
  "tokens": {"prompt": 18340, "prefix_reused": 2210, "prefix_reused_approx": 0,
             "chunk_reused": 13420, "chunk_recomputed": 2013, "prefilled": 2710, "encode_queued": 412},
  "recompute": {"selector": "query_relevance", "budget": 0.15, "rows": 2013, "forwards": 1, "attn_kernel": "qpos"},
  "timings_ms": {"assembly": 76, "probe": 12, "recompute": 1540, "prefill": 410, "full_prefill_estimate": 6100},
  "warnings": [{"code": "chunk_ignored_too_short", "count": 1}]
}
```

**How the token counts relate:**
- **The prompt partition:** `prompt = prefix_reused + prefix_reused_approx + chunk_reused + prefilled`. Here
  2,210 + 0 + 13,420 + 2,710 = 18,340.
- **Recompute is a subset of reuse:** `chunk_recomputed` ⊂ `chunk_reused`.
- **Missed chunks** (412 tokens, prefilled in place under `on_miss: prefill`) are counted in `prefilled`.
- **Background encodes:** `encode_queued` counts tokens queued for background encode, which take no request time.
- **Under `shadow`:** the same object with `"policy_applied": "exact"` and a `"plan"` holding the predicted values.

**Exact vs approximate counters:**
- `usage.prompt_tokens_details.cached_tokens` and `timings.cache_n` keep meaning **exact** prefix reuse.
- CodeSharp has a planned cache-miss rule (B9) that compares `cached_tokens` with the previous prompt **[verified as a
  design rule; no code found per review]**.
- Anthropic defines its cache counts as exact reads **[verified]**.
- New `timings` fields are `chunk_n` (approximately reused) and `chunk_recomputed_n`. `/metrics` gains counters.

**Capabilities.** `GET /v1/chunk-cache` (behind the inference API key) returns:

```json
{"versions": [1], "policies": ["exact", "shadow", "balanced", "fast", "auto"],
 "selectors": ["chunk_starts"], "wire_chunkers": ["symbol-512"], "auto_validated": [],
 "model": {"id": "...", "supported": true, "reason": null},
 "store": {"entries": 0, "bytes": 0, "budget_bytes": 0, "dtype": "f32"}, "max_chunks_per_request": 4096}
```

- `selectors` lists only what runs on the active backend (`query_relevance` appears once a probe exists).
- `wire_chunkers` lists text-first chunkers (`symbol-512`, `lines-512`).
- A 404 means "no convention: strip annotations".
- **Versioning.** Additive fields keep `v: 1`; a change of meaning (hash rule, span units, positioning) bumps `v`. Store
  format changes are invisible on the wire, because they change `ChunkKey`.

### 5.10 Encode admission and disk budget

On a miss, the background encode is queued only when **all** of these hold:
- the chunk is not `volatile` and not `no_store`;
- its path is not on the deny-list (§10);
- it has been seen in at least 2 requests (a sighting table keyed by text hash and namespace);
- the store is under its byte budget (`--chunk-store-budget`, **required**, no unlimited default).

Encodes run only while the server is idle, so they never evict a single-slot session snapshot. When the budget is
reached:
- eviction of server-ledger entries (§14, L2) runs in least-recently-used order;
- if eviction cannot free space, encodes stop and responses carry `chunk_store_unavailable` as a warning.

For scale: at F32, a 100K-token session's worth of misses is about 28 GB.

### 5.11 E4c: eligibility vs validation of text-first fixed chunks

Two separate questions:
- **Eligibility (wire correctness): granted.** E4c's round-trip census found 0 / 3,996 failures for `lines-512` (by
  construction; 15 / 15 mutants), so `lines-512` may be used on the wire and listed in `wire_chunkers`.
- **Validation (quality): open, moved to Phase I5.** E4c ran one fixed-chunk cell (QR and chunk starts, 10 % and 20 %, plus
  the query-before-context arm) but 9 contexts are missing and the comparison was not on the same context text.
  - **Remaining work:** finish the 9 missing contexts; a **same-context** comparison (chunk the same context text both
    ways, `lines-512` vs the reference chunking, same call sites); the query-before-context arm (§5.6).
  - **Pass rule (non-inferiority):** the lower 95 % CI bound of the gap-recovered difference vs the reference chunking is
    ≥ −0.10, on ≥ 30 matched instances.
  - **Outcomes:** pass → that (chunker × selector × budget) cell may enter `auto_validated`; fail → the 95 / 20 bar is
    unmet for every wire-eligible chunker and `balanced` stays documented as below the bar. Until then `auto_validated` is
    empty.

## 6. Transparent mode

- **Mechanism.** A server flag (`--chunk-transparent`, off by default) treats every text part, or every tool-result
  content, of at least `min_chunk_tokens` tokens as a candidate chunk identified by its own text hash.
  - It applies the request's policy, which defaults to `exact`. Transparent mode therefore only collects sightings and
    feeds background encode unless the client opts in.
  - **It requires `namespace` isolation** whenever the server has more than one client or any API key configured (§10).
  - It is the only route to reuse for clients that cannot annotate (Claude Code through `ANTHROPIC_BASE_URL`, §9).
- **Delimiters in text: not recommended.**
  - LMCache's CacheBlend marks boundaries in-band (`blend_special_str`, default `" # # "`; `enable_blending`,
    `blend_recompute_ratios` 0.15) **[verified on the docs page of 2026-11-02]**.
  - That page documents the **deprecated in-process mode**. The current multi-process mode docs say blending is
    unsupported there **[reported by review]**. Any alignment with LMCache must pin the LMCache version whose docs were
    read.
  - **Delimiter risks:**
    - a plain server shows the delimiters to the model;
    - file content or injected text can forge them;
    - stripping them changes the text relative to a plain server.
- **Risks of transparent mode:**
  - It reuses whole blocks, so an edit anywhere in a file read as one block misses the whole block.
  - It sees no chunker or ids.
  - Its sighting table is sensitive data (§10).

## 7. Control plane

### 7.1 What MCP can and cannot do

- **Can:** expose store management as tools with `inputSchema`, `outputSchema` and `structuredContent` (plus a serialised
  text copy) ([MCP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools); the rules match
  [2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) **[verified]**, plus `icons` and
  `execution.taskSupport` in 2025-11-25 **[reported by review]**).
  - `select` can return chunk text that a dotLLM-served host may reuse in transparent mode.
- **Cannot:** change the host's prompt, add request fields, or affect a model it does not run. With a hosted model behind
  the host, the control plane manages a local store only. It gives no TTFT benefit.

### 7.2 Tools (v1)

**Common parameters.**
- Every tool takes `store` (the store root; default from config).
- Tools that need the model take `server` (the dotLLM base URL). The server, not the CLI, owns the model identity and all
  K/V writes (§14, L1).
- Schemas are abbreviated to `properties`, with `additionalProperties: false` unless noted.

**Scope.** `compare` is lab tooling that runs GPU forwards, so it stays a CLI verb (`chunkcache compare`) and is not an
MCP tool in v1.

**`chunkcache_build`**: scan a solution or folder, chunk it with a wire-eligible chunker, and update the index
(tokenizer only). Optionally ask the server to encode.
```json
{"input": {"required": ["path"], "properties": {
   "store": {"type": "string"}, "server": {"type": "string"},
   "path": {"type": "string", "description": ".sln/.slnx/.csproj or folder"},
   "chunker": {"enum": ["symbol-512"], "default": "symbol-512", "description": "lines-512 is wire-eligible; not quality-validated"},
   "configuration": {"type": "string", "default": "Release"},
   "encode": {"type": "boolean", "default": false, "description": "queue all missing chunks via the server's prewarm"},
   "max_encode_tokens": {"type": "integer"}}},
 "output": {"properties": {
   "files": {"type": "integer"}, "chunks": {"type": "integer"}, "tokens": {"type": "integer"},
   "wire_ineligible_chunks": {"type": "integer"}, "denied_files": {"type": "integer"},
   "added": {"type": "integer"}, "removed": {"type": "integer"}, "unchanged": {"type": "integer"},
   "encode_queued_tokens": {"type": "integer"},
   "skipped_projects": {"type": "array", "items": {"type": "object", "properties": {
       "project": {"type": "string"}, "reason": {"type": "string"}}}},
   "elapsed_ms": {"type": "integer"}}}}
```
The tokenizer comes from the server's loaded model (`GET /v1/chunk-cache` plus a tokenizer fetch, or a local GGUF with
the same `TokenizerId`), so chunk token ids match the server's.

**`chunkcache_select`**: `ContextSelector.Select` over an index and its reference graph **[verified API, selection-tools
README]**.
```json
{"input": {"properties": {
   "store": {"type": "string"}, "server": {"type": "string"},
   "path": {"type": "string", "description": "solution/folder whose index to use"},
   "chunker": {"enum": ["symbol-512"], "default": "symbol-512"},
   "paths": {"type": "array", "items": {"type": "string"}}, "exclude": {"type": "array", "items": {"type": "string"}},
   "symbol": {"type": "string"}, "hops": {"type": "integer", "default": 1, "maximum": 100},
   "changed_since": {"type": "string"}, "token_budget": {"type": "integer"},
   "include_text": {"type": "boolean", "default": false},
   "order": {"enum": ["rank", "document"], "default": "document"}}},
 "output": {"properties": {
   "chunks": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "path": {"type": "string"}, "start_line": {"type": "integer"},
      "end_line": {"type": "integer"}, "tokens": {"type": "integer"}, "hash": {"type": "string"},
      "reason": {"type": "string"}, "detail": {"type": "string"}, "hop": {"type": "integer"},
      "stored": {"type": "boolean"}, "text": {"type": "string"}}}},
   "selected_tokens": {"type": "integer"}, "candidate_tokens": {"type": "integer"}, "trimmed": {"type": "integer"},
   "unmatched_patterns": {"type": "array", "items": {"type": "string"}},
   "notes": {"type": "array", "items": {"type": "string"}}}}}
```
- `hash` is the wire hash of the chunk's `plain` text, which is LF-normalised as scanned (§5.3, item 1).
- `stored` is answered by the server for the selected keys.

**`chunkcache_status`**: `ChunkIndex.Status(store, currentFiles)` **[verified API]**.
```json
{"input": {"properties": {"store": {"type": "string"}, "server": {"type": "string"}, "path": {"type": "string"},
   "chunker": {"enum": ["symbol-512"], "default": "symbol-512"}, "list_missing": {"type": "boolean", "default": false}}},
 "output": {"properties": {
   "total_chunks": {"type": "integer"}, "missing_chunks": {"type": "integer"}, "missing_tokens": {"type": "integer"},
   "up_to_date": {"type": "boolean"},
   "stale_files": {"type": "array", "items": {"type": "string"}}, "new_files": {"type": "array", "items": {"type": "string"}},
   "deleted_files": {"type": "array", "items": {"type": "string"}},
   "missing": {"type": "array", "items": {"type": "object", "properties": {
       "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"},
       "tokens": {"type": "integer"}}}},
   "store_bytes": {"type": "integer"}, "budget_bytes": {"type": "integer"}, "entries": {"type": "integer"}}}}
```

**`chunkcache_evict`**: through the server (`POST /v1/chunk-cache/evict`), which holds the write lock (§14, L3).
```json
{"input": {"properties": {"store": {"type": "string"}, "server": {"type": "string"},
   "mode": {"enum": ["orphans", "path", "namespace", "all"], "default": "orphans"},
   "path": {"type": "string", "description": "glob; mode=path: forget every entry first seen under it"},
   "namespace": {"type": "string"}, "dry_run": {"type": "boolean", "default": true}}},
 "output": {"properties": {"evicted": {"type": "integer"}, "freed_bytes": {"type": "integer"},
   "kept_referenced": {"type": "integer"}, "dry_run": {"type": "boolean"}}}}
```
**Modes:**
- `orphans`: keys referenced by neither an index nor the server ledger (§14, L2).
- `path`: a "forget this repo" request. It removes entries whose ledger provenance lies under the glob, and their index
  references.
- `all`: wipes the namespace or the store.

LRU and age eviction are internal to the budget (§5.10); they are not tool modes in v1.

**`chunkcache_prewarm`**: queue isolated encodes on the server (`POST /v1/chunk-cache/prewarm`). It takes **text only**:
there is no hash → key map, and a hash-only API would be a membership oracle.
```json
{"input": {"properties": {"store": {"type": "string"}, "server": {"type": "string"},
   "select": {"type": "object", "additionalProperties": true, "description": "a chunkcache_select input; text is read locally"},
   "texts": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}}}},
   "max_tokens": {"type": "integer"}}},
 "output": {"properties": {"requested": {"type": "integer"}, "already_stored": {"type": "integer"},
   "queued": {"type": "integer"}, "queued_tokens": {"type": "integer"}, "refused": {"type": "integer"},
   "refused_reasons": {"type": "array", "items": {"type": "string"}}}}}
```
Encodes run under the idle and budget rules of §5.10. Prewarm bypasses only the "seen twice" rule.

**`chunkcache_explain`**: a dry run of §5.5 for a request body (`POST /v1/chunk-cache/explain`). It takes text only (the
full request); hash lists are not accepted.
```json
{"input": {"required": ["request"], "properties": {"server": {"type": "string"},
   "request": {"type": "object", "additionalProperties": true}}},
 "output": {"properties": {
   "policy_would_apply": {"type": "string"}, "reason": {"type": "string"},
   "chunks": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "status": {"enum": ["prefix", "hit", "miss", "ignored"]},
      "why": {"type": "string", "description": "hash mismatch, template altered, not wire-eligible, too short, other model, CRLF vs index"}}}},
   "predicted_ms": {"type": "object", "properties": {"reuse": {"type": "number"}, "full_prefill": {"type": "number"}}},
   "warnings": {"type": "array", "items": {"type": "string"}}}}}
```
- Per-chunk status is returned only to an authenticated caller for its own namespace (§10).
- The `why` value "CRLF vs index" comes from comparing the chunk text with the indexed file's LF text when the chunk's
  `source.path` is in the caller's index.

## 8. .NET wrapper abstractions

### 8.1 Constraints

**Do not rely on `AIContent.AdditionalProperties` or `ChatOptions.AdditionalProperties` reaching the wire.**
- `ChatOptions.AdditionalProperties` is dropped silently (`AnthropicPromptCacheHandler.cs` remarks, about
  `reasoning_effort`) **[verified]**.
- Per-content properties on the OpenAI bridge are unverified **[assumption: dropped]**.

**Other routes are unconfirmed or fragile:**
- `ChatOptions.RawRepresentationFactory` pre-builds the provider options
  ([docs](https://learn.microsoft.com/en-us/dotnet/api/microsoft.extensions.ai.chatoptions.rawrepresentationfactory))
  **[verified]**.
- **openai-dotnet `JsonPatch Patch`:** an experimental `[Experimental("SCME0001")] ref JsonPatch Patch` exists across
  models ([PR #834](https://github.com/openai/openai-dotnet/pull/834.diff)), and Semantic Kernel uses it for extra body
  fields ([PR #13934](https://github.com/microsoft/semantic-kernel/pull/13934)) **[reported]**.
  - Whether `ChatCompletionOptions` has it, and from which version, is **unconfirmed**.
  - It reaches top-level fields only.

**The reference transport is therefore an HTTP body handler**, the seam CodeSharp uses for Anthropic `cache_control`:
- an MEAI decorator records the spans;
- a `DelegatingHandler` writes `chunk_cache` (placement B) into the JSON body.

### 8.2 Interfaces

Package `DotLLM.ChunkCache.Client`: a permissive licence, no engine reference.

```csharp
namespace DotLLM.ChunkCache.Client;

/// One chunk inside one message part, identified by its exact text. Offsets are UTF-16 chars here (.NET strings);
/// the body handler converts them to the wire's UTF-8 byte offsets.
public sealed record ChunkSpan(
    string Id, string Hash,                    // Hash: "sha256:<hex>" of the UTF-8 bytes of the span text
    int Start = 0, int? End = null,            // UTF-16 offsets within the part text; null End = to the end
    string? Chunker = null, ChunkSourceInfo? Source = null,
    bool Volatile = false, bool NoStore = false);

public sealed record ChunkSourceInfo(string Path, int StartLine, int EndLine, string? Revision);

/// Reads a file the harness is about to show the model and returns the text plus its chunk spans, chunked with a
/// wire-eligible (text-first) chunker over the same normalised text the store indexes.
public interface IChunkSource
{
    ValueTask<ChunkedText> ReadAsync(string path, LineRange? window, CancellationToken ct);
}
public sealed record ChunkedText(string Text, IReadOnlyList<ChunkSpan> Spans, string ContentSha256,
                                 IReadOnlyList<string> Notes);   // e.g. "2 chunks cut by the window: not annotated"
public readonly record struct LineRange(int Start, int End);

/// Source-change notifications. Identity is content, so this is an optimisation (re-read and prewarm early);
/// without it, stale chunks simply miss.
public interface IInvalidationSignal
{
    IAsyncEnumerable<ChunkInvalidation> ReadAllAsync(CancellationToken ct);
}
public sealed record ChunkInvalidation(string Path, InvalidationKind Kind, string? NewContentSha256, string Origin);
public enum InvalidationKind { Modified, Deleted, Renamed, Unknown }        // Origin: "edit-tool", "fs-watch", "git"

/// Chooses the request policy. The default implementation returns Policy = "exact".
public interface IRecomputePolicy
{
    ChunkRequestOptions Decide(ChunkRequestContext context);
}
public sealed record ChunkRequestContext(string ModelId, int PromptTokensEstimate, int ChunkTokens,
    ChunkCacheCapabilities? Server, bool IsSubAgent, bool AfterCompaction, bool UserOptedIntoApproximation);
public sealed record ChunkRequestOptions(string Policy = "exact", string? Selector = null, double? Budget = null,
    string OnMiss = "prefill", bool Strict = false, string Report = "summary");

/// Control plane over the server's /v1/chunk-cache endpoints (plus local index operations).
public interface IChunkCacheClient
{
    ValueTask<ChunkCacheCapabilities?> GetCapabilitiesAsync(CancellationToken ct);    // null = convention absent
    ValueTask<SelectResult> SelectAsync(SelectRequest request, CancellationToken ct);
    ValueTask<PrewarmResult> PrewarmAsync(PrewarmRequest request, CancellationToken ct); // text only
    ValueTask<StatusResult> StatusAsync(StatusRequest request, CancellationToken ct);
    ValueTask<EvictResult> EvictAsync(EvictRequest request, CancellationToken ct);
    ValueTask<ExplainResult> ExplainAsync(JsonObject requestBody, CancellationToken ct);
}
```

### 8.3 Pipeline pieces

```csharp
/// MEAI decorator: maps chunk-bearing parts to spans (via the registry), publishes the manifest to the handler
/// through an AsyncLocal scope, and lifts the response's chunk_cache into ChatResponse.AdditionalProperties.
public sealed class ChunkAnnotatingChatClient(IChatClient inner, IChunkSpanRegistry registry,
                                              IRecomputePolicy policy) : DelegatingChatClient(inner)
{
    public override async Task<ChatResponse> GetResponseAsync(IEnumerable<ChatMessage> messages,
        ChatOptions? options = null, CancellationToken ct = default)
    {
        var list = messages as IList<ChatMessage> ?? messages.ToList();
        using var scope = ChunkManifestScope.Begin(BuildManifest(list));
        var response = await base.GetResponseAsync(list, options, ct);
        ChunkCacheReport.Attach(response, scope.ResponseReport);
        return response;
    }
    // GetStreamingResponseAsync: the same; the report arrives with the final update.
}

/// Part text -> spans, registered by the file-read tool when it produces a result.
public interface IChunkSpanRegistry
{
    void Register(string partText, IReadOnlyList<ChunkSpan> spans);
    bool TryGet(string partText, out IReadOnlyList<ChunkSpan> spans);
}

/// On the provider HttpClient (OpenAI Chat Completions JSON). Locates each registered part in the *serialised* body
/// by re-hashing the *decoded* part texts (MEAI and wire indices differ; serialisers escape non-ASCII), verifies every
/// span hash (a mutated part yields no annotation, never a wrong one), converts offsets to UTF-8 bytes, adds
/// "chunk_cache", and parses the response's chunk_cache back into the scope (lazily from SSE when streaming).
public sealed class ChunkCacheBodyHandler : DelegatingHandler { /* SendAsync as described */ }
```

- **Installation.** Install the handler only on providers that are actually dotLLM (gate on the provider kind, not on
  the shared OpenAI-compatible builder) and whose probe succeeded.
- **Probe timing.** Probe when the provider is built, and again when the model id changes. CodeSharp: §12.1.

### 8.4 Transports

| transport | when | notes |
|---|---|---|
| **HTTP, OpenAI Chat Completions + `chunk_cache`** (reference) | any harness | CodeSharp's wire (ADR-009) |
| HTTP, Anthropic Messages + `chunk_cache` | clients on that wire to dotLLM | same fields; the stream report is in `message_delta` |
| in-process (dotLLM engine linked) | GPL-compatible hosts only | not for CodeSharp (ADR-009, ADR-011). It would use `StoredContextAssembler.ForModel(config, modelId, quant, tokenizerId)` and `GgufIdentity` **[verified API]**, but needs the same engine work as the server (§14, L5) |

## 9. Adapter matrix

| framework | where annotations go in | can | cannot | effort |
|---|---|---|---|---|
| **Microsoft Agent Framework (.NET)** | `ChunkAnnotatingChatClient` in the chat-client pipeline plus `ChunkCacheBodyHandler` on the provider `HttpClient`. An `AIContextProvider` for harness-built selections; an `IChatReducer` / compactor for chunk-preserving compaction (both used in CodeSharp **[verified]**) | the full convention, sub-agent hand-off, telemetry | rely on `AdditionalProperties` reaching the wire | M (reference) |
| **Semantic Kernel (.NET)** | SK chat services bridge to `IChatClient`, so the same decorator and handler apply. `IFunctionInvocationFilter` registers file-read outputs **[names reported correct by review]** | the full convention via the bridge | `PromptExecutionSettings.ExtensionData` to the wire is unconfirmed | S–M |
| **LangChain / LangGraph (Python)** | `ChatOpenAI(extra_body={"chunk_cache": ...})` (placement B); v1 agent middleware `wrap_model_call` builds the manifest **[names reported correct]** | the full convention via B; a chunk-preserving replacement for `SummarizationMiddleware` | inline fields, depending on the adapter | M (deferred) |
| **Claude Code** | MCP for the control plane; `ANTHROPIC_BASE_URL` → dotLLM `/v1/messages` with transparent mode | store management, `select`; block-hash reuse of repeated tool results on a local model | annotate its own requests (hooks cannot edit the API request **[reported]**); any benefit with Anthropic-hosted models. Its Read output numbers lines absolutely. A PostToolUse hook might re-render it (`updatedToolOutput` **[reported; unverified for built-in tools]**) | S (MCP) / L |
| **Generic OpenAI-compatible client** | `chunk_cache` via `extra_body` or a raw body | the full convention | — | S |
| **llama.cpp / vLLM / LMCache as targets** | none | degrade to plain text | a common convention | n/a |

**Alignment.**
- llama.cpp offers `cache_prompt` and `--cache-reuse` (KV shifting)
  ([README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) **[verified]**).
- vLLM's APC hashes blocks over the parent hash, tokens and extra keys; our `namespace` corresponds to its `cache_salt`
  ([design](https://docs.vllm.ai/en/latest/design/prefix_caching.html) **[verified]**).
- `budget` corresponds to LMCache's `blend_recompute_ratios`.
- The marker uses Anthropic's per-block placement but its own key (`chunk`), because `cache_control` means exact
  breakpoints. Counters (`chunk_n`) stay separate from exact ones (`cache_n`).

## 10. Security and privacy

- **The store contains the source code.**
  - What it holds:
    - each `.ckv` holds the chunk's **token ids** beside the K/V **[verified]**;
    - the index and server ledger hold paths and hashes;
    - the sighting table holds text hashes.
  - Treat the store root like the repository:
    - same ACLs;
    - outside synced folders;
    - git-ignored;
    - excluded from crash dumps and telemetry.
- **Membership oracle.** A per-chunk hit/miss is itself a probe: send candidate text and observe "hit".
  - Responses report **counts only** by default.
  - `per_chunk` reports and `explain` per-chunk status go only to an authenticated caller, for its own namespace.
  - Hash-only APIs do not exist; prewarm and explain take text.
- **Authentication and isolation.**
  - `/v1/chunk-cache/*` sits behind the same API-key auth as inference. Prewarm is a GPU and disk DoS vector, so it gets
    the inference rate limits.
  - **Namespace isolation is on by default** as soon as any API key or more than one client is configured. The namespace
    defaults to one per key and is salted into `ChunkKey`.
  - Transparent mode requires it.
  - A namespace-free store is for single-user local servers only.
- **Secrets.**
  - **Path deny-list** (default; extendable):
    - `.env*`
    - `*.pem`, `*.key`, `*.pfx`, `id_*`
    - `secrets.json`, `appsettings.*.Development.json`
    - `.git/**`
  - Denied paths are never chunked by `build` or encoded by prewarm.
  - Harnesses set `no_store` on reads of denied paths. The server cannot see paths, so it trusts `no_store`.
  - **Server switch:** `--chunk-store-index-only` stores only chunks that an index references (built from a scanned,
    deny-listed tree), so text from ad-hoc reads is never persisted.
- **Deletion.** `evict --mode path` ("forget this repo") and `--mode namespace` / `all` remove the K/V, the index
  references, the ledger rows and the sighting rows.
- **Poisoning.**
  - The K/V is always computed by the server from received, re-hashed text.
  - Model identity is content-based (`GgufIdentity`; a full hash with `--strict-model-id`) **[verified]**.
  - Only the server writes (§14, L1), so no other process writes K/V under a model's key.
  - **Residual risk:** the sampled model id misses interior-only tensor edits. A shared store therefore wants the full
    hash.
- **No server-side file reads in v1.** `source.path` is telemetry only.
- **CLI git refs.** They go through dotLLM's `GitCliInfo` validation (no shell; a leading `-` is rejected) **[verified,
  `Tooling/GitInfo.cs`]**.

## 11. Harness integration checklist

1. **Probe** `GET /v1/chunk-cache`. Install the annotating path only when it succeeds; otherwise strip annotations.
2. **Mark file reads.** Read files through an `IChunkSource` that uses a wire-eligible chunker over the **same normalised
   text** the store indexes (LF). Register the spans, and put headers and window notes in glue.
3. **Default policy `exact`.** Offer `shadow` for measurement. Approximate policies need an explicit user or session
   opt-in, shown in the UI.
4. **Leave the history alone.** Keep it chronological and append-only. Apply the ordering rules only to context the
   harness composes (§5.6). Pass the user's task as the query (the last user message, by default).
5. **Don't mutate chunk text after registration.** Truncation, dedupe and hook rewrites must keep spans whole or drop
   the annotation. Appending a suffix keeps manifest spans valid. The handler's re-hash catches violations, but they cost
   reuse.
6. **Invalidation is optional.** Content identity makes edits miss correctly.
   - Use edit-tool events (`IInvalidationSignal`) to re-read and prewarm early.
   - External edits need no watcher.
7. **Compaction keeps chunk parts byte-identical**, or drops them whole, and re-emits them in a stable order after the
   summary (§12.3).
8. **Sub-agents** receive chunk references and text through the same `IChunkSource`. They do not receive the parent's
   conversation.
9. **Persist the chunk list per session**, in the harness's own state: `(id, hash, path, range, chunker)`, in order. Use
   it for resume, compaction and `explain`.
10. **Log `chunk_cache` per call** (policy applied, reason, counts, TTFT, estimate). Keep exact-prefix monitoring
    separate.
11. **Never prewarm as a side call** on a single-slot server's active slot. The server runs encodes when idle.
12. **Mark secrets.** Set `no_store` on reads of deny-listed paths.

## 12. Reference integration: CodeSharp

Facts are from codesharp-d1 (`codesharp-answers.md`, `codesharp-review-answers.md`) **[reported]**, except where re-read
**[verified]**. Items they marked unverified stay open questions (§12.7).

### 12.1 Fit

- **Handler chain and gate.**
  - The handler chain in `ChatClientFactory.BuildOpenAiCompatibleClient` (~408–445) is `ProviderLivenessHandler`, then
    `DotLlmMaxTokensHandler`, then the primary handler.
  - `DotLlmMaxTokensHandler` already reads the body, parses it as `JsonNode` and re-wraps it in a `StringContent`. That
    is the precedent for `ChunkCacheBodyHandler`, which goes next to it.
  - **Gate on the `dotllm` provider, not on "openai-compatible".** Both share `BuildOpenAiCompatibleClient`, and the
    existing handler is installed only when `activityProbe != null`.
- **Decorator placement.**
  - The factory stack is `OpenTelemetry > UsageSpanTagging > Retrying > LocalServerStartAwait >
    UniqueToolCallId(EmptyToolArguments(LivenessObserving(provider)))`.
  - `ChunkAnnotatingChatClient` goes **below `Retrying`**, so retries resend the same manifest, and above
    `UniqueToolCallId`. It may go lower, because spans are keyed by text and call ids do not matter.
  - **What it sees.** It runs once per HTTP-bound call, below the invocation loop (`MafAgentEngine` ~1046–1090). It sees
    the final message list after dedupe, the guard and compaction, but **not** which tool produced a result. Spans are
    therefore keyed by **part text**, never by call id.
  - **Unverified:** whether the decorator → handler hand-off through `AsyncLocal` survives `Retrying`, `HttpClient` and
    the liveness handler (open question 1).
  - **Streaming:** the handler parses SSE lazily, as `SseTimingsScanner` does.
- **Prefix-cache policy.**
  - `PrefixCacheLevel { None, PrefixCached, SingleSlot }` and `IPrefixCachePolicy` (`LevelFor`, `SideCallEvictsSession`)
    are in `src/CodeSharp.Core/PrefixCache/` **[verified]**.
  - `RegistryPrefixCachePolicy` is in `src/CodeSharp.Models/RegistryPrefixCachePolicy.cs`; it delegates to
    `PrefixCacheSensitivity.Of(provider)`.
  - **Agreed: a capability flag, not a fourth enum value.** The level derives from `ProviderDescriptor.PrefixSnapshots`
    alone and never sees the server. The probe is the first server-derived fact.
  - **New member:** `bool ChunkReuseFor(string? modelId)` on `IPrefixCachePolicy`, backed by cached probe state. The probe
    is async; `LevelFor` is sync. It is re-probed when the model id from `/props` changes. Reload detection (B7) is
    unbuilt.
- **Rule scope and relaxations.** Keep the spec's scoping:
  - A4, B3 and B5 apply to every dotLLM provider;
  - B1 and B2 apply only when `PrefixSnapshots == 1`;
  - A1, A3, B6 and B9 apply to all providers.

  | rule (scope) | status | with `ChunkReuse` |
  |---|---|---|
  | A4 no piecemeal spill (all dotLLM) | built (`ToolOutputGuard.cs` ~725) | keep for non-chunk results; spilling a chunk-bearing result whole is cheap, since its re-read hits |
  | B1 / B2 sub-agents in the foreground, side calls off the server (`PrefixSnapshots == 1`) | specified | keep. The resume re-read becomes chunk hits plus glue, so the notice's cost estimate drops |
  | B3 append-only history (all dotLLM) | **unbuilt**: `MemoryIndexDedupeChatClient` still rewrites mid-history | still required; chunks do not cover non-chunk text |
  | B5 auto-compact (all dotLLM): size-based, trigger 85 %, target 45 %, system prompt and tools byte-identical | specified | the miss is limited to non-chunk text if the planner keeps chunks (§12.3) |
  | B9 cache-miss monitoring (all providers) | **unbuilt** (only `SseTimingsScanner` reads `cached_tokens` / `cache_n`) | unchanged (exact only); add a chunk hit-rate line |

- **Mutators after registration** (re-hash in the handler catches all of them):
  - `ToolOutputGuardChatClient` replaces whole results with a receipt-style spill. It **cannot cut at span boundaries
    without a new API**, so the annotation is lost.
  - `PostToolUseHookFunction` can rewrite a result (`updatedToolOutput`) and **appends `additionalContext` to the same
    text**. An appended suffix keeps manifest spans valid: offsets are unchanged, and the reference client ends a span registered "to the end of the part" where the registered text ends, sending an explicit `end`, so the suffix is never inside a span. A span is lost only if its own bytes change.
  - `ImageToolResultRewriting` affects images only.
  - `MemoryIndexDedupe`: B3.
- **Invalidation.** PostToolUse on edit and write tools feeds `IInvalidationSignal`. Whether `HookContext` carries the
  file path is unverified (it carries `ToolName`); it may need a path argument. There is no conversation-level watcher,
  and none is needed: content hashing makes stale reads miss.

### 12.2 File reads (`read_file`)

Facts about `ReadFileTool` **[reported]**:
- **BOM:** `File.ReadAllTextAsync` strips a UTF-8 BOM.
- **Line endings:** CRLF is **not** normalised. `Split('\n')` + `Join('\n')` keeps `\r`.
- **No line numbers and no header.**
- **Cap:** without offset or limit, a read is capped at `EffectiveReadFileMaxLines` (default 2,000). An explicit
  offset / limit (1-based) is honoured uncapped.
- **Trailer:** when lines are excluded it appends `\n…(showing lines a-b of N)`, which is glue. For newline-terminated
  files the windowed total `N` is off by one.

Consequences:
1. **CRLF.** Every chunk of a CRLF file misses against LF-indexed entries; LF files match.
   - **Normalising `read_file` output to LF is cheap and safe.** `EditFileTool` already retries in the file's own
     line-ending convention when `old_string` contains `\n` and does not match, and translates the replacement the same
     way. It picks CRLF if the file has any `\r\n`.
   - So: option (c) for production; the spike may start with LF-only files (option a).
2. **Cap and windows.**
   - Only whole chunks inside the read lines are annotated.
   - A chunk-aware read rounds the window out to chunk boundaries within the cap.
   - The 2,000-line cap cuts large files: their tails are reusable only through explicit windowed reads.

### 12.3 Chunk-aware compaction planner

**Today.** `SessionCompactor.Plan(byte[] state, keepFirstTurns, keepLastTurns)` works on the **serialised session JSON,
by turns**, not on `ChatMessage` objects. It keeps the head and tail turns verbatim and flattens the middle with
`CompactionFlattener`. B5's 45 % target is size-based.

**The chunk-aware planner** works on the same JSON:
1. Collect the chunk-bearing parts in the middle, from the session's chunk list.
2. Keep a subset within the size target: chunks referenced by the tail, or in the current selection, and only the newest
   read of each path.
3. Summarise the rest.
4. Emit the head, the summary, one message with the kept chunks (document order, glue headers, byte-identical), then the
   tail.
5. Persist the new chunk list.

Whether it replaces `CompactionFlattener` behind a setting is CodeSharp's design choice. `WorkerCompactionReducer`
follows the same rule.

### 12.4 Spike scope and preconditions

- **Precondition: a clean prefix baseline first.** Build or finish **B3** (append-only memory index) and the **B9**
  cache-miss monitor before any reuse comparison. Ideally build **B7** (reload detection) too. Without them every dotLLM
  turn already breaks the prefix, and chunk effects cannot be separated from prefix churn.
- **What can run before.** `shadow`-mode hit-rate measurement (plumbing, plan counts) needs neither precondition, and can
  run earlier.
- **In:**
  - probe and `ChunkReuseFor`;
  - the body handler and decorator on the `dotllm` provider;
  - LF-normalised, chunk-aware `read_file`;
  - PostToolUse invalidation;
  - telemetry;
  - `exact` / `shadow` (approximate policies only behind a dev setting);
  - the planner behind a setting;
  - sub-agent hand-off.
- **Out:** in-process hosting (ADR-009 / ADR-011), transparent mode, Python, recurrent models.
- **Model and GPU:**
  - CodeSharp has no default dotLLM model, so the spike pins Qwen3-4B-Instruct-2507 Q4_K_M.
  - GPU-bound: Vulkan on Strix. The T5500 only with the user's approval; GPU work is coordinated through the user.

### 12.5 Success metrics

Measured on replayed recorded sessions, with 3 session sets and bootstrap intervals:

| metric | definition | target |
|---|---|---|
| chunk hit rate (`shadow`) | planned reusable tokens / annotated tokens, after compaction, sub-agent and resume events | report; ≥ 0.8 is a hypothesis |
| plumbing loss | annotations dropped by the re-hash, template, cap or mutator checks / registered spans | < 5 %, every drop attributed |
| `exact` neutrality | output and `cached_tokens` with the path installed vs without | identical |
| TTFT (after #1540, opt-in) | full prefill / applied reuse, Vulkan | report, with the prediction error |
| accuracy (after §5.11 validation, opt-in) | scripted, checkable tasks, `balanced` vs `exact` | ≥ 95 % at ≤ 20 % recompute |
| overhead | handler and decorator time; store bytes per session | < 5 ms; report |

### 12.6 Test plan

- **CodeSharp unit tests:**
  - the manifest matches registered spans;
  - the hash is over decoded text even when the body escapes non-ASCII;
  - a guard-replaced or hook-rewritten part gives no annotation, and an appended hook suffix keeps prefix spans;
  - string vs parts content;
  - UTF-16 → UTF-8 offsets;
  - lazy SSE parsing;
  - no capability, or an `openai-compatible` provider: body byte-identical to today;
  - the planner keeps chunk bytes;
  - mutation evidence.
- **dotLLM contract tests:**
  - unknown fields are ignored;
  - strict codes;
  - mismatched and template-altered spans become plain text;
  - `exact` and `shadow` are bit-identical to an unannotated request, including after an approximate request on the same
    slot;
  - `cached_tokens` stays exact-only;
  - a CPU entry never hits on Vulkan;
  - `orphans` eviction keeps ledger entries.
- **Integration** (after the §12.4 precondition; Vulkan under the GPU lock): replay sessions under `exact` and `shadow`,
  each with a compaction, a sub-agent, a restart and an external edit.
- **Regression:** CodeSharp provider-conformance, with the capability absent and present.

### 12.7 Open questions for codesharp-d1

The questions resolved by their answers are folded in above: the flag vs a fourth enum value; the body handler; the
decorator position; CRLF; the guard cannot cut at spans.

1. **AsyncLocal hand-off.** Does the decorator → handler hand-off survive `Retrying` / `HttpClient` /
   `ProviderLivenessHandler`? If not, carry the manifest in a request option or header (unverified).
2. **Session JSON.** Does it round-trip content `AdditionalProperties`? If not, where does the per-session chunk list
   live (unverified)?
3. **Sub-agents.** How do they receive history? `SubAgentBootstrap` was not located. Is a chunk hand-off message
   acceptable?
4. **Invalidation.** Does `HookContext` carry the edited file's path (unverified)?
5. **Planner.** Replace `CompactionFlattener` behind a setting, and does B5's 45 % count kept chunks?
6. **Guard.** Is a span-aware spill API worth adding to `ToolOutputGuard`, or does it drop annotations?
7. **Scheduling.** When will B3, B9 and B7 be scheduled? They are the spike precondition; the design doc puts B3 in Stage
   B, its own release.
8. **Corpus.** Is there a recorded-session corpus (it contains source code) and a checkable task set?
9. **Telemetry.** Which OpenTelemetry attribute names (`UsageSpanTaggingChatClient`, `src/CodeSharp.Models`)?
10. **Models.** Is a hybrid model (Qwen3.8 / Flash-Next) planned for CodeSharp sessions? v1 cannot reuse with it.

## 13. Phased delivery

| phase | content | depends on | outward-facing |
|---|---|---|---|
| I0 | this spec; codesharp-d1 answers; **E4c** scheduled | — | no |
| I1a | server, wire only: parsing (both placements), hash and template checks, special-token rule, lineage-tagged snapshots, `exact` / `shadow`, counts, `/v1/chunk-cache` (capabilities, explain), auth, contract tests | L4, L7 (§14); dotLLM session agreement | a dotLLM PR only with the user's approval |
| I1b | server, store: sole-writer encodes, ledger, budget and admission, prewarm, evict, deny / no_store, namespaces | L1–L4, L8 | same |
| I2 | `DotLLM.ChunkCache.Client` (.NET) | I1a contract | NuGet via the dotLLM release path; permissive licence |
| I3 | `chunkcache` CLI (Phase S Task 7, revised by L1 and L6) + MCP server (§7.2) | I1b | tool package |
| I4 | CodeSharp spike, `exact` / `shadow` | I1–I3; CodeSharp B3 + B9 built first (`shadow` hit rates may run before) | CodeSharp branch |
| I5 | applied reuse (`balanced`, `fast`, `auto` gates) | **engine work L5**, **dotLLM #1540**, a Vulkan QR probe, **`lines-512` validation** (§5.11) | report to the user |
| I6 | compact F16 / Q8_0 rows, direct-to-device loading, cold-disk TTFT | the dotLLM Vulkan owner | — |
| I7 | transparent mode; Claude Code recipe | I1b, namespaces | docs |

**Deferred:**
- adapters and PRs for Semantic Kernel, LangChain and Claude Code;
- `contextual` positioning;
- by-reference chunks;
- the `hybrid` selector (server-side graph);
- `numbered-relative`;
- multi-tenant hosting beyond namespaces;
- recurrent models;
- the E7 quality half.

## 14. Required library and engine changes (blocking item B4 and related)

| # | change | why | owner |
|---|---|---|---|
| **L1** | **The server is the only K/V writer.** `chunkcache build --encode` and `prewarm` become HTTP calls to the server; the CLI never calls `IChunkStore.Put`. An offline mode (no server running) may let the CLI write while holding the store lock | CPU-encoded entries can never hit a Vulkan server (the backend is in the key); one writer removes the lock conflict below | this project (CLI), dotLLM session (server) |
| **L2** | **A server ledger, `ledger-server.json`, next to the indexes** (or an access-time sidecar). It lists each server-written key with its namespace, first-seen provenance (`source.path` if given), last use and bytes. `ChunkIndex.ReferencedKeysUnder` / `StoreWideOrphans` must count ledger keys as referenced | today `StoreWideOrphans` = store keys minus index-referenced keys (`ChunkIndex.cs:263-279`), so `orphans` eviction would delete every server-written entry; LRU and budget eviction need last-use times | this project (`DotLLM.ChunkReuse`) |
| **L3** | **Lock model:** the exclusive `.chunkstore.lock` (`AcquireStoreLock`) is held only for short scopes: per Put batch, per ledger or index save, per eviction pass. Index-only updates (CLI build without encode) take a per-index lock (`index-<chunker>.lock`), not the store lock. Eviction runs in the server, or in the CLI only in offline mode | the current contract (every putting process holds the exclusive lock from update through eviction, `ChunkIndex.cs:284-289`) would block the server for an entire `build` | this project |
| **L4** | **Persist the backend tag in the `.ckv` header** and check it on read (the skipped test `TODO_StoreHeader_PersistsBackendTag`). A CPU-encoded entry is a miss on a Vulkan server, by key and by header | today the backend is in the key only; `ChunkKvEntry.Backend` exists only on the Vulkan branch | this project + the Vulkan branch merge |
| **L5** | **Engine assembly into the server's KV:** non-CPU backends, paged and quantised destinations, multi-slot, store rows in the cache's dtype. `StoredContextAssembler` hard-codes `"cpu"` and F32 today | wire plumbing alone cannot apply reuse | dotLLM session (engine, Vulkan owner) |
| **L6** | **Text-first chunkers:** `lines-512`; `SymbolChunker` marks over-long-line token slices wire-ineligible; `build` asserts `EncodeRaw(text) == ids` per chunk | B1 (§5.3, item 4) | this project |
| **L7** | **Snapshot lineage** (`exact` / `approx` per row range) in the prefix-snapshot store, with restore limited by policy | B2 (§5.3, item 8) | dotLLM session |
| **L8** | **`namespace` in `ChunkKey`** (a new field; key scheme v4) and in the ledger | isolation (§10) | this project |
| **L9** | **Index path keyed by chunker and model** (and later by render profile): `index-<chunker>.<model12>[-<render>].json`, plus a `chunkcache.json` registry in the store root. A server-backed CLI keys on the **server's** model identity (from `GET /v1/chunk-cache`), not the local GGUF's | two models (or a chunker change) sharing a store root no longer collide; `numbered-relative` slots in later | this project (Phase I Task 4b) |

## 15. Sources

**Local (verified):**
- `REPORT.md`
- `experiments/*/README.md` (G2 as revised in the working tree)
- `.superpowers/sdd/2026-11-01-phase-s/`: task-3 and task-4 reports, `codesharp-answers.md`, `integration-spec-review.md`,
  `codesharp-review-answers.md`
- dotLLM `docs/SERVER.md`, `docs/ANTHROPIC_API.md`, `Corpus/FixedSizeChunker.cs`
- CodeSharp `decisions.md` (ADR-009, ADR-011), its prefix-cache alignment spec, `Core/PrefixCache/*.cs`,
  `AnthropicPromptCacheHandler.cs`

**Web (fetched 2026-11-02):** the URLs cited inline: Anthropic, MCP (2025-11-25 per the review), MEAI, LMCache, llama.cpp,
vLLM.

**Unconfirmed:**
- openai-dotnet PR #834 and Semantic Kernel PR #13934 (search results only).
- OpenAI, Gemini, MAF, SK, LangChain and Claude Code docs were not fetched. They are marked **[reported]** or
  **[assumption]** where used.
