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
20. Span location in the rendered prompt compares against the marked span text or strips U+FDD0 from both sides (dotLLM marks untrusted special-token strings with U+FDD0, #1339). Spans altered by the template (Llama-3.1 trims user/assistant/system and JSON-encodes tool content) are ignored with the existing `chunk_ignored_template` warning: on Llama-3.1, tool-result spans are never reusable in v1; Qwen3 is fine.
21. Tokenisation of chunk text for the store AND for the wire path is `EncodeRaw(MarkUntrustedSpecials(text))`, which matches the chat path exactly; chunks are encoded the same way by the CLI/prewarm. Chunks whose text contains special-token strings therefore hash to the same chunk but encode as plain text, consistently on both sides.
22. Not our scope but to tell the maintainer: the OpenAI 400 for array content has an empty body instead of the usual error JSON.
