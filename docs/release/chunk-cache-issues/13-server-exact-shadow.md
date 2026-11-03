# Server: `chunk_cache` `exact` / `shadow` execution and response metadata (draft)

> **Status: DRAFT, not filed.** Lane S, plan Task 13. Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and #1542
> (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Packaging: Tasks 10, 11 and 13 ship together as one PR** (this part wires the endpoints, so the flag does something
> when merged). Branch `feature/chunk-cache-server`, worktree `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`:
> merges `f6c251a3` (snapshot lineage, Task 12) and `70b2b594` (Lane L library: store, key, namespace, ledger, locks),
> then `c8a56e5b` (pipeline, report, metrics, identity), `94f99010` (endpoint wiring), `f3303914` (docs), `32b11dab` and
> `2edc099e` (tests from surviving mutants).
> **PR split note:** the server branch now contains the Lane L library merge; upstream, the library PRs (issues 02–05)
> and the lineage PR (issue 12) must land on `dev` first, or this PR carries them.

## Title

Server: `chunk_cache` wire convention: run `exact` / `shadow` and report chunk hits behind `--chunk-cache` (output unchanged)

## Body

Refs #1543, #1542.

The parser (Task 10) validates annotations and the locator (Task 11) finds each span in the rendered prompt. This part
wires both into `/v1/chat/completions` and `/v1/messages` and runs the two policies that never change the output:

- **`exact`** (default): the request is rendered, tokenised and dispatched exactly as the unannotated request; the
  annotations only produce a report (how many chunks were annotated, inside the restored exact prefix, found in the chunk
  store, missing or ignored).
- **`shadow`**: as `exact`, plus a reuse **plan** that is computed and not applied: which rows a chunk-reuse policy
  would take from the store and recompute, and the predicted time to first token from a provisional cost model.
- `balanced`, `fast`, `auto` parse and are served `exact` with `reason: "chunk_policy_unavailable"` (strict: 400) until
  applied reuse exists. Recurrent / hybrid / diffusion models, backends other than CPU and Vulkan, and RoPE variants
  the chunk re-rotation does not reproduce give `chunk_model_unsupported` (every annotation ignored).

What it adds:

- **The server references `DotLLM.ChunkReuse`** (store, `ChunkKey`, `ChunkFingerprint`, `GgufIdentity`,
  `ChunkTokenization`). Maintainer decision: that assembly brings `Microsoft.CodeAnalysis.CSharp` (Roslyn, used by the
  symbol chunker) and `DotLLM.Vulkan` into the server's dependency graph.
- **`ServerModelIdentity`**: content model id (`GgufIdentity.ModelId`, sampled), tokenizer id, quantisation label,
  backend tag and stored K/V type (F32), folded into the fingerprint the `chunkcache` CLI uses. An entry the CLI built
  for the same GGUF (without `--strict-model-id`) is a hit; the CLI's index loads under the server's identity (same
  producer hash). Computed once per loaded model.
- **`ChunkCachePipeline`**, per located span in prompt order:
  1. ids = `ChunkTokenization.Encode(text)` (`EncodeRaw(MarkUntrustedSpecials(text))`, contract ruling 21);
  2. fewer than `min_chunk_tokens` (default 32, server tokenizer) → `chunk_ignored_too_short` (warning only);
  3. **token check**: equal text is not equal tokens at a span's edges. The span counts only if its ids occur in the
     whole-prompt ids exactly where its characters are; otherwise `chunk_template_altered`. Catches BPE merges across
     a span edge, a SentencePiece leading space, and a Qwen3 assistant span holding a live `<think>` (located by the
     locator, rejected here). Linear in the prompt: with a proven token boundary after the previous span the glue is
     encoded alone and compared; otherwise the prefix is encoded and must be a prefix of the prompt's ids; prefix
     encodes are capped at 4 × the prompt length (+64 Ki chars), spans past the cap are ignored as unverified;
  4. store lookup (`IChunkStore.Contains`) under the server key in the caller's namespace (server-assigned; the
     default namespace until authentication, issue 14). A store failure is a miss.
- **`--chunk-store <dir>`**: the store to look chunks up in, **read-only** (never written, encoded into or created; the
  sole-writer encode path, budget and admission are issue 15). No store: every verified chunk is a miss. A configured
  root that does not exist: misses plus `chunk_store_unavailable` (strict: 503 `api_error`).
- **Response `chunk_cache` object** (spec §5.9, contract rulings 5–10; shapes pinned against the contract fixtures):
  on the blocking response (both surfaces), the OpenAI streaming **finish-reason chunk** beside `timings`, and the
  Anthropic `message_delta` beside `usage`. `chunks{annotated, prefix, hit, miss, ignored}` partition the annotations;
  `tokens` is `prompt = prefix_reused + prefilled` (nothing applied: chunk counters 0; `prefix_reused` =
  `cached_tokens`); `shadow` adds `plan` (selector `chunk_starts`, budget 0.2, its own partition,
  `predicted_ttft_ms`, `full_prefill_estimate_ms`); `timings_ms`; `warnings` merged per code across parser, locator
  and execution (ruling 38). `report: "none"` omits the object. `timings` gains `chunk_n` / `chunk_recomputed_n` (0) on
  annotated requests only.
- **Cost model** (`ChunkCostModel`, embedded `chunk-cost-model.json` with sources): Vulkan 16 µs per recomputed row ×
  visible key (G2), assembly and prefill from G1 / E1; prefill uses the request's measured rate when it has one.
  Provisional, calibrated in a later task.
- **`/metrics`**: `dotllm_chunk_cache_chunks_total{status}` and `dotllm_chunk_cache_tokens_total{kind}` (no namespace,
  text or hash in labels).
- **Strict errors**: parser defects right after request validation; after rendering, request-level first
  (`chunk_model_unsupported`, `chunk_policy_unavailable`, `chunk_store_unavailable`), then span-level. OpenAI: the usual
  body with `code` and `param: "chunk_cache"`. Anthropic: the usual envelope with a new optional `error.code` (ruling
  29; absent on every other error, so flag-off bytes are unchanged).
- **Never throws on request content**; an unexpected planning failure ignores every annotation and logs only the
  exception type. No chunk text, hash or namespace in reports, labels or logs.
- **Exact counters stay exact.** `cached_tokens` / `timings.cache_n` come from the prompt cache's exact lineage
  (snapshot lineage PR): an approximate snapshot on the slot is restored only up to its first approximate row.
- **Docs**: `docs/CHUNK_CACHE.md` (execution, report, metrics sections), `docs/SERVER.md` (both surfaces, flag table),
  `docs/TELEMETRY.md` (series).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; ships together with parsing and span location (Tasks 10, 11); `docs/SERVER.md`
      updated; `Closes #N` closed by hand.
- [ ] Every new flag documented and tested: `--chunk-store` (`ChunkStore_ParsedOnBothPaths`).
- [ ] Flag off, over real HTTP on a generating model: annotated bodies (valid, strict-defective, malformed) are answered
      exactly like the plain body on both surfaces, blocking and streaming (ids, timestamps and timing values blanked);
      nothing chunk-related appears.
- [ ] Flag on, `exact`: same generated tokens, usage and `cached_tokens` as the unannotated request on an identical
      server, cold and warm, blocking and streaming, on both prompt-cache paths (paged trie + scheduler; single-slot
      prefix cache) and both surfaces.
- [ ] Review focus: `exact` right after `shadow` on the same slot equals unannotated-after-unannotated (tokens and
      `cached_tokens`), blocking and streaming, both paths.
- [ ] An approximate prefix snapshot on the slot (rows after `r` from other tokens) is restored only up to `r`:
      `cached_tokens = prefix_reused = r` and the output equals a cold unannotated request.
- [ ] `shadow` with a store pre-filled (CPU encode) for half the chunks: hits and misses counted, chunk token positions
      verified against the prompt ids, plan partition and predictions; a chunk inside the restored prefix is `prefix`.
- [ ] A CLI-built store (`chunkcache build`) holding a chunk with `<think>` is a hit for the server (same key, index
      loads under the server identity).
- [ ] Token check: a span glued to the text before it where the tokenizer merges across the edge is
      `chunk_template_altered`; the same span after a newline is verified; a Qwen3 assistant span with a live
      `<think>` is rejected, the same text in a user message verified.
- [ ] `min_chunk_tokens`; `balanced` / `fast` / `auto` → `exact` with the reason, strict 400; unsupported model →
      `chunk_model_unsupported`; missing store → warning, strict 503 `api_error`; namespace is part of the key.
- [ ] Report shapes equal the contract fixtures' (keys and JSON kinds; `recompute` omitted; `reason` written as null);
      partitions hold.
- [ ] Report on the finish-reason chunk only (not on other chunks, not on the `include_usage` chunk) and on the
      Anthropic `message_delta`; `chunk_n` / `chunk_recomputed_n` present (0).
- [ ] `/metrics` counters move by exactly one request's report; no namespace in the exposition.
- [ ] Bounded work: 1,500 spans (half glued without a newline) cost ≤ 8 × the prompt length in tokenizer characters.
- [ ] No new `JsonSerializerContext`; the new response DTOs have no init-property initializers and are covered by
      `JsonContextDefaultsTests`.
- [ ] Correctness tests shown to fail against mutants (table below, also in the PR body).

## Mutant evidence

Run in a `git archive` copy (never the live worktree), `--filter FullyQualifiedName~Server.ChunkCache`, Release, CPU,
`DOTLLM_SKIP_VULKAN=1`. Baseline 191 / 191. **29 mutants, 29 killed** after two test additions (first runs: M14, M17, M21
survived and became tests in `32b11dab` and `2edc099e`; each then re-run and killed). Red evidence: a stub that plans
nothing and reports nothing (L0) fails 19 tests; with the pipeline still `NotImplementedException` and the endpoints not
wired, the 17 pipeline tests and every report test failed. The plan's three named mutants are M1 / M1b (shadow uses
segmented tokenisation: the token check accepts any located span), M2 (report omitted from the stream) and M3 / M3b
(misses counted in `chunk_reused`).

| mutant | change | killed by |
|---|---|---|
| L0 | `Prepare` plans nothing, `Finish` reports nothing | 19 (every report, HTTP and exchange test) |
| M1 | token check accepts the located index without comparing ids | `AssistantSpanWithThinkTag_VerifiedByIds`, `Warnings_MergedPerCode_…` |
| M1b | token check skipped (every span at token 0) | + `Shadow_PlanCountsHitsAndMisses`, `Span_TokenIdsDifferAtBoundary_…` |
| M2 | report omitted from the OpenAI stream | `StreamingFinalChunk_CarriesReport`, `Exact_IsBitIdenticalToUnannotated` (stream), `Exact_AfterShadow_…` (stream) |
| M3 | misses counted in the plan's `chunk_reused` | `Shadow_PlanCountsHitsAndMisses`, `Report_PartitionHolds`, `Shadow_OverHttp_…`, `Metrics_…`, 2 more |
| M3b | actual `tokens.chunk_reused` = planned reuse | `Report_PartitionHolds`, `Shadow_PlanCountsHitsAndMisses`, `Shadow_OverHttp_…` |
| M4 | chunk ids from bare `EncodeRaw` (unmarked) | `ShadowKey_ChunkWithThinkTag_HitsStoreEntryFromCli`, `AssistantSpanWithThinkTag_…`, `Warnings_…` |
| M5 | `min_chunk_tokens` ignored | `ShortChunk_IgnoredTooShortWarning` |
| M6 | `prefix` status never assigned | `Shadow_PlanCountsHitsAndMisses` |
| M7 | `balanced` / `fast` / `auto` without the reason | `Balanced_DegradesToExact_WithReason` (3), `StrictErrors_AreReturned_BothSurfaces` |
| M8 | reason set when `exact` is requested on an unsupported model (ruling 6) | `RecurrentModel_ModelUnsupported` |
| M9 | recurrent models not detected | `RecurrentModel_ModelUnsupported` |
| M10 | Anthropic `message_delta` without the report | `AnthropicMessageDelta_CarriesReport`, `Exact_IsBitIdenticalToUnannotated` (anthropic stream) |
| M11 | flag ignored at the OpenAI endpoint | `FlagOff_AnnotatedBodies_AnsweredLikePlain_EverySurface`, `FlagOff_OpenAi_AnnotatedBodyIsByteIdenticalToPlain` |
| M12 | prefix lineage cap ignored (approximate rows restored under `exact`) | `Exact_WithApproxSnapshotOnSlot_RestoresExactRowsOnly` |
| M13 | `prefix_reused` = the whole prompt | `Report_PartitionHolds`, `StreamingFinalChunk_…`, `Exact_WithApproxSnapshot…`, 2 more |
| M14 | strict: span-level defect wins over request-level | `Span_TokenIdsDifferAtBoundary_NotCountedReusable` (added after it survived) |
| M15 | unavailable store not reported | `MissingStoreRoot_Warns_StrictIs503`, `StoreUnavailable_MissesAndWarning_StrictIs503` |
| M16 | metrics not recorded | `Metrics_CountersIncrement` |
| M17 | hits recorded under `status="miss"` | `Metrics_CountersIncrement` (store hit added after it survived) |
| M18 | timings without `chunk_n` / `chunk_recomputed_n` | `CachedTokens_UnchangedByAnnotations`, `StreamingFinalChunk_…` |
| M19 | OpenAI 503 written as 400 | `MissingStoreRoot_Warns_StrictIs503` |
| M20 | token check: glue fast path removed | `TokenCheck_CostBound_ManySpans` |
| M21 | token check: prefix-encode cap removed | `TokenCheck_CostBound_ManySpans` (all-fallback case added after it survived) |
| M22 | Anthropic strict error without `error.code` | `StrictErrors_AreReturned_BothSurfaces` |
| M23 | `report: "none"` ignored | `ReportNone_OmitsObject` |
| M24 | identity keyed on the wrong backend tag | `ShadowKey_ChunkWithThinkTag_…`, `Shadow_PlanCountsHitsAndMisses` |
| M25 | recompute rows rounded down | `Shadow_PlanCountsHitsAndMisses`, `Shadow_OverHttp_…` |
| M26 | lookup ignores the caller namespace | `Lookup_UsesTheCallersNamespace`, `ShadowKey_…`, `Shadow_PlanCounts…`, `Shadow_OverHttp_…` |
| M27 | missing store root created instead of reported | `MissingStoreRoot_Warns_StrictIs503` |

Logs: `.superpowers/sdd/2026-11-01-phase-s/phase-i-task-13-mutants.log`; script `phase-i-task-13-mutate.py`.
