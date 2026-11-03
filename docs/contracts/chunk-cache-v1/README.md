# chunk-cache wire contract v1: golden fixtures

Shared contract for every Phase I lane (library, client, server, tooling). Source of truth is the spec
(`docs/superpowers/specs/2026-11-02-chunk-cache-integration.md`, section 5, rev 3). Each lane copies these files into its
own test project (dotLLM: `tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/`; the client's test project likewise) and a test
checks the copy against `fixtures.sha256`.

Check them here with `python -I docs/contracts/chunk-cache-v1/check.py` (`--update` rewrites `fixtures.sha256` after the
semantic checks pass; an optional folder argument checks a copy).

## Rules the fixtures pin

- Hash: `"sha256:"` + lowercase hex of the UTF-8 bytes of the **decoded** JSON string (escapes such as `é` are resolved
  first; CRLF, BOM, trailing whitespace all count). Spec 5.2, 5.3 item 1.
- Manifest `at`: `message` and `part` index the serialised `messages` and its `content` array (a string `content` is part 0);
  `start` / `end` are **UTF-8 byte** offsets into that part's text, end exclusive; omitted means the whole part. Spec 5.2.
- Inline and manifest placement in one request: warning `chunk_manifest_conflict`, served as unannotated; strict error.
  Spec 5.1.
- Errors: strict is `400 invalid_request_error` with a `code`; no 422. Spec 5.8.
- Response `chunk_cache`: `prompt = prefix_reused + prefix_reused_approx + chunk_reused + prefilled`, `chunk_recomputed <=
  chunk_reused`. `cached_tokens` / `cache_n` equal `prefix_reused` (exact rows only). Spec 5.9.
- Fixture files are stored byte-exact (`.gitattributes` disables line-ending conversion; the CRLF cases are escapes inside
  JSON strings, not file line endings).

## Files

| file | pins | spec |
|---|---|---|
| `inline.json` | placement A: two chunk-annotated tool-result parts with real hashes (`symbol-512`) | 5.1 A, 5.2 |
| `manifest.json` | placement B: `policy: shadow`, one whole-part span and one `start 0 / end 1830` span (1830 UTF-8 bytes, followed by glue in the same part) | 5.1 B, 5.2 |
| `conflict.json` | both placements in one request: warning and strict error `chunk_manifest_conflict`, zero spans accepted | 5.1, 5.8 |
| `nonascii-crlf.json` | escaped `é` and a surrogate pair (`😀`) before a span, so UTF-8 byte offsets differ from UTF-16 and char offsets; one whole-part CRLF chunk (its LF-normalised hash is different: a CRLF text must miss an LF-indexed entry) | 5.2, 5.3 item 1 |
| `bad-span.json` | four defective spans plus one valid: overlap (later span dropped), start inside a multi-byte character, part index out of range, non-text (`image_url`) part; all `chunk_span_invalid` | 5.2, 5.8 |
| `hash-mismatch.json` | a CRLF part hashed as its LF-normalised text: `chunk_hash_mismatch`, only that span dropped | 5.3 item 2, 5.8 |
| `response-blocking.json` | OpenAI blocking response under `exact`, with `usage`, `timings`, `chunk_cache` (prefix hit, one miss) | 5.9 |
| `response-stream-final.json` | final streaming chunk next to `usage` and `timings`, one `chunk_ignored_too_short` warning, `encode_queued` | 5.9 |
| `response-anthropic-delta.json` | Anthropic `message_delta` event with `chunk_cache` beside `usage`. Values are the spec's applied-reuse illustration (`auto` to `balanced`): Lane S does not emit them before Phase I5; clients must still parse them | 5.9 |
| `response-shadow.json` | `shadow`: applied `exact`, actual `tokens` identical to the unannotated request, predicted values under `plan` (own partition) | 5.5, 5.9 |
| `capabilities.json` | `GET /v1/chunk-cache` body | 5.9 |
| `expected.json` | each request fixture to its non-strict warnings, strict error (status, type, code), accepted span ids and defect list | 5.8 |

`check.py` is also a small reference implementation of the span validation: it recomputes every hash and offset, derives the
warnings from the requests and compares them with `expected.json`, and checks the response invariants above.

## Rulings on spec silence (controller, 2026-11-02; the spec should absorb these when next revised)

1. Overlap: the later span in manifest order is dropped; count 1.
2. A `chunk_cache` object with options only (no `chunks`) next to inline annotations is NOT a conflict.
3. An empty span (`start == end`) is `chunk_span_invalid`.
4. Several defects in one request: the strict-mode error code is that of the first defect in request document order (messages, then parts, then spans).
5. `chunks.annotated = prefix + hit + miss + ignored`; `hit` means "found in the store", whether or not reuse was applied (so `hit` is non-zero under `exact` and `shadow`).
6. `reason` is `null` when the applied policy equals the requested policy.
7. Under `shadow`, `plan` is `{selector, budget, tokens{same keys, own partition}, predicted_ttft_ms, full_prefill_estimate_ms}`.
8. `timings.chunk_n` equals `chunk_reused` (it does not include `prefix_reused_approx`).
9. Anthropic `message_delta` usage carries only `output_tokens` and `cache_read_input_tokens` (= `prefix_reused`).
10. Under `exact`, `recompute` is omitted and `timings_ms` is present with zeros.
11. `start == 0` and `end == len` are on-boundary.
12. Inline `v` is required; `chunk_not_wire_eligible` is covered by the server task's own tests, not by a fixture.
13. `chunk_ignored_too_short` is tokenizer-dependent and has no pinned request fixture.

## Rulings from the Task 6 review (controller, 2026-11-02)

14. Prewarm items may carry an optional `source` object (`{path}`), advisory only: the server applies its deny-list to `source.path` when present and can never rely on it (a client can omit it); the MCP schema lists `source`. The spec's prewarm item is `{id, text}` plus this optional field.
15. Explain request shape is pinned: `POST /v1/chunk-cache/explain` with body `{"request": <the chat request body>}`. `chunkcache select --server` uses the same shape.
16. Probe failure semantics: any exception or non-2xx from the capability probe (401, 403, 5xx, timeout, 404) means "strip annotations and send a plain request"; the client never sends `chunk_cache` unless the probe succeeded.
17. Lone surrogates in chunk text hash as UTF-8 with U+FFFD replacement (the default `Encoding.UTF8` behaviour); server and client must do the same; `check.py` uses the equivalent (`errors="replace"` on the surrogate-escaped form) if a fixture ever carries one.
18. The CLI must emit UTF-8 JSON on stdout (no console code-page dependence) and read the API key from an environment variable (`CHUNKCACHE_API_KEY`), never from the command line. List options with commas in values need a non-splitting form (repeatable option): Task 17 adds it; until then the client rejects commas in path globs.

## Rulings from the Task 9 server behaviour pin (controller, 2026-11-02)

19. v1 OpenAI surface: spans address string `content` only (the manifest form `chunk_cache.chunks[]` with message index + UTF-8 byte range). OpenAI array-of-parts content stays a 400 exactly as today; general array support is a separate, later issue (it changes responses for array bodies even with the flag off). The inline per-part `chunk` form is therefore Anthropic-only in v1 (text blocks), and part indices are mapped through the Anthropic converter ('\n' joins, tool_result splitting): the server task designs and tests that mapping.
20. Span location in the rendered prompt compares against the marked span text or strips U+FDD0 from both sides (dotLLM marks untrusted special-token strings with U+FDD0, #1339). Spans altered by the template (Llama-3.1 trims user/assistant/system and JSON-encodes tool content) are ignored with the existing `chunk_template_altered` warning: on Llama-3.1, tool-result spans are never reusable in v1; Qwen3 is fine.
21. Tokenisation of chunk text for the store AND for the wire path is `EncodeRaw(MarkUntrustedSpecials(text))`, which matches the chat path exactly; chunks are encoded the same way by the CLI/prewarm. Chunks whose text contains special-token strings therefore hash to the same chunk but encode as plain text, consistently on both sides.
22. Not our scope but to tell the maintainer: the OpenAI 400 for array content has an empty body instead of the usual error JSON.

## Rulings from the Task 10 server parser (controller, 2026-11-02)

23. Structurally malformed annotations (wrong JSON types, missing required fields, unknown `at` shape) use the new code `chunk_annotation_malformed` (400 `invalid_request_error` in strict mode, warning otherwise). Add it to the §5.8 code table in the next spec revision.
24. One defect is recorded per span: the first in this check order: structure, version, id, range/boundary, hash, overlap/conflict. `check.py`'s reference parser follows the same order.
25. `chunk_too_many`: the first N spans (document order) are kept; a request-level error wins over span defects in strict mode.
26. `chunk_not_wire_eligible` drops the span (warning; 400 in strict mode).
27. `id` length counts Unicode scalar values (not UTF-16 units); documented.
28. An unknown policy name maps to `chunk_policy_unavailable` (non-strict: served as `exact` with the warning; strict: 400).
29. Anthropic strict chunk errors carry the code inside the error object as `error.code` (an extension field: clients ignore it) in addition to the message; OpenAI errors use the existing `code`.
30. Annotating text inside an Anthropic `tool_result` content array is inline-only in v1 (the manifest `at` has no inner index); an optional `at.inner` may be added in a later contract version.
31. Engine message indices in the parsed model are counted BEFORE a profile system prompt is prepended; Task 11 adds the offset when a profile is active.
32. `chunk_namespace_ignored` (ruling from the Task 2 review): a body `namespace` differing from the caller's own is ignored with this warning (400 in strict mode); fixtures for it are to be added (controller TODO).

## Amendments from the Task 10 review (controller, 2026-11-02)

- **Ruling 24 (check order) is amended** to: structure, version, id, range/boundary, **overlap/conflict, then hash** (cheap structural checks first; hashing last bounds the cost of adversarial requests). `check.py`, the parser and `docs/CHUNK_CACHE.md` all follow this order.
- **Ruling 17 (lone surrogates)** applies to in-process callers only: over HTTP, System.Text.Json (.NET 10) refuses a string containing a lone-surrogate escape, so chunk text cannot contain one; a lone-surrogate escape in an annotation field (`id`, `hash`, `policy`, ...) is a malformed annotation (`chunk_annotation_malformed`), never a 500.
- **Ruling 4 (strict first defect)** is clarified: "document order" means inline annotations in (message, part) order and manifest entries in array order.
- Rulings 23 (`chunk_annotation_malformed`) and 26 (`chunk_not_wire_eligible` is strict-mode 400) stand and MUST be implemented; §5.8 of the spec lists both codes.
- Task 10 does not ship as a standalone PR: Tasks 10, 11 and 13 ship together (the flag must do something when merged).

## Rulings on the Task 10 fix round (controller, 2026-11-02)

33. Check order is: structure, version, id, eligibility (`chunk_not_wire_eligible`), range/boundary, overlap/conflict, hash. An ineligible span never reserves a range.
34. Unknown string values for `report` and `on_miss` are malformed (`chunk_annotation_malformed`: warning, strict 400) and the default is used otherwise; an invalid `query.message` is also malformed. (Task 11's first step brings the parser in line.)
35. `chunk_not_wire_eligible` drops the span (warning; strict 400), as in ruling 26.

## Rulings from Task 11 (controller, 2026-11-03)

36. A span whose text is not at its stated position in the rendered/received message is `chunk_span_invalid`; a span containing a caller-supplied U+FDD0 is `chunk_template_altered` (it cannot be reproduced after encode).
37. The locator's retry budget (4 sentinel renders per request) is a fixed internal constant in v1; exposing it as an option is deferred.
38. Task 13 merges the locator's warnings into the parser's list with per-code counts. Located character ranges are NOT proof of token equality: Task 13 verifies token ids over each located range before counting a span as reusable.

## Rulings from Task 13 (controller, 2026-11-03)

39. The read-only `--chunk-store <dir>` stays in the Task 10/11/13 PR (without a store `shadow` could only ever report misses).
40. Anthropic `usage.cache_read_input_tokens` is NOT added for annotated requests (usage must be identical to the unannotated request); the report lives in the `chunk_cache` object only.
41. `exact` on an unsupported model: `reason: null` plus a `chunk_model_unsupported` warning (ruling 6 prevails over the spec's §5.5 wording; the spec follows).
42. `chunk_policy_unavailable` appears in `reason` AND once in `warnings`.
43. The default shadow plan budget is 0.05 (as in the `response-shadow` fixture); a request's `recompute.budget` overrides it.
44. With no store configured, misses carry no warning; `GET /v1/chunk-cache` reports `store: false`.
45. `report: "per_chunk"` returns the summary until auth exists (Task 14).

## Rulings from the Task 13 review (controller, 2026-11-03)

46. `response-anthropic-delta.json` no longer carries `cache_read_input_tokens` (ruling 40 prevails; the field stays optional in `check.py`: if a server ever reports it, it must equal `tokens.prefix_reused`). Ruling 9 is amended accordingly.
47. Streaming placement: `chunk_cache` rides on the chunk that carries `timings` (dotLLM's final chunk, the one with the finish reason). `response-stream-final.json` shows a final chunk carrying both `usage` and the report; where a server emits `usage` on a separate trailing chunk, the report stays on the finish-reason chunk beside `timings`. Clients scan every event for `chunk_cache`.
48. `timings_ms.full_prefill_estimate` is an ESTIMATE of the unannotated prefill time (cost model, or the last measured full prefill of this model/backend if available), never simply the measured prefill of this request when reuse was applied; under `exact` (no reuse) it may equal `prefill`.
49. Spans that cannot be verified because the server's verification budget ran out are IGNORED with the warning `chunk_verification_skipped` (warning only, NEVER a strict-mode error); `chunk_template_altered` is reserved for spans actually found altered. The shadow plan counts them as ignored.
50. The default shadow plan budget is 0.05; `recompute.budget` in the request overrides it (ruling 43 stands).

## Rulings from Task 14 (controller, 2026-11-03)

51. Capabilities `model` may carry extra keys beyond `{id, supported, reason}` (`tokenizer_id`, `producer`, `quantization`, `backend`, `kv_dtype`, rope parameters, ...); `check.py` requires only that the three base keys are present. Clients ignore unknown keys.
52. Ruling 44 is amended: `store` in the capabilities response is ALWAYS an object (clients parse it as one); when no store is configured it is `{"configured": false, "entries": 0, "bytes": 0, "budget_bytes": 0, "dtype": "f32"}`; `configured` is optional (absent = unknown/true).
53. "Local caller" (no keys file) means loopback remote address AND a loopback/`localhost` Host header AND no `Origin` header (browser/DNS-rebinding protection); otherwise 403.
54. An inference request from a caller the control plane would refuse gets NO store lookups (summary report from parsing only); the annotation still never changes the output.
55. `per_chunk` shape is `[{id, status, why}]` with `why` a §5.8 code or null; explain is OpenAI-surface only in v1 and returns `counts` besides the chunk list.

## Rulings from Task 15 (controller, 2026-11-03)

56. Writer problems (`chunk_store_unavailable`, `chunk_encode_skipped`, ...) are WARNINGS only, never a strict-mode error: inference must never fail because of the store; strict errors are for request defects.
57. The optional `detail` field on a warning (e.g. `ledger_unreadable`, `budget_exhausted`, `lock_timeout`, `write_failed`) is an additive contract extension; clients ignore unknown fields.
58. Vulkan servers write nothing until Phase D settles how Vulkan K/V entries are versioned (shader/driver changes) and stored (compact rows).
59. A local caller without keys (authenticated=true under the loopback rule) may write through annotated inference requests, subject to `--chunk-store-write`.
60. Index-only mode accepts a key referenced by any index file in the store (as built).
61. Encode/queue limits stay fixed constants in v1; options are deferred.

## Rulings on the Task 15 fix round (controller, 2026-11-03)

62. A hung encode may keep the model alive until process exit (no forced abort); the owner lock is kept too.
63. The deny-list is a superset of ruling's list: `id_*` and `.git/**` stay; 8.3 short-name matching errs towards denying.
64. The per-namespace sighting share is a fixed quarter of the table (25,000); all writer limits are constants in v1 (ruling 61).

65. Background encode on CPU is capped at 512-token chunks (constant); larger chunks are refused at admission (`chunk_encode_skipped`, detail `too_large_for_cpu`). Measured on Qwen3-4B Q4_K_M, CPU, 8 threads: 512 tokens 8.35 s, 2048 tokens 43.5 s (so worst-case request wait ~8.4 s with the cap).

## Rulings from Task 16 (controller, 2026-11-03)

66. `path` forget removes stored entries/ledger rows/sightings/queued encodes the server owns and REPORTS (`kept_referenced`) entries still referenced by a CLI index; it never edits index files. `namespace`/`all` forget also delete that namespace's own index files (never legacy-named files or other namespaces').
67. Evict responses may carry extra output fields (`removed`, `warnings`); the MCP wrapper (Task 18) projects them out to fit the strict schema.
68. `orphans` and a store-wide `all` evict are admin-only.
69. The per-namespace budget counts only the server's ledger rows (documented); CLI-written offline entries are not counted.

## Rulings from I5 B2 (controller, 2026-11-03)

70. The engine's seeder hook trusts the in-process seeder's 'approximate from row N' tag (rows below N are stored as exact); the seeder is internal trusted code and this keeps exact reuse of leading glue; documented and pinned by tests.
71. Seed time stays out of the engine's PrefillTimeMs; the server (B3) adds seed + prefill for the reported prompt time.
72. The stale prefix-cache entry after a failed/cancelled plain request, and the fresh-cache leak on exception, are pre-existing engine bugs: candidates for a separate upstream issue (dotllm-97).
