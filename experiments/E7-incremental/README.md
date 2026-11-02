# E7: incremental re-encode after single-method edits (Phase S, Task 4)

**Question.** When one method of a large repository is edited, how many tokens of chunk K/V must be re-encoded with
symbol (one member per chunk) versus fixed-size 512-token chunking, and what share of the cache stays valid?

**Answer (codesharp, 300 edits).**

- **Symbol chunking re-encodes about one method per edit:** median **234 tokens** (p10 77, p90 487, max 779).
  - One chunk in 291 of 300 edits, two chunks in the other 9.
- **Fixed-512 re-encodes everything from the edit point to the end of the file**, because 298 of 300 edits change the
  file's token count: median **842 tokens** (p10 265, p90 9,266, max 95,407).
- **Fixed / symbol, typical edit:**
  - **ratio of medians** (842 / 234): **3.6×** (95 % CI 3.0–5.4)
  - **median of the per-edit ratios**: **4.8×** (95 % CI 3.3–6.9)
  - Fixed re-encodes more than symbol in 271 of 300 edits.
  - CIs are from a bootstrap over files.
- **Estimated CPU time per median edit:** about **5 s with symbol chunks against about 17 s with fixed chunks**, at about
  20 ms per token for Qwen3-4B. This is not a wall-clock measurement.
- **The mean is driven by one file.** Means are symbol 254 and fixed 6,590 tokens, a ratio of 25.9× (CI 4.6–56.3).
  - `src/CodeSharp.Tui/TuiApp.cs` (136K tokens) holds 30 of the 300 edits (10 %), but **81 % of all fixed re-encoded
    tokens**.
  - It is the only edited file over 32K tokens.
  - **Without it, the ratio of means is 5.6×** (symbol 244, fixed 1,378; 270 edits).
  - The 25.9× and its wide CI mostly reflect how often the bootstrap draws that one file. Use them only as an
    outlier-driven upper figure.
- **Hit rate in the edited file** (share of its chunks still valid):
  - symbol: mean 0.87, median 0.91
  - fixed: mean 0.44, median 0.50

This is a **tokenisation-only** result: it counts tokens whose K/V must be recomputed. It says nothing about the
cross-chunk quality of the reused cache; that is E4's question. Measured on CPU, with no model forward pass.

## Setup

- **Code:**
  - dotLLM branch `feature/chunk-index` @ `6aa4832d` (dirty=0, not pushed)
  - `ChunkIndex` (`src/DotLLM.ChunkReuse/Store/ChunkIndex.cs`)
  - lab command `ChunkKvLab e7` (`benchmarks/ChunkKvLab/E7Command.cs`)
  - run script [`run.ps1`](run.ps1), summariser [`summarize.py`](summarize.py)
  - log [`logs/e7-codesharp.log`](logs/e7-codesharp.log), per-edit rows [`raw/codesharp.csv`](raw/codesharp.csv)
    (SHA-256 `a67f242e34a8a96b41c7bba601dc0ffb25cbebfc1464dcee6021614a3dcdafa9`), tables [`summary.md`](summary.md)
  - The run used `6aa4832d`. The later review-fix commit `6ec51265` changes `ChunkIndex` (path normalisation, load
    validation, eviction helpers) but not the diff/status semantics that E7 measures, so the CSV was not regenerated.
- **Corpus:** the frozen codesharp snapshot from [`../corpus.md`](../corpus.md)
  (`git archive` of `8e2adbd8`, `src`, 1,390 files). Both chunkings reproduced their pinned chunk-id hashes:
  - symbol-512 `bf397403…`: 7,586 chunks, 1,535,738 tokens
  - fixed-512 `cde11b22…`: 3,766 chunks, 1,530,303 tokens
- **Tokenizer:** the BPE embedded in `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` Q4_K_M, snapshot `ae44f08e` (HF cache).
  No weights are run.
- **Index:** one `ChunkIndex` per chunker. Each chunk is keyed with `ChunkKey.Create` over its token ids and a fixed producer
  label; the producer is irrelevant to hit/miss counting. The **pristine store** is the set of every key of the unedited
  snapshot:
  - symbol: 7,497 distinct keys, because 89 chunks are textual duplicates and share an entry
  - fixed: 3,765 distinct keys
- **Edit sites:** methods and constructors with a block body and at least one statement alone on its line. There are 2,698
  such sites in 716 files.
- **Edits:** for each seed (0, 1, 2), 100 sites are drawn uniformly without replacement, with `Random(seed)`. Each edit picks
  one such statement and one kind, uniformly:
  - **insert:** a new line `System.Diagnostics.Debug.WriteLine("e7 edit");` after the statement (median +10 file tokens)
  - **delete:** the statement's line is removed (median −13 tokens)
  - **modify:** the last character of the statement's first identifier (2 or more characters long) is changed in place
    (median +1 token)

  The edits need not compile, since only tokens matter. The 300 edits cover 290 distinct methods in 198 files.
- **Per edit:**
  1. `ChunkIndex.Update([edited file], chunker, removeMissingFiles: false)`.
  2. **Re-encoded tokens** = the tokens of the chunks the diff reports as `Added` whose key the pristine store lacks.
  3. **Cross-check:** `ChunkIndex.Status(store)` must list exactly those chunks (same count and tokens). It did for all 600
     updates.
  4. The edit is reverted, and the index must be up to date again.

  So every edit starts from the pristine snapshot, and edits are independent.

## Results

### Re-encoded tokens per edit (300 edits, 3 seeds pooled)

| chunker | mean | min | p10 | p25 | median | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **symbol-512** | **254** | 25 | 77 | 124 | 234 | 362 | 487 | 779 |
| **fixed-512** | **6,590** | 12 | 265 | 460 | 842 | 2,212 | 9,266 | 95,407 |
| edited method (with leading trivia) | 305 | 27 | 77 | 127 | 237 | 392 | 610 | 1,578 |
| whole edited file (re-encoding the file) | 16,298 | 249 | 610 | 1,083 | 2,054 | 5,005 | 40,937 | 136,393 |

Per seed (mean / median):

| seed | symbol | fixed | fixed / symbol (ratio of means) |
|---:|---|---|---:|
| 0 | 280 / 244 | 6,604 / 794 | 23.6 |
| 1 | 240 / 208 | 5,669 / 790 | 23.6 |
| 2 | 243 / 240 | 7,497 / 939 | 30.8 |

Paired comparison (bootstrap that resamples files, 10,000 resamples, 95 % percentile CI):

| quantity | value | 95 % CI |
|---|---:|---|
| symbol mean | 254 | 230–278 |
| fixed mean | 6,590 | 1,121–14,918 |
| fixed − symbol (mean paired difference) | 6,335 | 881–14,645 |
| **fixed / symbol (ratio of medians, 842 / 234)** | **3.59** | 3.00–5.37 |
| **fixed / symbol (median of per-edit ratios)** | **4.83** | 3.28–6.86 |
| fixed / symbol (ratio of means; outlier-driven, see below) | 25.9 | 4.6–56.3 |

**One file dominates the means.** `src/CodeSharp.Tui/TuiApp.cs` (136K tokens) is the only edited file over 32K tokens.
- Edit sites are uniform over methods, and that file holds about 10 % of the 2,698 sites, so it received 30 of the 300
  edits.
- Its five worst edits re-encode 89K–95K tokens each with fixed chunks, against 114–496 tokens with symbol chunks.
- It accounts for **81 % of all fixed re-encoded tokens**.

Without it (270 edits):

| quantity | value |
|---|---:|
| symbol mean | 244 |
| fixed mean | 1,378 |
| ratio of means | **5.6×** |
| ratio of medians | 3.3× |
| median per-edit ratio | 4.0× |

With one cluster carrying 81 % of the fixed mass, the CI of the ratio of means mostly reflects how often the bootstrap
draws that file (0, 1 or more times). It is not an informative interval.

### By edit kind

| kind | edits | file token delta (median) | symbol mean / median | fixed mean / median |
|---|---:|---:|---|---|
| insert | 107 | +10 | 255 / 239 | 8,902 / 762 |
| delete | 99 | −13 | 243 / 223 | 3,928 / 895 |
| modify | 94 | +1 | 266 / 246 | 6,761 / 908 |

**Fixed chunking keeps the tail of a file only if the edit leaves the token count unchanged.** BPE rarely allows that:
- Even the one-character identifier change kept the file's token count in only **2 of 300** edits.
- Those two edits re-encoded only one fixed chunk (median 297 tokens).
- In every other edit, every fixed chunk from the edited one to the end of the file was re-keyed.
- Median share of the edited file re-encoded with fixed chunks: 0.48 (p10 0.13, p90 1.00).

### Cache hit rate after one edit

| chunker | chunks in edited file (median) | re-encoded chunks: mean / median / max | chunk hit rate in edited file: mean / median | token hit rate in edited file: mean / median | token hit rate, whole corpus (mean) |
|---|---:|---|---|---|---:|
| symbol | 11 | 1.03 / 1 / 2 | 0.869 / 0.909 | 0.852 / 0.903 | 0.99983 |
| fixed | 5 | 13.4 / 2 / 187 | 0.440 / 0.500 | 0.493 / 0.521 | 0.99569 |

**Denominators:**
- The edited-file token hit rate divides by the file's whole-file token count after the edit.
- Symbol chunks are tokenised one chunk at a time, so their token sum is slightly larger. Over the corpus it is 1,535,738
  against 1,530,303 for whole-file tokenisation, a difference of 0.4 %. The symbol token hit rate is therefore a slight
  underestimate.
- The whole-corpus column divides by each chunker's own corpus total.

### Where symbol chunking is not "exactly the method"

- **Methods over 512 tokens** are split into several chunks at statement boundaries. This applied to 44 of the 300 edits.
  - For those, symbol chunking re-encodes only the touched pieces: mean 407 of 787 method tokens.
- **9 edits re-encoded 2 chunks.** Seven of them are inserts (+10 tokens). The method sizes were 391, 505, 508, 525, 595,
  602, 661, 765 and 782 tokens, and three causes cover them:
  - **The 512-token cap was crossed.** Two methods of 505 and 508 tokens went over 512 after the insert, so their chunk was
    split into two.
  - **A glued header pushed the chunk over the cap.** The 391-token method's chunk also carries the file header (usings,
    namespace and type declaration are glued to the first member), so it was already close to 512.
  - **A boundary moved inside a long method.** For the methods over 512 tokens, the greedy re-split moved one boundary.
- **Symbol re-encodes more than the method's own tokens in 180 of 300 edits.** Usually the excess is just the edit's token
  delta. The largest excess, 387 tokens, is a glued file header.
- **Fixed was cheaper in 25 of 300 edits** (and equal in 4). Each of these re-encoded one fixed chunk: the last, partly
  filled chunk of the file, which is smaller than the edited method's symbol chunk (for example 31 against 175 tokens).

### Index update cost

Re-chunking and re-keying one edited file takes these times per edit (median / p90):
- symbol: 9.2 / 486 ms (Roslyn parse plus per-chunk tokenisation; the slow tail is the 136K-token file)
- fixed: 3.3 / 108 ms

Building the whole index from scratch took 5.0 s (symbol) and 1.6 s (fixed) for 1.5 M tokens. This was one E7 process,
on a CPU shared with other sessions' builds.

## What this means

- **For a cache that lives across edits, symbol chunking re-encodes roughly the edited method and nothing else.**
  - That is a median of 234 tokens, about the method's own size (median 237).
  - Fixed-size chunking re-encodes from the edit point to the end of the file.
  - For a typical edit, fixed re-encodes **3.6× more tokens (ratio of medians), or 4.8× (median per-edit ratio)**.
  - On average it is 5.6× more without the one 136K-token file, and 26× with it.
- **Rough time cost on CPU (estimate, not measured).** The store probe's CPU encode rate for Qwen3-4B is about 10–12 s per
  512-token chunk, so about 20 ms per token; it was measured on a contended CPU ([`../store/README.md`](../store/README.md)).
  At that rate:

  | edit | symbol | fixed |
  |---|---:|---:|
  | median edit | about 5 s | about 17 s |
  | mean edit, 270 edits without TuiApp.cs | about 5 s | about 28 s |
  | mean edit, all 300 | about 5 s | about 2.2 min |
- **The fixed-512 cost is structural.** Slicing a file's token stream into fixed lengths means that any change in token
  count re-keys every chunk after the edit. This happened in 298 of 300 edits, so the result is nearly arithmetic.
  - Symbol chunks are also smaller: median 157 tokens against 512.
  - **Untested middle ground:** fixed-size chunks that realign at member or line boundaries, or content-defined
    boundaries (a rolling hash, which needs no parser), would keep the tail of the file stable.
- **This complements the G2 default of fixed-size chunks.** G2 chose fixed-size chunks for *query-time quality and speed*.
  E7 is about *maintenance cost under edits*, and on that axis the symbol chunker wins clearly.
  - A store could index with symbol chunks and still assemble contexts in fixed-size order. The two choices are
    independent, as long as the quality of symbol-chunked contexts is acceptable (E4 measured both).
- **`ChunkIndex.Status` gives the exact list of stale chunks**, by file and line range. It agreed with the diff on all 600
  updates.

## Limitations

- **Synthetic edits:** an inserted debug line, a deleted statement line, or a one-character identifier change. Real edits
  can span several methods, add members (which adds symbol chunks) or change usings and headers. Header text is glued to
  the first member's chunk, so a header edit re-encodes that chunk.
- **Independent edits**, each applied to the pristine snapshot. Cumulative edit sessions were not simulated. The store is
  a key set; no K/V was written and no wall-clock encode time was measured.
- **One corpus** (codesharp, the large one). DocAgent and AFClaude can be run with `run.ps1 -Name docagent|afclaude`.
- **The spec's E7 quality part is not done here.** The edit-local repair baseline (K=32) and the edit-to-dependent-text
  distance axis need model forward passes and belong to a later run.
- **The index JSON size on codesharp was not measured.** The persistence round trip is unit-tested only.

## Reproduce

```
./run.ps1 -Snapshots <dir holding t8-corpus-codesharp-8e2adbd8-20261101111016> [-Seeds 0,1,2] [-Edits 100]
uv run summarize.py raw/codesharp.csv --corpus-tokens symbol=1535738,fixed=1530303 > summary.md
```
