# chunkcache demo: the CLI on the dotLLM solution (Phase S Task 7, Step 5)

The `chunkcache` CLI (`tools/DotLLM.ChunkCache` in the dotLLM worktree `chunk-cache`, branch `feature/chunk-cache`) run on
the dotLLM solution itself with Qwen3-4B-Instruct-2507 Q4_K_M on the CPU. This is a demonstration of the tool, not an
experiment: one task, one run, one machine shared with other agents.

## Setup

- **Code:** dotLLM `94ed8630` (dirty=0), the same tree that was scanned (`dotLLM.slnx`, Configuration=Release).
- **Model:** bartowski `Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, HF cache snapshot `ae44f08e`; model id
  `gguf-sha256:383e0dc9…` (sampled hash), fingerprint `0921b80e…`; 36 layers, **8,192 B/token/layer** F32 K+V
  (294,912 B/token).
- **CPU only, `--threads 8`**, Strix Halo; the CPU was shared with another agent's CPU job (E4c), so the timings are rough.
- **Commands:** `run.ps1` (all steps, with `--json`; logs and JSON results in `logs/`, provenance in `logs/provenance.txt`).
- **Store:** in the session scratchpad; deleted after the run (8.2 GB, 47 GB free on the disk).

## What a full encode would cost

`build --dry-run` over the whole solution (nothing written, 62 s: scan 23 s, chunk + key 35 s):

| | value |
|---|---|
| projects / skipped | 29 / 0 |
| authored files indexed | 2,534 (2,622 scanned, 88 generated) |
| symbol-512 chunks | 40,029 (37,211 distinct keys: identical chunk text dedupes) |
| tokens | 8,044,994 (7,877,157 distinct) |
| estimated store | **2.11 TiB** (F32; distinct tokens × 294,912 B + headers) |
| estimated CPU encode time | **~31–33 h** at the measured 66–71 tokens/s (8 threads) |

A full encode is infeasible here (CPU time and the disk), so the build indexes the whole solution (tokenizer only) and
encodes a selection.

## Build, rerun, status

| step | command (abbreviated) | result | wall time |
|---|---|---|---|
| 2 | `build --solution dotLLM.slnx --symbol ChunkIndex.Update --hops 2 --budget 24000` | whole tree indexed (40,029 chunks); selection 81 chunks / 23,708 tokens (389 more trimmed by the budget); **81 encoded**, 0 wire-ineligible | 491 s: scan 22 s, index 35 s, selection (graph) 71 s, **encode 360 s = 65.9 tokens/s** |
| 3 | same command again | added 0, removed 0, unchanged 40,029; 0 of the 81 selected missing; **0 encoded** | 107 s (scan 23 s, index 0.3 s, selection 81 s) |
| 4 | `build --chunker fixed --symbol ChunkIndex.Update --hops 1 --budget 4096 --exclude tools/DotLLM.ChunkCache/BuildCommand.cs` | fixed-512 index (16,896 chunks, 8,015,655 tokens); 8 chunks / 3,935 tokens encoded | 139 s (encode 56 s, 70.5 tokens/s) |
| 5 | `status --no-scan` (symbol) | 40,029 chunks, 39,948 missing (8,021,286 tokens), not up to date | 1.6 s |
| 6 | `select --symbol ChunkIndex.Update --hops 1 --budget 4096 --exclude …/BuildCommand.cs` | 15 chunks / 3,870 tokens of 12,207 candidate tokens (29 trimmed), all 15 stored | 97 s (scan 21 s, chunk + graph 74 s: 377,452 edges) |

- **Store size after step 4:** 89 entries, 8,152,403,216 B (7.59 GiB) = 27,643 tokens × 294,912 B (8,152,252,416 B)
  + 150,800 B of headers and token ids (≈ 1.7 KB per entry); the estimate printed before encoding uses the same formula.
  The rerun wrote nothing.
- Steps 3 and 6 are dominated by the scan and, for selections, the Roslyn reference graph over the whole solution
  (70–80 s). The index update itself on an unchanged tree is 0.3 s.
- **Bug found and fixed on the way:** the first fixed-512 build failed: `FixedSizeChunker` produced chunks that did not
  tile `src/DotLLM.Tokenizers/ControlTokenGuard.cs`. That file holds U+FDD0, which the Qwen BPE decode drops, so the
  decode-based offsets fell one character short and `ChunkIndex.Update` refused the file. Fix (dotLLM `8788e78c`): the
  last chunk always ends at the end of the text. Interior offsets of a fixed chunk can still drift by such characters
  (fixed chunks are not wire-eligible anyway; integration spec §5.3). The run reported here is the full rerun after the
  fix.

## Compare

Task (`logs/task.json`): the context is the 1-hop neighbourhood of `ChunkIndex.Update` under 4,096 tokens, excluding the
query's own file (so the answer is not in the context); the query is lines 155–166 of `tools/DotLLM.ChunkCache/BuildCommand.cs`
(225 tokens, the code just before the call), and the expected continuation is line 167,
`IndexDiff diff = index.Update(tree.Files, chunker);` (13 tokens). Both chunkings were warm (every context chunk a store
hit). KL is KL(full ‖ reuse) in nats, mean over the 13 teacher-forced continuation rows; top-1 is agreement with full
prefill's argmax; EM is greedy exact match of all 13 expected tokens.

| chunker | arm | budget | recomputed | calls | KL | top-1 | EM | reuse ms | full ms | speedup | path |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|
| symbol-512 | full | 100% | 3870 | 0 | 0.0000 | 1.00 | no | 146,741 | 146,741 | 1.00× | cpu-prefill |
| symbol-512 | naive | 0% | 0 | 0 | 0.2395 | 0.92 | no | 11,880 | 146,741 | 12.35× | - |
| symbol-512 | chunkstarts | 5% | 194 | 14 | 0.0433 | 1.00 | no | 19,420 | 146,741 | 7.56× | cpu-per-run |
| symbol-512 | chunkstarts | 10% | 387 | 13 | 0.0383 | 1.00 | no | 24,709 | 146,741 | 5.94× | cpu-per-run |
| symbol-512 | chunkstarts | 20% | 774 | 10 | 0.0303 | 1.00 | no | 31,724 | 146,741 | 4.63× | cpu-per-run |
| symbol-512 | queryrelevance | 5% | 194 | 139 | 0.0499 | 1.00 | no | 81,973 | 146,741 | 1.79× | cpu-per-run |
| symbol-512 | queryrelevance | 10% | 387 | 234 | 0.0244 | 1.00 | no | 84,744 | 146,741 | 1.73× | cpu-per-run |
| symbol-512 | queryrelevance | 20% | 774 | 369 | 0.0243 | 1.00 | no | 106,794 | 146,741 | 1.37× | cpu-per-run |
| symbol-512 | hybrid | 5% | 194 | 11 | 0.2063 | 0.92 | no | 53,608 | 146,741 | 2.74× | cpu-per-run |
| symbol-512 | hybrid | 10% | 387 | 160 | 0.1782 | 0.92 | no | 67,917 | 146,741 | 2.16× | cpu-per-run |
| symbol-512 | hybrid | 20% | 774 | 352 | 0.0189 | 1.00 | no | 99,400 | 146,741 | 1.48× | cpu-per-run |
| fixed-512 | full | 100% | 3935 | 0 | 0.0000 | 1.00 | no | 132,270 | 132,270 | 1.00× | cpu-prefill |
| fixed-512 | naive | 0% | 0 | 0 | 0.3113 | 0.92 | no | 12,091 | 132,270 | 10.94× | - |
| fixed-512 | chunkstarts | 5% | 197 | 7 | 0.1155 | 1.00 | no | 17,893 | 132,270 | 7.39× | cpu-per-run |
| fixed-512 | chunkstarts | 10% | 394 | 7 | 0.0876 | 1.00 | no | 23,683 | 132,270 | 5.58× | cpu-per-run |
| fixed-512 | chunkstarts | 20% | 787 | 7 | 0.1305 | 0.92 | no | 41,204 | 132,270 | 3.21× | cpu-per-run |
| fixed-512 | queryrelevance | 5% | 197 | 137 | 0.1021 | 1.00 | no | 60,630 | 132,270 | 2.18× | cpu-per-run |
| fixed-512 | queryrelevance | 10% | 394 | 231 | 0.0625 | 1.00 | no | 70,773 | 132,270 | 1.87× | cpu-per-run |
| fixed-512 | queryrelevance | 20% | 787 | 363 | 0.0468 | 1.00 | no | 108,505 | 132,270 | 1.22× | cpu-per-run |
| fixed-512 | hybrid | 5% | 197 | 12 | 0.3021 | 0.92 | no | 55,250 | 132,270 | 2.39× | cpu-per-run |
| fixed-512 | hybrid | 10% | 394 | 92 | 0.2471 | 0.92 | no | 62,383 | 132,270 | 2.12× | cpu-per-run |
| fixed-512 | hybrid | 20% | 787 | 305 | 0.0399 | 1.00 | no | 103,055 | 132,270 | 1.28× | cpu-per-run |

`reuse ms` = store read and RoPE assembly (≈ 1.1 GB of F32 K/V per context) + scoring (query-relevance probe; graph
signals) + selection + recompute + query prefill; `full ms` = context + query prefill. The compare run took 20.5 min.

**Reading it (one task; not evidence for a selector ranking):**
- **Exact match is uninformative here:** full prefill itself misses one of the 13 expected tokens (top-1 of every arm is
  12/13 or 13/13 of full's argmax, and full's own EM is no). KL and top-1 are the usable columns.
- **Which path produced which timing:** full prefill is `cpu-prefill` (512-token blocks); every recompute is
  `cpu-per-run`: one ordinary forward per contiguous run of selected positions. That is the only recompute path on this
  branch; the single-pass Vulkan strategy (jamesburton/dotLLM#1531) plugs in through `IRecomputeStrategy` and is not
  measured here.
- **On CPU per-run, the number of runs sets the cost.** Chunk starts select contiguous prefixes (7–14 runs) and stay
  4.6–7.6× faster than full prefill at 5–20 %; query relevance and hybrid select scattered tokens (92–369 runs, one
  trunk pass each) and fall to 1.2–2.7×. This is the opposite of what a GPU single-pass path would show (Phase G G2: per
  row × key cost, not per run).
- **Full prefill is slow on this contended CPU** (4K in 132–147 s, against ≈ 50 s with all cores in `LLMs.md`), which
  flatters every speedup; the absolute reuse times are the more portable numbers.
- Quality: naive concatenation KL 0.24 (symbol) / 0.31 (fixed); chunk starts reach 0.03–0.04 (symbol); query relevance
  reaches 0.024 at 10 % (symbol) and 0.047 at 20 % (fixed). Hybrid's graph picks spend the 5–10 % budgets badly on this
  task (KL 0.18–0.30, top-1 drops) and only catch up at 20 %. The fixed chunk-starts arm is non-monotonic (20 % worse than
  10 %). One task: no conclusion about selectors beyond "the table works".

## Notes and limits

- `compare` reads the store and never writes it; misses would be encoded in memory and flagged (none here).
- The index update holds the store lock for the whole build (the `AcquireStoreLock` contract), including the 6-min encode.
- The query-relevance and graph scores are charged to every arm that uses them (each request would pay them once).
