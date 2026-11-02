# Library: wire-eligible chunking and chat-path chunk tokenisation (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Umbrella: `00-umbrella.md`, PR row 2 (library
> PR, Lane L Tasks 1-5; this draft is the Task 5 + 5b part and may be folded into the row-2 issue). Branch:
> `feature/chunk-wire` (local only, off `feature/chunk-cache` `bea84032`; merged into `feature/chunk-cache` by the
> controller; the library PR is cut fresh from `dev` later). Plan: Phase I Tasks 5 and 5b (spec §14 L6, §5.3 item 4;
> contract ruling 21).

**Suggested title:** `chunk-cache store: wire-eligible chunks, lines-512 chunker, chunk text tokenised as the chat path does`

## Body

The `chunk_cache` wire carries chunk **text**; the server tokenises it. A stored entry is only reachable from the wire when
the chunk's ids are exactly what the server computes from that text. Two things break that today:

1. **Token-id slices.** `FixedSizeChunker` slices one tokenisation of the whole file, and `SymbolChunker` slices an
   over-long single line. A slice can end inside a multi-byte character or a BPE merge, so its text need not re-tokenise to
   its ids (E4c: 2 / 3,972 on our corpora; not guaranteed in general).
2. **Special-token spellings.** `EncodeRaw` parses `<think>`, `<|im_start|>`, ... into control ids, while the chat path
   marks them (U+FDD0, #1339) and encodes them as plain text. A chunk containing one got ids, and a key, the server never
   computes.

What it adds (`DotLLM.ChunkReuse`):

- **`ChunkTokenization.Encode(tokenizer, text)`** = `EncodeRaw(MarkUntrustedSpecials(text))`, the only way library code
  turns chunk text into ids: every chunker (all size probes, ids and slices), `WireChunking.VerifyRoundTrip`, the CLI's
  build eligibility check and compare's query / continuation. Text without special spellings keeps its ids.
- **`Chunk.WireEligible` / `ChunkRef.WireEligible`** (default true). False for `SymbolChunker`'s over-long-line slices and
  every `FixedSizeChunker` chunk. `ChunkRef` JSON writes `"wireEligible": false` only when false; a missing field reads true
  (nullable carrier, per the source-generator `init` rule in dotLLM `CLAUDE.md`).
- **`WireChunking`**: `Eligible = {symbol-512}`, `PendingE4c = {lines-512}` (moves to `Eligible` in the follow-up that
  publishes it), `IsWireChunker`, `Hash` (`"sha256:"` + lowercase hex of UTF-8; a lone surrogate hashes as U+FFFD),
  `VerifyRoundTrip(chunks, textOf, tokenizer)`.
- **`LinesChunker`** (`lines-N`): the text-first fixed chunker, renamed from `TextFirstFixedChunker` / `fixed-text-N`
  (E4c's name). `ChunkRef.KindOfName("lines-*")` is `ChunkKind.Fixed`.
- **Index files** record `wireEligible` per chunk. An index written before this change: whole-line `symbol-*` files load
  as eligible and are re-chunked on the next `Update` even if unchanged (their keys may predate the tokenisation fix);
  token-slice and non-symbol files are dropped and re-chunked. Saving such an index before an update keeps it marked
  legacy.

**Compatibility.** Keys of chunks without special-token spellings are unchanged. Chunks with one get new ids, so a new key
(a miss, never a wrong hit); `KvOutputVersion` is unchanged. `ChunkIndex.FormatVersion` stays 1 (old files are recognised
by the missing field and refreshed). The API is unreleased.

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit --filter FullyQualifiedName~ChunkReuse` passes.
- [ ] `WireChunkingTests` (slices not eligible, round trip at a multi-byte cut, `Hash_MatchesFixtures` on the v1 contract
  fixtures, allow-list, JSON and index persistence incl. legacy indexes) and `ChunkTokenizationTests` (synthetic
  control-token vocabulary + guarded ChatML template; real Qwen3-4B-Instruct-2507 golden, skippable) pass.
- [ ] Contract fixtures copied byte-exact under `tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/`, checked against
  `fixtures.sha256`.
- [ ] Every correctness test shown to fail against a mutant (below).

## Mutant evidence

From `.superpowers/sdd/2026-11-01-phase-s/phase-i-task-5-report.md` (git-archive copies; full ChunkReuse filter per
mutant; log `phase-i-task-5-mutants.log`): **25 killed, 1 equivalent, 2 surviving (CLI, left to the CLI PR) = 28**.

- Killed: slices left eligible; hash over UTF-16; round trip compares lengths only; `lines-*` kind Other; JSON without the
  field reads ineligible; `ChunkRef.From` drops the flag; index never writes the flag; legacy entries not re-chunked; legacy
  symbol files with slices kept; legacy non-symbol files kept (after a test fix); legacy marker lost on Save; fixed slices
  eligible; `lines-512` on the allow-list; `IsWireChunker` = any `symbol-*`; unmarked `EncodeRaw` (7 tests incl. the real
  Qwen3 golden); `Encode` with BOS framing (after a test add); each chunker call site left on `EncodeRaw` (Symbol emit /
  pack / slices, Lines rest / probes / line-end / CRLF back-off, Fixed); `VerifyRoundTrip` on `EncodeRaw`.
- Equivalent: marking applied twice (marked text has no spelling left; the encoder strips every U+FDD0).
- Survived (CLI, no special spelling in the CLI test trees): build's eligibility check and compare's query on `EncodeRaw`;
  to be covered by the CLI PR (Task 17).
