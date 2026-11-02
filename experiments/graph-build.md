# Reference graph: build time and edge statistics (Task 9)

The Roslyn reference graph (dotLLM `src/DotLLM.ChunkReuse/Graph`: `RoslynGraphBuilder`, `ReferenceGraph`) over the three Task 8
corpora (`corpus.md`), with both chunkers. Lab command `ChunkKvLab graph-info`; script `graph-build/run.sh`; raw logs
`graph-build/<corpus>-<chunker>.log` (each starts with a provenance block).

## Provenance

- dotLLM worktree `feature/chunk-kv-reuse`, measured at **`7b5328e6`** (0 dirty files; review-fix round). Graph history:
  `2f717364` (implementation), `e2e311d9` (tests after mutation; `graph-info`), `1f418f2a` (extra statistics), `4e397207`
  (tests/doc), `7b5328e6` (`QueryEdges`, `CodeTask` file offsets, stricter mapping-mismatch check, query-edge split in
  `graph-info`). Edge sets are unchanged from the first run (same counts per corpus); only the mismatch count and the new
  query-edge lines differ.
- Snapshots: the Task 8 freezes (`t8-corpus-*` in the session scratchpad), verified by `--expect-hash` on every run:

  | corpus | source commit | symbol-512 hash | fixed-512 hash |
  |---|---|---|---|
  | codesharp `src` | `8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2` | `bf397403…df1fb` (pre-5b only, dotLLM ≤ `63d17b87`; now `364db68b…`) | `cde11b22…dceb` (pre-5b only; now `fb35a894…`) |
  | CSharpDocAgentFrameworkMCP `src` | `6683823880bc2a7d62708907c725d9eaedf3a016` | `5d7e4560…46c7` | `8d083a63…f2b4` |
  | AFClaude `src` | `b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c` | `2601bb05…a938` | `b90ef5fa…cbb6` |

- Tokenizer only (Qwen3-4B-Instruct-2507 Q4_K_M GGUF @ `ae44f08e`; no weights are run). CPU, Ryzen AI MAX+ 395, Windows 11 Pro
  10.0.26200, .NET SDK 10.0.401, Release build. 2026-11-01.

## What the graph contains

Edges run from the first character of a referencing name to the first character of a declaration name, mapped to chunk-local
token indices (the token holding that character, also when the name starts inside a token such as Qwen's `.Add`). Symbols are
resolved with one compilation over the corpus (BCL-only references, as Task 8); unresolved or ambiguous names give no edge.

- **Call**: invoked method name (also `x?.M()`), attribute name, or created type name when its constructor is declared in
  source → the method/constructor declaration (both parts of a partial method).
- **Use**: other references to types, fields, properties, events and method groups → the declaration (every part of a partial
  type or property). **Not** edges: locals, parameters, type parameters, range variables, labels, `var`, namespaces outside
  using directives.
- **Import**: using directive name → the namespace name in its ordinal-first declaring file (the type, for `using static` and
  aliases). One edge per directive, no fan-out. For `using A.B;` the use end is `A` and the definition end is `B`.
- **Definition**: a later declaration of a partial type/method/property → its ordinal-first declaration.

`EdgesForContext(ChunkedContext)` identifies context chunks by token content; a chunk whose content another chunk shares is left
unidentified (no edges). `EdgesForContext(ctx, chunks)` takes the chunks explicitly (by `Chunk.Id`) and has no such gap.
`QueryEdges(file, start, end)` returns the edges whose use starts in a character range of a file, with file offsets (for
queries; see below).

## Build time per 100K tokens

Three builds per run, each from scratch (new compilation, new semantic models, token mapping). Build 1 includes JIT warm-up.

| corpus | chunker | tokens | build 1 (cold) | builds 2, 3 | split of build 3: compile / bind / map |
|---|---|---:|---:|---:|---|
| codesharp | symbol | 1,535,738 | 0.902 s | 0.407, **0.262** s | 0.015 / 0.237 / 0.010 |
| codesharp | fixed | 1,530,303 | 0.959 s | 0.361, **0.249** s | 0.045 / 0.194 / 0.010 |
| DocAgent | symbol | 76,017 | 3.61 s | 1.78, 1.99 s | 0.017 / 1.926 / 0.048 |
| DocAgent | fixed | 75,636 | 4.23 s | 2.40, 2.17 s | 0.075 / 2.040 / 0.050 |
| AFClaude | symbol | 12,744 | 9.81 s | 1.53, 1.82 s | 0.109 / 1.679 / 0.036 |
| AFClaude | fixed | 12,687 | 15.95 s | 1.49, 2.08 s | 0.052 / 1.993 / 0.030 |

- On the large corpus a full build is **0.25–0.41 s per 100K tokens warm, 0.90–0.96 s cold**: 14–15 s for 1.5M tokens cold,
  3.8–6.3 s warm. Semantic binding is > 90 % of it; token mapping is ≈ 0.01 s per 100K tokens. (The first run at `1f418f2a`
  gave 0.21–0.39 warm / 0.73–0.90 cold: run-to-run variance is of this size.)
- Per-token cost differs a lot between corpora and is not explained. AFClaude's whole warm build (0.19–0.26 s absolute) bounds
  any fixed per-compilation cost (BCL metadata etc.) from above, yet DocAgent takes 1.35–1.81 s warm for 76K tokens, about 7×
  codesharp's cost per token. That gap is not a fixed cost; it was not investigated (a guess, unverified: DocAgent is a Roslyn
  analyzer project, so many names bind to unresolved Roslyn types, and error recovery may be expensive).
- Variance between warm runs is up to 2× (GC and tiered JIT); the numbers are wall times of single runs, not means.
- This is offline cost, paid once when chunks are encoded. The request-time lookup `EdgesForContext` costs 0.34–0.70 ms per 10K
  context tokens on the two larger corpora and 1.2–1.3 ms on AFClaude (not investigated; its runs have the fewest contexts,
  14–16).

## Edge statistics (E4 input)

The graph is chunker-independent (same edges in characters), so edge counts per corpus are identical for both chunkers; only
the chunk-crossing share changes.

| corpus | edges | per 1K tokens | Use / Call / Import / Definition | cross-file | cross-chunk, symbol-512 | cross-chunk, fixed-512 |
|---|---:|---:|---|---:|---:|---:|
| codesharp | 33,134 | 21.6 | 77.1 / 20.5 / 2.3 / 0.0 % (1 Definition edge) | 65.4 % | **98.7 %** | **92.5 %** |
| DocAgent | 3,772 | 49.6–49.9 | 85.1 / 12.9 / 2.0 / 0 % | 71.4 % | **93.7 %** | **86.5 %** |
| AFClaude | 514 | 40.3–40.5 | 82.9 / 16.9 / 0.2 / 0 % | 30.9 % | **71.0 %** | **59.3 %** |

Cross-chunk share per kind (symbol / fixed): codesharp Use 98.7 / 93.7 %, Call 98.7 / 87.3 %; DocAgent Use 92.7 / 85.9 %, Call
98.8 / 88.0 %; AFClaude Use 66.9 / 56.1 %, Call 90.8 / 74.7 %. Imports always cross (the using block and the namespace's first
declaration are in different chunks).

- Distinct use-end tokens: 2.1 % (codesharp), 4.8 % (DocAgent), 3.9 % (AFClaude) of all tokens; definition-end tokens 0.6 /
  1.2 / 2.1 %. The graph marks few tokens, which fits a small recompute budget.
- Symbol chunks keep **more** edges crossing than fixed 512-token chunks (their median is 105–157 tokens, 3–5× smaller, so a
  member's references to its siblings cross a boundary); fixed chunks keep more intra-chunk edges.
- Definition edges are essentially absent (partial types are rare outside generated code, which the loader excludes).
- Mapping mismatches (decoded chunk text ≠ file slice: a fixed chunk cut inside a multi-byte character): 3 chunks holding an edge
  end in DocAgent fixed-512, 0 elsewhere. (The first run counted 1: it compared lengths only, which misses a cut whose two
  halves each decode to one replacement character.)

### Inside the Task 8 contexts (what E4 will see)

Contexts are the Task 8 plans (`GeneratePlans`, default options: 2048-token budget, required chunk + seeded distractors,
calling files excluded), task budget 100, seed 0.

| corpus | chunker | contexts | chunks / context | cross-chunk edges (total; per 1K context tokens) | by kind (Use / Call / Import) | unidentified chunks |
|---|---|---:|---:|---:|---|---:|
| codesharp | symbol | 60 | 14.3 | **1**; 0.01 | 1 / 0 / 0 | 40 / 857 |
| codesharp | fixed | 52 | 8.7 | **2**; 0.02 | 1 / 1 / 0 | 18 / 453 |
| DocAgent | symbol | 48 | 16.9 | 183; 1.86 | 159 / 19 / 5 | 61 / 810 |
| DocAgent | fixed | 35 | 6.7 | 136; 1.91 | 122 / 7 / 7 | 0 / 235 |
| AFClaude | symbol | 16 | 17.4 | 226; 6.91 | 190 / 36 / 0 | 0 / 279 |
| AFClaude | fixed | 14 | 5.4 | 91; 3.28 | 71 / 20 / 0 | 0 / 76 |

- **On codesharp the Task 8 contexts have almost no edges between their chunks: 3 in total** (1 over 60 symbol contexts, 2 over
  52 fixed contexts). Distractors are drawn at random from 1390 files, so they rarely reference each other or the required chunk.
- Symbol chunking gives 1.6–3.2× more chunks per context than fixed-512 at the same 2K budget (14.3 vs 8.7, 16.9 vs 6.7, 17.4
  vs 5.4).
- Duplicate-content chunks are real: codesharp symbol-512 has 132 chunks in 43 groups (e.g. 15 identical `RiskClass =>`
  members), DocAgent 21 in 9 groups; fixed-512 only a tiny `    }\n}\n` tail (which the generator often uses to fill the budget).
  In these runs the explicit-chunk overload found exactly the same edges as the content match, but E4 should pass
  `plan.Chunks` (the explicit overload) anyway.

### Query → context edges

The query of a task is the calling file's text [`CodeTask.PrefixStartOffset`, `CodeTask.MaskStartOffset`) after a `// path`
header; the masked call spans [`MaskStartOffset`, + `MaskedText.Length`). Edges from the calling file into the context, from
`ReferenceGraph.QueryEdges`, split by where the use lies (100 tasks per corpus except AFClaude's 29; "req" = into the required
chunk):

| corpus | chunker | query prefix, per context (req) | per task (req) | masked call, per task (req) | elsewhere in the file, per task (req) | prefix edges Use / Call |
|---|---|---:|---:|---:|---:|---|
| codesharp | symbol | **0.37** (0.37) | 0.22 (0.22) | 1.00 (1.00) | 1.19 (0.55) | 12 / 10 |
| codesharp | fixed | **1.04** (1.00) | 0.54 (0.52) | 1.00 (1.00) | 1.41 (1.08) | 41 / 13 |
| DocAgent | symbol | **1.48** (0.46) | 0.71 (0.22) | 1.00 (1.00) | 8.52 (1.68) | 54 / 17 |
| DocAgent | fixed | **6.69** (5.00) | 2.34 (1.75) | 1.09 (1.06) | 22.43 (10.86) | 190 / 44 |
| AFClaude | symbol | **4.81** (0.88) | 2.66 (0.48) | 1.00 (1.00) | 32.31 (4.10) | 58 / 19 |
| AFClaude | fixed | **4.36** (3.07) | 2.10 (1.48) | 1.00 (1.00) | 24.90 (16.66) | 44 / 17 |

These match the reviewer's independent count for the prefix column. The first version of this record counted edges from the
**whole calling file** (3–36 per context); that included the masked call itself (≈ 1 per task, always into the required chunk:
the answer) and text outside the 256-token query window, so it overstated the usable structure. No prefix edge is an Import:
the using block is usually outside the query window.

## What Task 11 (E4) must do

1. **(a) Restrict query edges to the prefix and exclude the masked span.** Use `graph.QueryEdges(t.CallSitePath,
   t.PrefixStartOffset, t.MaskStartOffset)` — the range ends where the mask begins, so the masked call (the answer) is excluded.
   Counting the whole file, or the mask, lets the selector see the answer.
2. **(b) Map query uses by character offset into the query's own tokenisation.** `QueryEdge.UseOffset` is a file offset; the
   query token is the one covering `header.Length + (UseOffset − PrefixStartOffset)` in `t.PrefixTokenIds` (decode to find
   it). The calling file's chunk tokens (`ChunkEdge.UseToken`) do not carry over: the query is tokenised separately. The
   definition end is `(DefinitionChunk, DefinitionToken)`; keep edges whose chunk is in the context and offset the token by
   that chunk's context start.
3. **(c) Consider contexts built from related chunks.** Query-prefix edges are sparse on codesharp (0.37 per context with
   symbol chunks, almost all into the required chunk) and in-context edges are ≈ 0, so a graph selector there can only find the
   required chunk's definition tokens. Contexts drawn from a dependency neighbourhood (same namespace, files the calling file
   references) would give cross-chunk structure to rank; otherwise E4 on codesharp measures the distractor sampler.
4. Rank on Use and Call; Import is 0–0.1 per 1K context tokens and never in a query prefix, and Definition is absent.
5. Compare chunkers at equal budget (Task 8 concern 5): symbol chunks give 1.6–3.2× more chunks per context, and more edge
   crossings, for the same tokens.
