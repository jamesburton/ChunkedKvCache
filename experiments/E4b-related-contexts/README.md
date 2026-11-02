# E4b — the E4 arms on related-chunk contexts (Phase S Task 1)

**Result in brief** (Qwen3-4B-Instruct-2507 Q4_K_M, CPU, 2K contexts, 58 valid instances from 17 call sites in 12
definition clusters, 3 seeds × 2 chunkers × 3 corpora; 95 % cluster-bootstrap CIs; full tables in `summary.md`):

- **The graph selector still does not beat query relevance (QR) at equal budget.** Both chunkers pooled, share of the
  naive→full masked-call NLL gap recovered, Graph − QR: **−0.10 [−0.19, −0.05] at 5 %** (a loss), +0.06 [−0.10, +0.31] at
  10 %, +0.02 [−0.17, +0.21] at 15 %, −0.02 [−0.20, +0.09] at 20 % (not distinguishable; the intervals admit losses up to
  0.20). With fixed 512-token chunks its point estimates are negative at every budget (−0.03 to −0.09), but the CI excludes 0
  only at 20 % (−0.08 [−0.35, −0.03]; 15 % is borderline, −0.08 [−0.39, +0.01]); with symbol
  chunks it loses at 5 % (−0.10 [−0.22, −0.03]) and is level with QR from 10 % (+0.09, +0.06, 0.00, CIs ∋ 0).
- **Hybrid(QR) (graph picks, then QR) is again the best runnable arm from 10 % up, but not significantly:** 0.87 / 0.90 / 0.94
  of the gap at 10 / 15 / 20 % against QR's 0.77 / 0.84 / 0.90 (Hybrid − QR +0.10 [−0.01, +0.34], +0.07 [−0.05, +0.23],
  +0.04 [−0.01, +0.12]; exact-match wins/losses 4/0, 4/1, 1/0), and **worse at 5 %** (−0.07 [−0.14, −0.02]). On fixed chunks
  it is within ±0.04 of QR at every budget (it mostly falls back to QR). Per seed it is not uniformly ≥ QR (related fixed
  seed 1 at 20 %: 0.96 vs 0.98; symbol seed 2: 0.94 vs 0.95).
- **Related contexts do carry more structure,** and the graph arm uses it: in-context cross-chunk edges per context 8.9 (median
  4) vs 6.1 (median 2) with symbol chunks and 5.0 (3) vs 2.1 (0) with fixed chunks; contexts without any such edge 30 % / 33 %
  vs 46 % / 58 %; valid instances whose query references a symbol declared in a stale context chunk 64 % vs 45 %; share of
  the graph arm's budget picked by the graph (not chunk-start fill) 54 / 31 / 20 / 15 % at 5 / 10 / 15 / 20 % vs 38 / 23 /
  16 / 12 %. **But no reliable change in the quality advantage is detectable:** on the 55 instances valid in both kinds
  (same task, chunker and seed), Hybrid − QR is +0.11 [−0.01, +0.37] / +0.09 [+0.01, +0.26] / +0.04 [−0.01, +0.13] at 10 /
  15 / 20 % on related contexts against +0.06 / +0.04 / +0.06 on random ones, and Graph − QR +0.06 / +0.04 / +0.01 against
  +0.04 / +0.01 / 0.00. Those are two separately bootstrapped sets; the reviewer's paired difference-in-differences (related
  minus random, one shared cluster resample, 1000 reps; not in `summarize.py`) gives Hybrid − QR +0.05 [−0.01, +0.23] at
  10 %, +0.045 [+0.01, +0.15] at 15 %, −0.02 [−0.05, +0.01] at 20 %, and Graph − QR intervals that all include 0 (+0.03,
  +0.03, +0.01). The point estimates move by −0.02 to +0.05, one of six intervals clears 0 and the sign flips at 20 %; the
  intervals still admit gains up to ≈ 0.2, so a small benefit of related contexts for the graph is not ruled out.
- **Where the graph signal helps:** only where the query has targets (n = 37, 9 clusters): Hybrid − QR +0.15 [−0.02, +0.48] at
  10 % (EM 4/0), +0.09 at 15 %, +0.06 [−0.02, +0.17] at 20 %, Graph − QR +0.12 [−0.07, +0.46] at 10 %, all n.s., and both lose
  at 5 % (−0.11 [−0.21, −0.03]). Without targets (n = 21) the graph has little to pick (graph picks ≈ 10 % of the budget at
  10 %) and falls back to chunk-start fill: Graph ≈ ChunkStarts at every budget (10 %: 0.849 vs 0.848 of the gap), so its
  −0.08 [−0.15, −0.04] against QR at 10 % is chunk starts trailing QR, not the graph tiers costing anything. Hybrid equals QR
  there.
- **Chunk starts are again close to the best** from 15 % (0.85 / 0.89 of the gap; the best baseline at 15 % pooled), and the
  definition-window ORACLE + fill is the ceiling at 5 % (0.84 vs ChunkStarts 0.61 and QR 0.76), +0.00 over QR at 20 %.
- **95 % / 20 % bar** (EM ≥ 0.95 × full at ≤ 20 %): fixed chunks QR and Hybrid 0.96 (met as a point estimate, 28 instances /
  10 clusters); symbol chunks best runnable 0.93 (ChunkStarts; QR 0.87, Hybrid 0.90): not met; pooled 0.93: not met.

**Answer to the task question: no.** On contexts drawn from the calling file's dependency neighbourhood, neither Graph nor
Hybrid(QR) beats query relevance at equal budget with a CI that excludes 0 in the pooled sets; Graph loses at 5 % (the one
robust pattern: negative in every subset and both chunkers) and its fixed-chunk estimates are negative (CI below 0 at 20 %
only); Hybrid is ahead by +0.04 to +0.10 from 10 % (point estimates slightly larger than on random contexts) and
behind at 5 %. E4's conclusion stands for related contexts: the reference graph is at best a small add-on to query relevance,
not a replacement.

No figure: the numbers are in the tables below and in `curves.csv` (sets `related-valid|<chunker>|pooled`, and the random
control `random-valid|…`).

## Why

E4 (`../E4-structure-aware`) found that the reference-graph selector does not beat QR at equal recompute budget, but its
contexts were the required definition chunk plus **random** distractors, the worst case for a graph: random chunks have
few edges between them (codesharp: none in any symbol context) and the query references a symbol in a stale chunk in only
45 % of instances. E4b repeats the core arms on contexts built from the calling file's **dependency neighbourhood**, where a
retrieval system would draw its context from and where structure-aware selection should be strongest.

## What changed against E4

Only the contexts. Same kept Task 8 call sites, same grouping into contexts (by required chunk, up to 4 tasks), same
seed- and chunker-independent context order (hash of the first task id), same arms, budgets, evaluation and statistics
(E4's `summarize.py` functions are imported, and the E4 rows in `../E4-structure-aware/results.csv.gz` are the random-context
control). One difference in validation: the random symbol/seed-0 instances (23 of E4's 88) have no `drop_required` row and
are accepted on Task 8's earlier validation plus a full-prefill EM recheck, whereas every related cell is re-validated with
`drop_required` in its own context.

**Context builder** (dotLLM `src/DotLLM.ChunkReuse/Corpus/RelatedContextBuilder.cs`, `e4 --context-kind related
--related-fraction 0.5`):

- **Neighbourhood**: files within two hops of the calling file(s) along directed use → definition edges of the Task 9
  Roslyn reference graph (kinds Use, Call, Definition). Hop 1 = files the calling file references anywhere in its text
  **except the masked call itself** (edges whose use lies in the masked span are dropped, so the answer never chooses the
  neighbourhood); hop 2 = files the hop-1 files reference. `using` directives are **not** followed (they point at whichever
  file declares a namespace first, not at a dependency). Calling files are never part of it. For a context with several
  tasks the neighbourhood is the union over their calling files.
- **Filling**: the required chunk(s), then distractors one at a time, a related one (hop-1 files' chunks in a seeded order,
  then hop-2 files') while fewer than `0.5 × (chosen + 1)` are related, otherwise a random one from outside the
  neighbourhood; a chunk that no longer fits is skipped, and when one pool has nothing that fits, the other fills the 2K
  budget. While both pools still hold a chunk that fits the remaining budget, the related count is within one chunk of half
  the distractors (counted in chunks, not tokens). The final chunk order is a seeded shuffle.
- **Leak filters** (equivalent to the task generator's on these corpora, applied to both pools; the callee name is read from
  the masked text, which starts with `.` or a letter in all 229 masked texts here): no chunk of a calling file, no chunk declaring a member or
  type named like the callee, no chunk containing a masked call's text.
- **Re-validation in every cell** (`drop_required` in every job, including symbol/seed 0, whose Task 8 contexts are not
  reused): a task is valid in a context when full prefill reproduces the masked call, the context without the required chunk
  does not, and the masked NLL falls by ≥ ln 2.
- Seed per context = run seed × 1 000 003 + the first 28 bits of SHA-256(first task id).

In practice the hop-1 ring was large enough that hop-2 chunks were almost never drawn (related distractors per context
8.2 symbol / 3.4 fixed, of which hop 1: 8.2 / 3.4), and **only DocAgent sits at the nominal 50 %**. Mean related share of
the distractors per context (`contexts.csv`):

| corpus | fixed | symbol |
|---|---|---|
| AFClaude | 0.80 (3 of 7 contexts at 1.00) | 0.78 |
| codesharp | **0.38** (0.22–0.50; up to 2.5 chunks below half) | **0.47** (1 chunk below half in 3 contexts) |
| DocAgent | 0.54 | 0.51 |

AFClaude (9 files) runs out of outside chunks, so related chunks fill; codesharp runs out of related chunks that fit the
remaining budget, so random chunks fill. Codesharp is also the corpus whose symbol contexts still have no in-context edge in
55 % of cases.

**Arms** (as E4): `full` (reference), `naive`, `drop_required` (validity), `chunk_starts`, `query` (ProphetKV-like QR, query =
the task's ≤ 256-token prefix), `graph` (`GraphSelector`: query targets, target chunk starts, in-context edges, imports, then
chunk-start fill), `hybrid_query` (graph picks, then QR), `oracle_def_fill` (ORACLE: the masked callee's 16-token
definition window, then chunk-start fill; 5 and 20 % only). Budgets 5 / 10 / 15 / 20 % of the context, equal across arms.
FirstK, Deviation, Random and the other oracles were not rerun (E4 placed them; they are not the comparison asked for).

## Tables (pooled corpora; valid instances)

Share of the naive→full masked-call NLL gap recovered (ratio of means) [95 % cluster-bootstrap CI]:

| arm | related 5 % | 10 % | 15 % | 20 % | random (E4) 5 % | 10 % | 15 % | 20 % |
|---|---|---|---|---|---|---|---|---|
| ChunkStarts | 0.61 [0.07, 0.87] | 0.65 [0.20, 0.87] | 0.85 [0.70, 0.90] | 0.89 [0.78, 0.93] | 0.65 | 0.70 | 0.78 | 0.83 |
| QR | 0.76 [0.47, 0.91] | 0.77 [0.44, 0.94] | 0.84 [0.62, 0.96] | 0.90 [0.79, 0.98] | 0.73 | 0.74 | 0.83 | 0.86 |
| **Graph** | 0.66 [0.33, 0.84] | 0.82 [0.68, 0.89] | 0.86 [0.74, 0.91] | 0.88 [0.75, 0.92] | 0.61 | 0.71 | 0.80 | 0.83 |
| **Hybrid(QR)** | 0.69 [0.36, 0.86] | 0.87 [0.75, 0.93] | 0.90 [0.82, 0.96] | 0.94 [0.90, 0.98] | 0.63 | 0.78 | 0.87 | 0.90 |
| ORACLE def + fill | 0.84 [0.74, 0.92] | | | 0.90 [0.82, 0.95] | 0.80 | | | 0.87 |

Related: n = 58 instances / 12 clusters (symbol 30 / 11, fixed 28 / 10); random: E4's 75 / 14. The two columns are
different instance sets (re-validation keeps different tasks); the paired cross-kind comparison is the matched set below.
Naive concatenation is less harmful on related contexts: naive EM 0.53 vs 0.35 (E4 pooled), masked-call NLL 2.24 vs 3.39
nats above full prefill; full EM 1.00 by construction. A smaller gap also makes the gap ratios noisier.

Paired differences, arm − QR, gap recovered [95 % CI] (`pairs.csv`):

| set (n / clusters) | arm | 5 % | 10 % | 15 % | 20 % |
|---|---|---|---|---|---|
| related, both (58 / 12) | Graph | **−0.10 [−0.19, −0.05]** | +0.06 [−0.10, +0.31] | +0.02 [−0.17, +0.21] | −0.02 [−0.20, +0.09] |
| | Hybrid(QR) | **−0.07 [−0.14, −0.02]** | +0.10 [−0.01, +0.34] | +0.07 [−0.05, +0.23] | +0.04 [−0.01, +0.12] |
| related, symbol (30 / 11) | Graph | **−0.10 [−0.22, −0.03]** | +0.09 [−0.12, +0.35] | +0.06 [−0.17, +0.26] | +0.00 [−0.21, +0.12] |
| | Hybrid(QR) | **−0.08 [−0.17, −0.00]** | +0.13 [−0.02, +0.39] | +0.09 [−0.07, +0.27] | +0.05 [−0.01, +0.14] |
| related, fixed (28 / 10) | Graph | −0.09 [−0.23, +0.01] | −0.03 [−0.18, +0.10] | −0.08 [−0.39, +0.01] | **−0.08 [−0.35, −0.03]** |
| | Hybrid(QR) | −0.04 [−0.22, +0.07] | −0.00 [−0.03, +0.03] | −0.00 [−0.01, +0.01] | −0.01 [−0.05, +0.00] |
| related, query targets > 0 (37 / 9) | Graph | **−0.11 [−0.22, −0.03]** | +0.12 [−0.07, +0.46] | +0.05 [−0.22, +0.29] | −0.03 [−0.30, +0.13] |
| | Hybrid(QR) | **−0.11 [−0.21, −0.03]** | +0.15 [−0.02, +0.48] | +0.09 [−0.10, +0.31] | +0.06 [−0.02, +0.17] |
| related, no targets (21 / 8) | Graph | **−0.07 [−0.21, −0.00]** | **−0.08 [−0.15, −0.04]** | −0.04 [−0.15, +0.04] | −0.01 [−0.09, +0.03] |
| | Hybrid(QR) | +0.01 [−0.00, +0.05] | −0.00 [−0.02, +0.00] | +0.01 [−0.00, +0.06] | −0.00 |
| matched, related contexts (55 / 11) | Graph | **−0.09 [−0.17, −0.03]** | +0.06 [−0.10, +0.33] | +0.04 [−0.09, +0.23] | +0.01 [−0.10, +0.11] |
| | Hybrid(QR) | −0.05 [−0.12, +0.01] | +0.11 [−0.01, +0.37] | **+0.09 [+0.01, +0.26]** | +0.04 [−0.01, +0.13] |
| matched, random contexts (55 / 11) | Graph | −0.06 [−0.14, +0.04] | +0.04 [−0.04, +0.11] | +0.01 [−0.07, +0.09] | +0.00 [−0.12, +0.10] |
| | Hybrid(QR) | **−0.07 [−0.12, −0.00]** | +0.06 [−0.01, +0.15] | +0.04 [−0.01, +0.12] | +0.06 [−0.01, +0.16] |
| random (E4, 75 / 14) | Graph | **−0.12 [−0.20, −0.03]** | −0.03 [−0.09, +0.01] | −0.03 [−0.06, +0.00] | −0.03 [−0.12, +0.04] |
| | Hybrid(QR) | **−0.10 [−0.18, −0.03]** | +0.04 [−0.01, +0.11] | +0.04 [−0.00, +0.09] | +0.04 [−0.01, +0.11] |

About 60 paired cells are reported here (more in `pairs.csv`) with no multiplicity adjustment. They are correlated through
nested subsets (symbol + fixed = both, targets + no targets = both, matched ⊂ both), so they are not 60 independent looks,
but an isolated CI that just clears 0, on either side, is expected by chance. The positive CIs that clear 0 are matched
Hybrid − QR at 15 % and Graph − ChunkStarts at 10 % (below); outside the 5 % column the negative ones are fixed Graph at
20 % and the no-targets Graph at 10 % (chunk-start fill, see above). Against ChunkStarts (the best baseline at 15 % pooled), Graph is +0.01 [−0.02, +0.05] and Hybrid +0.05
[−0.00, +0.17] at 15 %; Graph − ChunkStarts at 10 % is +0.17 [+0.01, +0.53], driven by a weak ChunkStarts on symbol seed 1
(0.21).

Masked-call exact match at 20 % (full = 1.00): related pooled ChunkStarts 0.93, QR 0.91, Graph 0.90, Hybrid 0.93, oracle
0.90, naive 0.53; fixed QR / Hybrid 0.96; symbol ChunkStarts 0.93, QR 0.87, Graph / Hybrid 0.90. Post-query KL at 20 %
(Hybrid / QR / ChunkStarts / Graph): 0.049 / 0.052 / 0.064 / 0.065 nats.

Per seed (`summary.md`, "Per chunker and seed"): related symbol seeds 0 / 1 / 2 at 20 %, QR 0.88 / 0.82 / 0.95, Graph 0.94 /
0.87 / 0.74, Hybrid 0.89 / 0.96 / 0.94; fixed QR 0.98 / 0.98 / 0.94, Graph 0.86 / 0.87 / 1.00, Hybrid 0.98 / 0.96 / 0.94.
The QR-vs-Graph order changes with the seed on symbol chunks, as in E4.

## Validity and structure

| | related | random (E4) |
|---|---|---|
| instances run / valid | 74 / 58 (0.78) | 88 / 75 (0.85) |
| valid instances with a query target | 0.64 | 0.45 |
| in-context cross-chunk edges per context, symbol (mean, median; share with none) | 8.9, 4; 0.30 | 6.1, 2; 0.46 |
| same, fixed | 5.0, 3; 0.33 | 2.1, 0; 0.58 |
| graph share of the graph arm's budget at 5 / 10 / 15 / 20 % | 0.54 / 0.31 / 0.20 / 0.15 | 0.38 / 0.23 / 0.16 / 0.12 |
| same, instances with a query target | 0.73 / 0.42 / 0.28 / 0.21 | 0.66 / 0.42 / 0.29 / 0.22 |

Per corpus (`summary.md`, "Structure per context"): codesharp gains the most edges with fixed chunks (5.8 vs 0.1) but
symbol codesharp contexts still have none in 55 % of cases (median 0); DocAgent symbol contexts rise to 15.0 edges.

Validity drops mainly because **full prefill misses the masked call more often in a neighbourhood context**: of the 16
invalid related instances, 11 fail because full prefill does not reproduce the call (full EM 0.50–0.86 in ten of 18 cells;
E4: 5 of 88) and 5 because the context without the required chunk already solves it (E4: 8 of the 65 instances with a
`drop_required` row); none fails on the NLL margin alone. A hypothesis, not measured: related distractors are plausible
competitors (similar names and signatures) that confuse even full prefill; likewise, related contexts may hold other call
sites of the same callee (not filtered, as in the generator), a candidate reason for the lower naive harm. The related-valid set is therefore selected toward instances the model still
solves in a crowded neighbourhood; it is not a random sample of "related" instances.

## Run

Job queue `jobs.csv` (one E4 random context rerun as a reproduction check, then 18 related jobs: 3 corpora × {symbol,
fixed} × seeds 0–2 with E4's per-cell context counts 6 / 4 / 3 / 2 and time caps 30 / 25 / 20 / 13 min), driver `run.ps1`
(2 jobs in parallel × 16 threads; provenance block written when each job starts; start times in `logs/queue.log`).
dotLLM `20b4da78` (0 dirty files in all 19 job logs), Release, CPU `TransformerModel`, F32 `SimpleKvCache`;
`bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` @ `ae44f08e1392f39c0e474af10c3ff8355c8b6688` (Q4_K_M, 2,497,280,736 bytes); AMD
Ryzen AI MAX+ 395, Windows 11 Pro 10.0.26200, .NET SDK 10.0.401; corpora = the Task 8 snapshots with their chunk-id hashes
enforced (`../corpus.md`). **Total 246.2 min wall** (over the ≈ 3 h budget). By the implementer's account (not recorded in
the logs) the mutation builds ran concurrently with the early part of the queue, so wall times and per-arm timings from that
period are inflated. **The time caps truncated 8 of the 18 related cells** (contexts run / planned): AFClaude fixed s0 3/4,
symbol s0 3/6, symbol s1 2/3; codesharp symbol s2 2/3; DocAgent fixed s0 3/4, fixed s1 1/2, symbol s0 4/6, symbol s2 2/3.
Truncation keeps a prefix of the same seed- and chunker-independent context order, so truncated cells hold a subset of
E4's definitions.

**Reproduction check:** the random-kind rerun of E4's codesharp / fixed / seed 1 context 0 at `20b4da78` matches E4's 21 rows
exactly (max |Δ| = 0 for masked NLL, EM, KL, budget, graph picks, forward calls), so the new flag leaves the random path
unchanged and E4's rows are a valid control.

**Speed checkpoint:** this task adds no runtime path (it changes only which chunks form a context). Selection costs as in
E4: graph 0.12 ms median; recompute on the run-per-`Forward` path at 20 %: graph 14 forwards / 10.2 s, QR 184 / 26.9 s,
ChunkStarts 8 / 8.9 s (relative CPU costs, possibly inflated by the shared CPU as above; QR's probe 20.5 s median, lab
code).

**Tests** (dotLLM `tests/DotLLM.Tests.Unit/ChunkReuse/RelatedContextBuilderTests.cs`, 7 tests): written first (build failed
with CS0103 `RelatedContextBuilder`), then green; ChunkReuse suite 236/236. The plan's five tests
(`Related_RequiredChunkAlwaysIncluded`, `Related_FractionRespected_WithinOneChunk`,
`Related_NoChunkFromOutsideTwoHopsUnlessFilling`, `Related_SameSeed_SameContext`, `Related_MaskedTextNeverInContext`) plus
`Related_Neighbourhood_IsTwoHopsOfUseEdges_WithoutImportsOrTheMaskedCall` and
`Related_LeakFiltersApplied_CallingFileAndSameNameDeclarations`. Mutation: 21 mutants of `RelatedContextBuilder` (masked
edges followed, 1 / 3 hops, imports followed at hop 1 / hop 2, fraction ignored or biased, seed ignored, each leak filter
dropped, required chunk omitted, no fill, hop order reversed, calling file in its own neighbourhood, required-chunk check
dropped, no final shuffle, budget overrun, union of calling files dropped, hop distance rewritten), run in a `git archive`
scratch copy (never the live worktree while jobs ran): 17/21 killed in round 1; the 4 survivors (hop-2 imports, calling
file self-edges, unshuffled order, hop rewrite) are killed by fixture and assertion changes; 21/21 in round 2 (dotLLM
`70112a05`, applied after the jobs finished). The `e4` lab command itself has no unit test (as in E4).

## Caveats

- **Small, clustered samples**: 58 valid instances from 17 call sites in 12 definition files; per-corpus cells have 2–6
  clusters. Only pooled statements are worth reading; per-corpus tables are in `summary.md`.
- **Selection by re-validation** (above): related contexts lose 22 % of instances, not at random (mostly full-prefill misses).
- **Hop 2 is barely exercised** (hop-1 files filled the related half), and the related share is off nominal on two corpora
  (AFClaude ≈ 0.8, codesharp 0.38 fixed / 0.47 symbol; table above). A "neighbourhood" is a property of these three repos.
- **Hop 1 reads the whole calling file**, including text after the call site that the model never sees (a retrieval setting
  where the editor has the file); the masked-span exclusion drops every edge inside the masked call, arguments included.
- **Same call sites, different contexts**: the cross-kind comparison pairs (task, chunker, seed) across two different
  context draws; the matched set controls for task mix, not for context length or chunk count.
- **Time caps** truncated 8 of 18 cells, so the related and random sets do not cover exactly the same definitions (the
  matched set does). Random symbol/seed 0 uses Task 8's validation, related cells their own (see "What changed").
- **Test gaps**: the unit fixture uses the symbol chunker only (9 of 18 jobs used fixed chunks; the builder is
  chunker-agnostic by construction), and the `e4 --context-kind related` wiring (`PlanSeed`, the `--mode kept` guard, the new
  CSV columns, the neighbourhood counts) has no unit test; the reproduction check covers only the random path.
- One model, 2K contexts, one fixed token set for all layers, one `Forward` per contiguous run (as E4).

## Files

| file | content |
|---|---|
| `run.ps1`, `jobs.csv` | job queue and driver (provenance block per log, chunk-id hash enforced) |
| `raw/*.csv` | the per-job CSVs written by `ChunkKvLab e4` (18 related jobs + the random reproduction) |
| `summarize.py` | merges `raw/` with E4's `results.csv.gz` → `results.csv.gz`, `curves.csv`, `pairs.csv`, `contexts.csv`, `summary.md` (`uv run summarize.py`; default input `raw/`; regenerates the committed `summary.md`, `curves.csv`, `pairs.csv`, `contexts.csv` byte-identically) |
| `results.csv.gz` | every row (related E4b rows + E4 random kept rows), with `context_kind`, `related_chunks`, `hop1_chunks` |
| `curves.csv`, `pairs.csv` | per set × chunker × corpus × arm × budget curves; paired differences with CIs |
| `contexts.csv` | one row per context: chunks, related / hop-1 distractors, in-context edges, query targets, valid tasks |
| `logs/*.log` | job logs (force-added) and `queue.log` |
