# E2 — baseline recompute selectors: quality versus budget (gate G1)

**Result in brief.** Model and setup: Qwen3-4B-Instruct-2507, CPU, code chunks, 3 seeds; 2K/4K with all selectors, 8K with the best two.
The headline metric is KL on the **post-query rows** (16–63). Rows 0–15 are the 16 query tokens the query-relevance selector was
built from (see "Query").

- Every structured selector removes about half (2K) to 60 % (4K) of the naive-concatenation KL with only 5 % of the tokens recomputed.
  Random selection removes almost none.
- **ProphetKV-style query relevance is the best selector from 10 % budget up at 4K and 8K, and at 15–20 % at 2K.**
  - Post-query, it removes 80 % / 83 % of the naive KL at 20 % at 2K / 4K. Layer-1 deviation removes 71 % / 60 %.
  - At 8K (3 seeds) query removes 97 %, against 82 % for deviation.
  - At **2K 5 % it is the worst structured selector post-query**: 0.066 against 0.054–0.060 for the others.
- The CacheBlend-like layer-1 deviation selector beats random, as published.
  - At 4K it does **not** beat the static EPIC first-k or chunk-start baselines at equal budget.
  - At 2K, post-query, it pulls ahead of them from 15 % up.
  - Its picks contain the chunk starts. At 20 % its selection is identical to "16 chunk-start tokens + deviation" in every seed and
    size, which is the chunk-start clustering reported by arXiv 2603.20218.
- Contiguous runs (w = 8) give no consistent gain.
- Greedy exact match does not follow KL: in 8 of 30 query-vs-deviation cells (4 of 9 contexts) deviation keeps full's greedy path
  where query does not, and the opposite happens in 1 cell. The data neither support nor rule out a generation advantage for
  deviation; see "Query relevance wins on KL; greedy EM is mixed".
- The numeric noise floor is exactly 0: dotLLM's CPU kernels are batch-invariant, so every non-zero KL here is a real method effect.

## Setup

- **Engine:** dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse`, branch `feature/chunk-kv-reuse`, commit
  **`8569b51c`** (selectors `src/DotLLM.ChunkReuse/Selectors`, harness `benchmarks/ChunkKvLab` command `e2`). CPU `TransformerModel`,
  `SimpleKvCache` F32, auto threads, Release. Engine string `0.3.0-dev.3628.7+8569b51c…` in every log.
- **Model:** `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` / `Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, revision
  `ae44f08e1392f39c0e474af10c3ff8355c8b6688`, 2,497,280,736 bytes, read in place from the HF hub cache.
- **Hardware / OS / SDK:** AMD Ryzen AI MAX+ 395 (16C/32T), 127.1 GB RAM, Windows 11 Pro 10.0.26200, .NET SDK 10.0.401.
- **Corpus (pinned):** `git archive 4a781829 src` of `C:\Development\dotLLM` was extracted into a fresh scratch directory and used
  read-only. It has 1086 `*.cs` documents and **7257** chunks of 512 tokens. The chunk-id SHA-256 is
  `b02b1e6e44ebbf82169f29a42d7847d7ba69203fc52f9d07bef60335c90dc800`, which equals Task 5's re-chunking of `4a781829`. The lab
  refuses to run if the hash differs (`--expect-hash`). This is the same corpus snapshot as E1's main run. So E2's `naive_concat`
  rows reproduce E1's to every printed digit: 2K/4K seed 0 0.14841/0.24892, seed 1 0.13998/0.21098, seed 2 0.10400/0.06159 nats.
- **Contexts, continuation, metrics:** identical to E1 (`ContextBuilder.Build`, same seeds 0–2; teacher-forced 64-token continuation:
  mean KL(P_full ‖ P_method) in nats and top-1 agreement over the 64 rows; greedy 16 exact match). E2 also reports KL and top-1 over
  the rows **after the query** (rows 16–63).
- **Query:** ProphetKV needs the user query. Here the query is the **first 16 continuation tokens**, the prompt tail known at
  request time. It is the only post-context text any selector may read. The selection is made before anything is forwarded after the
  context. Evaluation then feeds the continuation from position L, exactly as in E1. Query rows 0–15 are therefore part of the prompt
  in serving terms. Use the "post-query" columns for the generation-like rows.
  **Why rows 0–15 favour the query selector:** it picks the context tokens those 16 query tokens attend to most, so it refreshes
  exactly the K/V that rows 0–15 read. That is an in-sample advantage on those rows. It is legitimate at request time, because the
  query is known, but the all-row KL overstates the selector's edge on the generation that follows. Post-query KL is the headline
  metric below; all-row KL is kept for comparison with E1.
- **Budget:** `round(L × p / 100)` tokens for p ∈ {5, 10, 15, 20}: 102/205/307/410 at 2K and 205/410/614/819 at 4K. Every selector
  returns exactly that many distinct positions. All selectors except the `random` control rank chunk 0 last. Chunk 0 sits at offset
  0, so its isolated encoding equals the full prefill there and recomputing it is wasted budget. The `random` control also excludes
  chunk 0 (draws from stale tokens only), to be fair to it.
- **Recompute:** `SelectiveRecomputer` (Task 6) with one `Forward` per maximal contiguous run of selected positions, in ascending
  order, over the assembled cache. This equals a one-pass, fixed-set, layer-wise recompute. The same set is used in every layer
  (no per-layer narrowing).

### Selectors

| name | what it is | runnable at serving time? | cost of selection |
|---|---|---|---|
| `first_k` | EPIC / LegoLink-k (arXiv 2410.15332): the first k = 16 tokens of every chunk after the first (round-robin by offset). The rest of the budget is spread evenly (bit-reversal order) over the remaining stale tokens. EPIC's native budget, k = 16 only, is reported as the extra point `first_k @ 2.3 %` (48 tokens at 2K) / `@ 2.7 %` (112 at 4K). | yes, static | 0 |
| `chunk_starts` | All of the budget on equal-length prefixes of the stale chunks (= first-k with k grown to fill the budget). Motivated by the chunk-start clustering in 2603.20218. | yes, static | 0 |
| `deviation` | CacheBlend-like (arXiv 2405.16444): top-k by ‖(K,V)<sub>fresh</sub> − (K,V)<sub>reused</sub>‖ at **layer 1**. The fresh layer-1 K/V come from layers 0–1 over the whole context on a scratch cache (dotLLM change C4). This is CacheBlend's proxy, **without gradual per-layer filtering**. | yes | 2/36 of a prefill (1.0–3.8 s CPU) |
| `deviation_oracle` | Same ranking, but the deviation is taken against the **full-prefill K/V summed over all 36 layers**. **Not runnable at serving time**: it needs the full prefill that reuse avoids. It is an upper bound on deviation *information*, not the optimal selection. | **no** | a full prefill |
| `random` | Control: a seeded permutation of the stale tokens. Nested across budgets. | yes | 0 |
| `query` | ProphetKV-style (arXiv 2602.02579): the 16 query tokens are forwarded over the reused KV. Each context token is scored by the attention the query pays it, averaged over heads, query tokens and all 36 layers (read with dotLLM probe C7). One fixed set is recomputed in every layer. | yes, but query-dependent | one 16-token forward (0.8–5.2 s CPU) |
| `combined` | The **selection part of PSR** (arXiv 2603.20218): 16 chunk-start tokens per stale chunk, then layer-1 deviation top-k for the rest. PSR's Link0 dummy-prefix encoding and APE attention scaling are not token selections and are **not implemented**. This is not PSR. | yes | as `deviation` |
| `X+runs` | `ContiguousRuns` decorator (CacheClip-style grouping, w = 8): walking X's ranking, each uncovered anchor contributes up to 8 tokens forward. The same budget is truncated exactly. | as X | as X |

## Results

Mean over 3 seeds; [min, max] where shown, and for every cell in `summary.md`. KL is in nats; lower is better. In parentheses: the
share of the naive-concat value removed (mean of per-seed ratios). Reference rows: `full` = 0 by definition. `naive_concat`:

| size | all-row KL | post-query KL | top-1 |
|---|---|---|---|
| 2K | 0.1308 [0.1040, 0.1484] | 0.1274 [0.0707, 0.1700] | 0.875 |
| 4K | 0.1738 [0.0616, 0.2489] | 0.1415 [0.0803, 0.1755] | 0.906 |

All numbers come from `python -I summarize.py results.csv > summary.md` and `python -I summarize.py results-8k-all.csv >
summary-8k.md`. Each summary has both an all-row and a post-query selector × budget table.

**Numeric noise floor** (3 seeds × 2 sizes, all bitwise equal to `full`: KL 0, top-1 1.000, EM 1.000):
- `noise_prefill_block128` is the same ids prefilled in 128-token blocks instead of 512.
- `noise_recompute_all` is naive assembly followed by recompute of every token (one L-row `Forward` over the assembled cache).

Both are bitwise identical to the reference. dotLLM's CPU kernels are batch-invariant (#530), so block size does not change
numerics. The second row is also the end-to-end pipeline check: assembly, recompute and evaluation at 100 % budget reproduce full
prefill exactly. The only non-bitwise numeric path left in the methods is the RoPE re-rotation of K. E1 measured it at ≤ 3e-5 of the
head norm at 16K, which is far below every effect below. So any KL > 0 here is a method effect, not noise.

### Post-query KL (rows 16–63), the headline metric

Seed spread (mean [min, max] over 3 seeds; plain selectors at the lowest and highest swept budget):

| selector | 2K 5 % | 2K 20 % | 4K 5 % | 4K 20 % |
|---|---|---|---|---|
| naive_concat | 0.1274 [0.0707, 0.1700] | — | 0.1415 [0.0803, 0.1755] | — |
| first_k | 0.0588 [0.0349, 0.0825] | 0.0510 [0.0317, 0.0693] | 0.0495 [0.0414, 0.0553] | 0.0466 [0.0354, 0.0580] |
| chunk_starts | 0.0597 [0.0313, 0.0880] | 0.0466 [0.0244, 0.0809] | 0.0481 [0.0441, 0.0519] | 0.0455 [0.0362, 0.0619] |
| deviation | 0.0578 [0.0355, 0.0908] | 0.0369 [0.0201, 0.0562] | 0.0497 [0.0432, 0.0536] | 0.0444 [0.0350, 0.0625] |
| combined | 0.0541 [0.0365, 0.0788] | 0.0369 [0.0201, 0.0562] | 0.0470 [0.0414, 0.0523] | 0.0444 [0.0350, 0.0625] |
| query | 0.0663 [0.0501, 0.0902] | **0.0251 [0.0158, 0.0373]** | **0.0420 [0.0358, 0.0519]** | **0.0173 [0.0096, 0.0297]** |
| random | 0.1301 [0.0712, 0.1726] | 0.1053 [0.0698, 0.1506] | 0.1318 [0.0822, 0.1703] | 0.0970 [0.0658, 0.1257] |
| deviation_oracle (not runnable) | 0.0604 [0.0331, 0.0875] | 0.0366 [0.0293, 0.0446] | 0.0512 [0.0460, 0.0603] | 0.0466 [0.0319, 0.0725] |

By budget (mean; share of naive post-query KL removed):

| selector | 2K 5 % | 2K 10 % | 2K 15 % | 2K 20 % | 4K 5 % | 4K 10 % | 4K 15 % | 4K 20 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| first_k | 0.0588 (+53 %) | 0.0538 (+57 %) | 0.0537 (+55 %) | 0.0510 (+59 %) | 0.0495 (+59 %) | 0.0420 (+66 %) | 0.0447 (+62 %) | 0.0466 (+60 %) |
| chunk_starts | 0.0597 (+54 %) | 0.0540 (+58 %) | 0.0499 (+58 %) | 0.0466 (+65 %) | 0.0481 (+61 %) | 0.0456 (+63 %) | 0.0481 (+59 %) | 0.0455 (+60 %) |
| deviation | 0.0578 (+54 %) | 0.0505 (+60 %) | 0.0438 (+66 %) | 0.0369 (+71 %) | 0.0497 (+59 %) | 0.0468 (+60 %) | 0.0479 (+56 %) | 0.0444 (+60 %) |
| combined | 0.0541 (+56 %) | 0.0513 (+59 %) | 0.0438 (+66 %) | 0.0369 (+71 %) | 0.0470 (+61 %) | 0.0458 (+61 %) | 0.0489 (+55 %) | 0.0444 (+60 %) |
| query | 0.0663 (+43 %) | 0.0473 (+61 %) | 0.0370 (+70 %) | **0.0251 (+80 %)** | 0.0420 (+64 %) | 0.0345 (+67 %) | 0.0258 (+75 %) | **0.0173 (+83 %)** |
| random | 0.1301 (−2 %) | 0.1268 (−1 %) | 0.1119 (+11 %) | 0.1053 (+15 %) | 0.1318 (+5 %) | 0.1190 (+12 %) | 0.0971 (+25 %) | 0.0970 (+21 %) |
| deviation_oracle (not runnable) | 0.0604 (+53 %) | 0.0544 (+57 %) | 0.0431 (+64 %) | 0.0366 (+69 %) | 0.0512 (+57 %) | 0.0509 (+55 %) | 0.0464 (+59 %) | 0.0466 (+57 %) |

EPIC native (k = 16), post-query: 0.0602 [0.0330, 0.0835] at 2K (2.3 %) and 0.0495 [0.0442, 0.0540] at 4K (2.7 %). The `+runs`
variants are in `summary.md`. Their relation to the plain selectors is as described for all-row KL below; for example post-query
`query+runs` at 4K 20 % is 0.0248 against 0.0173 for plain `query`.

### All-row KL (rows 0–63, E1-comparable) with seed spread (mean [min, max] over 3 seeds; plain selectors, the lowest and highest swept budget)

| selector | 2K 5 % | 2K 20 % | 4K 5 % | 4K 20 % |
|---|---|---|---|---|
| naive_concat | 0.1308 [0.1040, 0.1484] | — | 0.1738 [0.0616, 0.2489] | — |
| first_k | 0.0661 [0.0604, 0.0734] | 0.0546 [0.0494, 0.0636] | 0.0560 [0.0421, 0.0701] | 0.0501 [0.0440, 0.0603] |
| chunk_starts | 0.0662 [0.0569, 0.0795] | 0.0628 [0.0366, 0.0807] | 0.0537 [0.0397, 0.0674] | 0.0469 [0.0418, 0.0519] |
| deviation | 0.0649 [0.0517, 0.0815] | 0.0518 [0.0366, 0.0687] | 0.0555 [0.0409, 0.0723] | 0.0473 [0.0442, 0.0500] |
| combined | 0.0628 [0.0499, 0.0724] | 0.0518 [0.0366, 0.0687] | 0.0534 [0.0400, 0.0693] | 0.0473 [0.0442, 0.0500] |
| query | 0.0645 [0.0578, 0.0725] | 0.0222 [0.0174, 0.0296] | 0.0457 [0.0398, 0.0557] | 0.0183 [0.0144, 0.0227] |
| random | 0.1318 [0.1046, 0.1490] | 0.1015 [0.0820, 0.1253] | 0.1680 [0.0630, 0.2547] | 0.1130 [0.0761, 0.1618] |
| deviation_oracle (not runnable) | 0.0687 [0.0634, 0.0782] | 0.0397 [0.0365, 0.0458] | 0.0558 [0.0462, 0.0651] | 0.0469 [0.0402, 0.0550] |

The [min, max] for every selector, budget and runs variant, and for top-1, post-query KL, EM, oracle Jaccard, forward calls and
recompute time, is in `summary.md` (2K/4K) and `summary-8k.md`.

### All-row KL vs budget (rows 0–63; includes the 16 query rows that favour `query`)

2K (naive 0.1308):

| selector | 5 % | 10 % | 15 % | 20 % |
|---|---:|---:|---:|---:|
| first_k | 0.0661 (+48 %) | 0.0581 (+55 %) | 0.0577 (+55 %) | 0.0546 (+58 %) |
| chunk_starts | 0.0662 (+49 %) | 0.0595 (+54 %) | 0.0663 (+46 %) | 0.0628 (+49 %) |
| deviation | 0.0649 (+50 %) | 0.0597 (+53 %) | 0.0599 (+52 %) | 0.0518 (+58 %) |
| combined | 0.0628 (+51 %) | 0.0603 (+53 %) | 0.0599 (+52 %) | 0.0518 (+58 %) |
| query | 0.0645 (+50 %) | **0.0443 (+66 %)** | **0.0337 (+74 %)** | **0.0222 (+83 %)** |
| random | 0.1318 (−1 %) | 0.1259 (+4 %) | 0.1095 (+17 %) | 0.1015 (+22 %) |
| deviation_oracle (not runnable) | 0.0687 (+47 %) | 0.0617 (+52 %) | 0.0510 (+59 %) | 0.0397 (+68 %) |
| first_k+runs | 0.0625 (+51 %) | 0.0594 (+54 %) | 0.0569 (+55 %) | 0.0535 (+58 %) |
| chunk_starts+runs | 0.0637 (+51 %) | 0.0609 (+53 %) | 0.0687 (+44 %) | 0.0631 (+49 %) |
| deviation+runs | 0.0657 (+49 %) | 0.0578 (+55 %) | 0.0489 (+62 %) | 0.0583 (+53 %) |
| combined+runs | 0.0634 (+50 %) | 0.0571 (+55 %) | 0.0472 (+64 %) | 0.0587 (+52 %) |
| query+runs | 0.0639 (+51 %) | 0.0634 (+49 %) | 0.0394 (+69 %) | 0.0283 (+79 %) |
| random+runs | 0.1377 (−6 %) | 0.1303 (+0 %) | 0.1232 (+6 %) | 0.1070 (+19 %) |
| deviation_oracle+runs | 0.0724 (+44 %) | 0.0703 (+46 %) | 0.0614 (+52 %) | 0.0569 (+56 %) |

EPIC native (k = 16, 48 tokens = 2.3 %): 0.0678 [0.0613, 0.0753].

4K (naive 0.1738):

| selector | 5 % | 10 % | 15 % | 20 % |
|---|---:|---:|---:|---:|
| first_k | 0.0560 (+59 %) | 0.0498 (+65 %) | 0.0507 (+62 %) | 0.0501 (+60 %) |
| chunk_starts | 0.0537 (+61 %) | 0.0507 (+63 %) | 0.0508 (+60 %) | 0.0469 (+61 %) |
| deviation | 0.0555 (+59 %) | 0.0520 (+60 %) | 0.0524 (+56 %) | 0.0473 (+60 %) |
| combined | 0.0534 (+61 %) | 0.0518 (+60 %) | 0.0527 (+55 %) | 0.0473 (+60 %) |
| query | **0.0457 (+64 %)** | **0.0372 (+66 %)** | **0.0275 (+74 %)** | **0.0183 (+83 %)** |
| random | 0.1680 (+2 %) | 0.1390 (+13 %) | 0.1167 (+23 %) | 0.1130 (+20 %) |
| deviation_oracle (not runnable) | 0.0558 (+57 %) | 0.0548 (+54 %) | 0.0480 (+60 %) | 0.0469 (+58 %) |
| first_k+runs | 0.0564 (+58 %) | 0.0569 (+61 %) | 0.0562 (+58 %) | 0.0515 (+62 %) |
| chunk_starts+runs | 0.0559 (+58 %) | 0.0525 (+62 %) | 0.0513 (+59 %) | 0.0475 (+60 %) |
| deviation+runs | 0.0533 (+61 %) | 0.0513 (+61 %) | 0.0486 (+61 %) | 0.0473 (+62 %) |
| combined+runs | 0.0524 (+63 %) | 0.0523 (+60 %) | 0.0501 (+60 %) | 0.0487 (+61 %) |
| query+runs | 0.0628 (+54 %) | 0.0445 (+65 %) | 0.0364 (+66 %) | 0.0279 (+74 %) |
| random+runs | 0.1501 (+8 %) | 0.1495 (+8 %) | 0.1449 (+14 %) | 0.1219 (+25 %) |
| deviation_oracle+runs | 0.0545 (+60 %) | 0.0559 (+58 %) | 0.0566 (+54 %) | 0.0542 (+58 %) |

EPIC native (k = 16, 112 tokens = 2.7 %): 0.0563 [0.0413, 0.0712].

All-row top-1 at 20 % (2K/4K): query 0.948 / 0.958, deviation 0.938 / 0.922, first_k 0.938 / 0.901, random 0.875 / 0.917, naive
0.875 / 0.906.

**All-row vs post-query KL:** the two metrics rank the selectors the same way at 4K at every budget, and at 2K at 20 %. They differ
at 2K at lower budgets:
- At 2K 5 %, `query` is mid-pack on all-row KL (0.0645) but the **worst** structured selector post-query (0.0663, against
  0.054–0.060).
- At 2K, `deviation` keeps improving post-query from 5 % to 20 % (0.0578 → 0.0505 → 0.0438 → 0.0369). Its all-row "plateau" at 2K
  (0.065 → 0.052) is partly an artefact of the query rows.

Full tables with [min, max], forward calls, recompute time and the Jaccard with the oracle selection are in `summary.md`.

### 8K follow-up (the two best runnable score-based selectors, 10 % and 20 %, 3 seeds)

Same protocol and corpus, with no noise rows and no runs variants. The two runs were seed 0 (`results-8k.csv`, `e2-8k.log`) and
seeds 1–2 (`results-8k-s12.csv`, `e2-8k-s12.log`). The first 8K process stopped after seed 0 when the session restarted, and seeds 1–2
were rerun with `-FirstSeed 1 -Seeds 2`. They are merged in `results-8k-all.csv` and `summary-8k.md`. `naive_concat` again reproduces
E1 exactly: 0.59840 / 0.69475 / 0.35528.

| method | budget | post-query KL mean [min, max] | all-row KL mean [min, max] | top-1 | greedy EM |
|---|---:|---|---|---|---|
| naive_concat | 0 | 0.6037 [0.4530, 0.7638] | 0.5495 [0.3553, 0.6947] | 0.760 [0.641, 0.891] | 0.42 [0.12, 1.00] |
| deviation | 10 % | 0.1157 [0.0707, 0.1805] (+80 %) | 0.1177 [0.0761, 0.1751] (+78 %) | 0.891 [0.812, 0.953] | 0.71 [0.25, 1.00] |
| deviation | 20 % | 0.1013 [0.0505, 0.1417] (+82 %) | 0.1083 [0.0882, 0.1397] (+79 %) | 0.880 [0.781, 0.953] | 0.96 [0.88, 1.00] |
| query | 10 % | **0.0349 [0.0199, 0.0564] (+94 %)** | 0.0347 [0.0263, 0.0513] (+93 %) | **0.927 [0.891, 0.953]** | 0.71 [0.25, 1.00] |
| query | 20 % | **0.0176 [0.0079, 0.0257] (+97 %)** | 0.0179 [0.0134, 0.0245] (+96 %) | **0.948 [0.891, 0.984]** | 0.75 [0.25, 1.00] |

At 8K the gap widens. In every seed, deviation's KL is 3.2–6.4× query's post-query, and 2.9–7.2× all-row. Deviation barely improves
from 10 % to 20 %.

### Query relevance wins on KL; greedy EM is mixed

Teacher-forced KL and top-1 and free-running greedy exact match do not agree on every cell, so the comparison is reported in full.
Over all 30 query-vs-deviation cells (2K/4K × 3 seeds × 4 budgets, plus 8K × 3 seeds × 2 budgets):
- **KL:** query is lower in **26 of 30** cells on all-row KL and **25 of 30** on post-query KL. The post-query exceptions are 2K seed 1
  at 5/10 %, 2K seed 2 at 5/10 %, and 4K seed 2 at 10 %.
- **top-1:** query is ≥ deviation in **24 of 30** cells, on both all-row and post-query top-1.
- **Greedy EM:** deviation is higher in **8**, query is higher in **1**, and **21** are ties.

Every cell where EM differs:

| context | budget | EM query / deviation | all-row KL query / deviation | post-query KL query / deviation |
|---|---:|---|---|---|
| 2K seed 2 | 5 % | 0.125 / 1.0 | 0.0633 / 0.0616 | 0.0584 / 0.0355 |
| 2K seed 2 | 15 % | 0.125 / 0.5 | 0.0270 / 0.0783 | 0.0244 / 0.0256 |
| 2K seed 2 | 20 % | 0.125 / 1.0 | 0.0174 / 0.0687 | 0.0158 / 0.0201 |
| 4K seed 1 | 5 % | 0.25 / 1.0 | 0.0557 / 0.0723 | 0.0382 / 0.0523 |
| 4K seed 1 | 15 % | 0.25 / 1.0 | 0.0224 / 0.0554 | 0.0116 / 0.0357 |
| 8K seed 0 | 10 % | 0.25 / 0.875 | 0.0513 / 0.1751 | 0.0564 / 0.1805 |
| 8K seed 0 | 20 % | 0.25 / 0.875 | 0.0245 / 0.1397 | 0.0257 / 0.1417 |
| 8K seed 2 | 10 % | 0.875 / 1.0 | 0.0263 / 0.0761 | 0.0284 / 0.0961 |
| 8K seed 1 | 10 % | **1.0 / 0.25** (query better) | 0.0266 / 0.1019 | 0.0199 / 0.0707 |

The 8 deviation-better cells come from **4 of the 9 contexts**: 2K seed 2, 4K seed 1, 8K seed 0 and 8K seed 2. Within a context,
query's EM depends on the budget:
- At 2K seed 2, query's EM is 1.0 at 10 %.
- At 4K seed 1, it is 1.0 at 10 % and 20 %.
- At 8K seed 2, it is 1.0 at 20 %.

The KL gap in these cells also varies. In 2K seed 2 at 5 % query's KL is *higher* than deviation's on both metrics. In the other seven deviation-better cells query's KL is lower by 1.3–5.7× all-row and by 1.05–5.5× post-query. So no consistent per-context explanation, such as a single near-tie, is supported.

EM is quantised: one flip at step t sets it to t/16. Each context has a single 16-token greedy window, and that window lies inside the
16-token query span. The only supported conclusion is that the data **can neither support nor rule out** "deviation preserves
generation better". Deciding it needs per-step evidence, such as the full-vs-method logit margin at the divergence step, or several
continuations per context. Deviation's 8K mean EM at 20 % (0.96 vs 0.75) comes from seed 0 alone.


## Findings, and whether the baselines behave as published

1. **Every structured selector beats naive concat**, as expected. Post-query, each one removes 43–56 % (2K) and 57–64 % (4K) of the
   naive KL at 5 %, including the oracle. All-row, the ranges are 47–51 % and 57–64 %. The only selector that does not is the **random control**: −2…+25 %
   post-query (−1…+23 % all-row), close to naive at low budget. That matches 2609.17983 (Random ≈ 0 recovery) and is why it is the
   control.
2. **Deviation and query relevance beat random**: yes, by a wide margin at every budget and size. For example, post-query at 4K 10 %:
   deviation 0.047, query 0.035, random 0.119.
3. **Query relevance (ProphetKV) is the strongest selector at 4K and 8K, and at 2K from 15 % up.** Post-query it goes from +43 % (2K)
   / +64 % (4K) at 5 % to +80 % / +83 % at 20 %, and to +97 % at 8K. Its all-row top-1 at 20 % (0.95–0.96) is the highest.
   - At **2K 5 %** it is the **worst** structured selector post-query (0.066 against 0.054–0.060).
   - Its "scales with budget, others plateau" pattern holds **at 4K**: the others stay at 55–66 % post-query from 5 % to 20 %.
   - At 2K, deviation and combined also keep improving post-query (+54 % → +71 %), so query is not the only selector that scales
     there.

   Part of query's all-row advantage comes from rows 0–15, the query it was built from (see "Query"). Post-query the 2K/4K 20 % margin
   over deviation is +80 % vs +71 % at 2K and +83 % vs +60 % at 4K. This agrees with ProphetKV's own claim (beats CacheBlend and EPIC)
   at medium and high budget. It is the bar a structure-aware selector must beat (E4).
4. **CacheBlend-style layer-1 deviation does not beat the static baselines at 4K, and does only from 15 % up at 2K (post-query).**
   - At 4K it is within ≈ 0.005 nats of `first_k` / `chunk_starts` post-query at every budget, and within ≈ 0.01 nats all-row.
   - At 2K post-query it is within 0.004 nats at 5–10 % and ahead from 15 %: 0.044 / 0.037 at 15 / 20 %, against 0.054 / 0.051 for first_k and
     0.050 / 0.047 for chunk_starts.
   - EPIC at its native 2.3–2.7 % (post-query 0.060 / 0.050) already reaches most of what deviation reaches at 20 % at 4K.

   Two measured reasons:
   - (a) **Its picks are the chunk starts.** `combined` (16 chunk-start tokens per chunk + deviation) produced the *identical*
     selection to `deviation` (identical KL, forward-call count and oracle Jaccard) in 6 of 6 seed × size cases at 20 %, 4 of 6 at 15 %
     and 1 of 6 at 10 %. So the layer-1 deviation top-20 % contains the first 16 tokens of every stale chunk, and smaller budgets
     contain most of them. This is 2603.20218's "chunk-start clustering at
     early layers" on this model.
   - (b) **Deviation magnitude is a weak ranking signal here.** Even the full-information oracle (all-layer deviation against full
     prefill) is no better than layer-1 deviation, except at 2K 20 % (0.040 vs 0.052). That matches 2609.17983's finding that
     oracle-ranked positions recover little under actual recompute.

   CacheBlend's paper claim (near-full quality at 15 %) is **not reproduced** in this setting. Here deviation at 15 % keeps KL at
   0.05–0.06 nats, versus a noise floor of 0. That is consistent with 2603.20218's cleaned evaluation (CacheBlend r = 15 % trails full
   by 7–18 %). Caveat: we use one fixed set, not gradual per-layer filtering.
5. **Most of naive concat's loss sits at chunk starts.** The first 16 tokens of each chunk (2.3–2.7 % of the context) remove half of
   the KL at 2K and ≈ 2/3 at 4K. Additional *static* budget adds little: post-query, first_k goes from 53 % to 59 % at 2K and stays at
   59–66 % at 4K. This supports EPIC's attention-sink explanation.
   It is also why chunk-start-based selectors (FirstK, ChunkStarts, Combined) and Deviation coincide.
6. **Contiguous runs (w = 8) give no consistent gain at equal budget.** The ± differences are within seed spread. Runs **hurt** the
   best selector (query: 4K 5 % 0.046 → 0.063, 20 % 0.018 → 0.028). Runs do cut the number of forwards 3–10× (for example query 4K
   20 %: 315 → 70 calls, 30 → 20 s on CPU), which matters for this run-per-Forward recompute. Contiguity (CacheClip, 2609.17983) is
   **not confirmed as a quality lever** for chunk reuse in this setting. Note that those papers' contiguity results are for
   aux-model selection (CacheClip) and post-edit repair (2609.17983), not this task.
7. **Pipeline checks behind the conclusions** (the plan asked to debug before concluding):
   - 100 % recompute is bitwise equal to full.
   - `naive_concat` reproduces E1 exactly.
   - Selections are nested across budgets (unit-tested).
   - `random` and `deviation` use the same recompute code path, yet one helps and the other does not.
   - The query selector's attention probabilities reproduce the model's own attention output (unit test,
     `QueryAttentionSource_ProbabilitiesReproduceModelAttentionOutput`).
   - The layer-1 deviation equals the full-prefill layer-1 deviation (unit test).
   - Every unit test was shown to fail on at least one of 19 mutants.

## Caveats

- **Greedy exact match is brittle** and is not used for ranking. At 4K seed 0, naive concat has EM 1.0 and every recompute selector
  has EM 0.06: the greedy paths diverge at the second token, which suggests a near-tie there. One flip changes EM by up to 15/16. KL and
  top-1 over 64 rows are the primary metrics.
- **Seed variance is large.** Naive KL at 4K ranges from 0.06 to 0.25. With 3 seeds, differences under ≈ 0.005–0.01 nats between
  selectors are not separable. Per seed, `query` has the lowest KL among the plain selectors:
  - all-row: 12 of 12 seed × size cells at 15–20 %, but only 6 of 12 at 5–10 %;
  - post-query: 6 of 6 at 20 %, 5 of 6 at 15 %, 3 of 6 at 10 %, and 3 of 6 at 5 % (0 of 3 at 2K 5 %).

  `random` has the highest KL in 24 of 24 cells post-query, and in 23 of 24 all-row (the all-row exception is 2K seed 2 at 15 %, where
  `chunk_starts` is worse). The order among first_k / chunk_starts / deviation / combined changes from seed to seed.
- **One continuation per context, code corpus only** (C#, 512-token fixed chunks). The query is a continuation prefix, not a natural
  question. ProphetKV's advantage may differ on QA-style queries (E4 / Task 8 tasks).
- **CPU recompute times** are one `Forward` per contiguous run (≈ 55–90 ms per single-token run). They show relative cost
  (scattered vs runs), not a serving TTFT. Single-pass recompute needs the per-query-position mask (dotLLM map change C3, not made).
- `deviation` is not full CacheBlend (no gradual filtering). `combined` is not full PSR (no Link0 prefix, no APE scaling).

## Runtime

- Grid (2K + 4K, 3 seeds, 7 selectors × {plain, +runs} × 4 budgets + EPIC native + noise floor): **93.1 min** wall
  (≈ 9–10 min per 2K seed, ≈ 20–25 min per 4K seed). It was under the 3 h cap, so **no breadth cuts were needed**.
- 8K follow-up: seed 0 took 12.6 min (the first process then stopped at the session restart). Seeds 1–2 took **21.8 min** (rerun).
  So 8K costs ≈ 11–13 min per seed for 4 configs: full prefill ≈ 229–243 s, recompute 44–141 s per config.
- Smoke (2K, 1 seed, 4 selectors, 2 budgets) before the grid: 3.5 min. A single-token recompute `Forward` costs ≈ 55 ms at 2K.

## Files

- `run.ps1`: builds the lab, writes the provenance block, runs `ChunkKvLab e2` with `--expect-hash`.
- `summarize.py`: produces `summary.md` from a results CSV (`python -I summarize.py results.csv > summary.md`).
- `results.csv`, `e2.log`, `summary.md`: the 2K/4K grid.
- `results-8k.csv` + `e2-8k.log` (seed 0), `results-8k-s12.csv` + `e2-8k-s12.log` (seeds 1–2), `results-8k-all.csv` (merged),
  `summary-8k.md`: the 8K follow-up.

Reproduce: extract `git archive 4a781829 src` of `C:\Development\dotLLM` into a new empty directory `D`, then
`./run.ps1 -Corpus D\src`. For 8K:
`./run.ps1 -Corpus D\src -Sizes 8192 -Selectors query,deviation -Contiguous none -Budgets 10,20 -Noise 0 -Out results-8k.csv -Log e2-8k.log`
(and the same with `-FirstSeed 1 -Seeds 2 -Out results-8k-s12.csv -Log e2-8k-s12.log` for seeds 1–2).
