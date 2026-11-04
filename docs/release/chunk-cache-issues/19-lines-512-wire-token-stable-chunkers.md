# Chunk cache: `lines-512` on the wire, and token-stable chunk edges (draft)

> **Status: DRAFT, not filed.** Phase I Task 19 (plan `docs/superpowers/plans/2026-11-02-phase-i-integration.md`, "Part A
> findings folded in"). Refs #1542 (umbrella). Our side files nothing and pushes nothing; the user decides when and whether it
> is filed.
> Branch: `feature/chunk-cache-server` (local, unpushed). Commits: `2fdfae4d` (chunkers), `6c3a2962` (allow-list, CLI,
> capabilities fixture), plus the docs / test commits after them. Squash with subject `... (#N)` once the issue number exists.
> Depends on: the library PR (chunkers) and the server wire PR (`ChunkCacheWire`, capabilities).

## Title

Chunk cache: accept `lines-512` on the wire; make `symbol-512` and `lines-512` cut only at token-stable edges

## Body

The first end-to-end run (e2e Part A, Qwen3-4B Q4_K_M, `experiments/e2e-chunkcache`) found that chunks shown back to back are
ignored by the server (`chunk_template_altered`): the tokenizer merges the last newline of one chunk with the blank line that
starts the next (`"\n" + "\n"` is one token), so the chunk's ids do not occur in the prompt at its position. The server's check
is right; the chunkers were the problem. This change makes the edges stable and also grants `lines-512` its wire eligibility.

- **`ChunkBoundary`** (`DotLLM.ChunkReuse.CodeCorpus`): an edge is token-stable when
  `Encode(left + right) == Encode(left) ++ Encode(right)` with `ChunkTokenization.Encode`; `IsStable` is the exact check,
  `IsStableAt` the windowed one the chunkers use (128 characters each side, no surrogate split).
- **`SymbolChunker`**: after chunking, an unstable edge between two wire-eligible chunks moves to the nearest stable line start,
  first later (the blank lines go to the previous chunk, so members stay whole; a chunk that is only blank lines joins the
  previous one), then earlier, and only where both chunks still fit the limit. Token-slice pieces of an over-long line are
  not wire chunks and are left alone.
- **`LinesChunker`**: the cut is the last **stable** line end that fits, else the last stable character cut (at most 256
  probes), else the old greedy cut (an edge that may merge; not seen on the corpora).
- **Allow-list**: `WireChunking.Eligible` = `lines-512`, `symbol-512` (`PendingE4c` is gone); the server's copy
  (`ChunkCacheWire.WireChunkers`, pinned equal by a test); capabilities `wire_chunkers` lists both (sorted) and
  `auto_validated` stays `[]` (`lines-512` is eligible on correctness; quality is Phase I5's gate). The CLI takes
  `--chunker symbol|fixed|lines`. The contract fixture `capabilities.json` changed and was re-copied (server and client tests).
- **Not changed**: the server's token check, `chunk_template_altered` semantics, the chunk size limit, determinism and the
  round-trip guarantee (0 failures on all three frozen corpora, both chunkers).
- **Join rule, documented not engineered.** Every chunk of both chunkers ends in a newline, so a chunk followed by a
  newline-starting joiner merges: the Anthropic converter joins the text blocks of one message with `"\n"`, so inline chunk
  blocks are all ignored (e2e A6). Clients use the manifest form over one string message (e2e A6m) or glue that does not
  start with a newline. The rule is contract ruling 75 and sits beside `chunk_template_altered` in `docs/CHUNK_CACHE.md` and
  `ChunkCacheCodes`. See "Decision" for why the chunkers do not try to avoid it.

### Evidence (Qwen3-4B tokenizer, three frozen corpora, edges counted within a file)

| | edges | unstable back to back, before | after | unstable under a `"\n"` join, after |
|---|---:|---:|---:|---:|
| `symbol-512` | 6,684 | 5,910 (88.4 %) | **0** | 6,659 (99.6 %) |
| `lines-512` | 2,542 | 0 | 0 | 2,534 (99.7 %) |

`symbol-512` chunk-id hashes moved (chunk counts did not): codesharp `364db68b…` to `3abfc1df…`, DocAgent `5d7e4560…` to
`f6865497…`, AFClaude `2601bb05…` to `54b3d4d1…`; `lines-512` and `fixed-512` hashes are unchanged. Symbol token totals now equal
one tokenisation of each file. Details and the re-pin list: `experiments/corpus.md`, "Re-pin after Phase I Task 19".

### Decision: newline-join stability is a client rule

Avoiding a trailing newline in the chunker is impractical: both chunkers cut whole lines (the chunk definition), 99.6 to 99.7 %
of left-hand chunks end in a newline, and ending a chunk before its newline only moves the merge to the start of the next chunk
(`"}" + "\n"` can merge too). It would also change nearly every chunk id. So the rule lives in the contract and the docs.

### Tests

`ChunkBoundaryTests` (36): `IsStable` and the join, `IsStableAt` window, lines (merging line end, no stable line end,
overlong line, blank-line edges), symbol (stable edges at four limits, blank line goes to the previous chunk, the limit is
never broken, the whole-next-chunk merge), a tokenizer with no stable edge (coverage, limit, determinism still hold). Allow-list:
`Lines512_IsWireEligible`, `Capabilities_ListLines512` (also `auto_validated` empty), `CliChunkerEnum_IncludesLines`,
`UnknownChunker_NotWireEligible_WarningAndStrict400` (lines-512 accepted), `Capabilities_MatchesFixtureShape`. Mutants (scratch
`git archive` copies) are listed in the Task 19 report.

### Open for the maintainer

- `lines-512` quality is unvalidated (Phase I5 non-inferiority margin); it is on the wire but never auto-selected.
- The MCP tool (Task 18) is not built yet, so its chunker enum is not touched here; it must list `symbol|fixed|lines` when it lands.
- Research experiments E3, E4, E4b, E7, G0, G2 were produced at the old `symbol-512` boundaries.
