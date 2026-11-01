# Reference graph: build time and edge statistics (Task 9)

The Roslyn reference graph (dotLLM `src/DotLLM.ChunkReuse/Graph`: `RoslynGraphBuilder`, `ReferenceGraph`) over the three Task 8
corpora (`corpus.md`), with both chunkers. Lab command `ChunkKvLab graph-info`; script `graph-build/run.sh`; raw logs
`graph-build/<corpus>-<chunker>.log` (each starts with a provenance block).

## Provenance

- dotLLM worktree `feature/chunk-kv-reuse`, measured at **`1f418f2a`** (0 dirty files). Graph code: `2f717364` (implementation
  and tests), `e2e311d9` (tests strengthened after mutation; `graph-info`), `1f418f2a` (extra `graph-info` statistics only, no
  graph change).
- Snapshots: the Task 8 freezes (`t8-corpus-*` in the session scratchpad), verified by `--expect-hash` on every run:

  | corpus | source commit | symbol-512 hash | fixed-512 hash |
  |---|---|---|---|
  | codesharp `src` | `8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2` | `bf397403…df1fb` | `cde11b22…dceb` |
  | CSharpDocAgentFrameworkMCP `src` | `6683823880bc2a7d62708907c725d9eaedf3a016` | `5d7e4560…46c7` | `8d083a63…f2b4` |
  | AFClaude `src` | `b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c` | `2601bb05…a938` | `b90ef5fa…cbb6` |

- Tokenizer only (Qwen3-4B-Instruct-2507 Q4_K_M GGUF @ `ae44f08e`; no weights are run). CPU, Ryzen AI MAX+ 395, Windows 11 Pro
  10.0.26200, .NET SDK 10.0.401, Release build. 2026-11-01.

## What the graph contains

Edges run from the first character of a referencing name to the first character of a declaration name, mapped to chunk-local
token indices. Symbols are resolved with one compilation over the corpus (BCL-only references, as Task 8); unresolved or
ambiguous names give no edge.

- **Call**: invoked method name, attribute name, or created type name when its constructor is declared in source → the
  method/constructor declaration (both parts of a partial method).
- **Use**: other references to types, fields, properties, events and method groups → the declaration (every part of a partial
  type). **Not** edges: locals, parameters, type parameters, range variables, labels, `var`, and namespaces outside using
  directives.
- **Import**: using directive name → the namespace name in its ordinal-first declaring file (the type, for `using static` and
  aliases). One edge per directive, no fan-out.
- **Definition**: a later declaration of a partial type/method/property → its ordinal-first declaration.

`EdgesForContext(ChunkedContext)` identifies context chunks by token content; a chunk whose content another chunk shares is left
unidentified (no edges). `EdgesForContext(ctx, chunks)` takes the chunks explicitly (by `Chunk.Id`) and has no such gap.

## Build time per 100K tokens

Three builds per run, each from scratch (new compilation, new semantic models, token mapping). Build 1 includes JIT warm-up.

| corpus | chunker | tokens | build 1 (cold) | builds 2–3 | split of build 3: compile / bind / map |
|---|---|---:|---:|---:|---|
| codesharp | symbol | 1,535,738 | 0.727 s | 0.393, **0.214** s | 0.011 / 0.196 / 0.008 |
| codesharp | fixed | 1,530,303 | 0.901 s | 0.357, **0.251** s | 0.048 / 0.193 / 0.009 |
| DocAgent | symbol | 76,017 | 3.44 s | 1.69, 1.61 s | 0.015 / 1.570 / 0.027 |
| DocAgent | fixed | 75,636 | 3.39 s | 1.75, 2.35 s | 0.064 / 2.259 / 0.029 |
| AFClaude | symbol | 12,744 | 9.64 s | 1.68, 1.80 s | 0.113 / 1.652 / 0.033 |
| AFClaude | fixed | 12,687 | 10.46 s | 1.64, 1.98 s | 0.063 / 1.891 / 0.025 |

- On the large corpus a full build is **0.2–0.4 s per 100K tokens warm, ≈ 0.7–0.9 s cold**: 11–14 s for 1.5M tokens cold,
  3.3–6 s warm. Semantic binding is > 90 % of it; token mapping is < 0.01 s per 100K tokens.
- Small corpora cost more per token because each build pays a fixed BCL binding cost (≈ 0.2 s): absolute times are 0.2–0.25 s
  (AFClaude) and 1.2–1.8 s (DocAgent) warm.
- Variance between warm runs is up to 2× (GC and tiered JIT); the numbers are wall times of single runs, not means.
- This is offline cost (paid once when chunks are encoded; encoding the same tokens on CPU costs about three orders of magnitude more). The
  request-time lookup `EdgesForContext` costs **0.32–0.58 ms per 10K context tokens** on the two larger corpora (1.2–1.5 ms on
  AFClaude, whose 16 contexts are dominated by the first, JIT-cold call).

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
- Symbol chunks keep **more** edges crossing than fixed 512-token chunks (they are ~3–5× smaller, so a member's references to
  its siblings cross a boundary); fixed chunks keep more intra-chunk edges.
- Definition edges are essentially absent (partial types are rare outside generated code, which the loader excludes).
- Mapping mismatches (a fixed chunk cut inside a multi-byte character): 1 chunk (DocAgent fixed), 0 elsewhere.

### Inside the Task 8 contexts (what E4 will see)

Contexts are the Task 8 plans (`GeneratePlans`, default options: 2048-token budget, required chunk + seeded distractors,
calling files excluded), task budget 100, seed 0.

| corpus | chunker | contexts | chunks / context | cross-chunk edges per 1K context tokens | by kind (Use / Call / Import) | unidentified chunks | calling-file → context edges per context (into the required chunk) |
|---|---|---:|---:|---:|---|---:|---|
| codesharp | symbol | 60 | 14.3 | **0.01** | 1 / 0 / 0 in total | 40 / 857 | 3.1 (70.7 %) |
| codesharp | fixed | 52 | 8.7 | **0.02** | 1 / 1 / 0 in total | 18 / 453 | 4.3 (86.5 %) |
| DocAgent | symbol | 48 | 16.9 | 1.86 | 1.62 / 0.19 / 0.05 | 61 / 810 | 14.0 (24.3 %) |
| DocAgent | fixed | 35 | 6.7 | 1.91 | 1.71 / 0.10 / 0.10 | 0 / 235 | 34.3 (43.4 %) |
| AFClaude | symbol | 16 | 17.4 | 6.91 | 5.81 / 1.10 / 0 | 0 / 279 | 36.5 (10.8 %) |
| AFClaude | fixed | 14 | 5.4 | 3.28 | 2.56 / 0.72 / 0 | 0 / 76 | 26.7 (54.3 %) |

- **On codesharp the Task 8 contexts have almost no edges between their chunks** (2 edges over 52–60 contexts). Distractors
  are drawn at random from 1390 files, so they rarely reference each other or the required chunk. The structure that matters
  there runs from the **query** (the calling file's prefix) into the context (3–4 edges per context, 71–87 % of them into the
  required chunk). `EdgesForContext` does not see these, because the query is not a chunk.
- Duplicate-content chunks are real: codesharp symbol-512 has 132 chunks in 43 groups (e.g. 15 identical `RiskClass =>`
  members), DocAgent 21 in 9 groups; fixed-512 only a tiny `    }\n}\n` tail (which the generator often uses to fill the budget).
  In these runs the explicit-chunk overload found exactly the same edges as the content match, but E4 should pass
  `plan.Chunks` (the explicit overload) anyway.

## Implications for E4 (Task 11)

1. A graph selector limited to `EdgesForContext` has nothing to rank on codesharp-style contexts. Either add query → context
   edges (map the task's call-site file prefix through the graph: the query is a prefix of a corpus file, so its edges are
   already in `ReferenceGraph.Edges` as edges from the calling file's chunks), or build contexts from related chunks
   (same-namespace / dependency neighbourhoods) so that cross-chunk structure exists. Without one of these, E4 measures the
   distractor sampler, not structure.
2. Rank on Use and Call; Import is 0–0.1 per 1K context tokens and Definition is absent.
3. Compare chunkers at equal budget (Task 8 concern 5): symbol chunks give 2–3× more chunks per context, and more edge
   crossings, for the same tokens.
