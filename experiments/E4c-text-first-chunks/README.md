# E4c — text-first fixed chunks on the E4 arms

**Result in brief** (Qwen3-4B-Instruct-2507 Q4_K_M, CPU, 2K contexts, E4's kept call sites and context rules; 95 %
cluster-bootstrap CIs; full tables in `summary.md`; revised after review, `review-e4c-report.md`):

- **Round trip: no BPE-merge failure was observed, but none is guaranteed.** Decoding each of E4's 512-id slices and
  re-tokenising the text alone gives the same ids for 3,970 of 3,972 chunks. The 2 failures are the **two sides of one
  cut** (DocAgent `IncrementalIngestionEngine.cs` chunks 2 and 3), which falls inside a multi-byte UTF-8 character (U+FFFD,
  first / last id only). That is **1 failing cut in 2,518 interior cuts** (3,972 slices over 1,454 files); the third
  file-range failure (chunk 4) is offset drift from the same cut. The rate is a property of these mostly-ASCII C# corpora,
  Qwen3's tokenizer and N = 512, not of id slicing: the per-cut risk scales with the share of positions inside multi-byte
  characters (high for CJK / emoji / box drawing), and the per-chunk rate grows as N shrinks. Zero merge failures in 2,518
  cuts is an observation only: many cuts fall inside multi-token identifiers, where a suffix tokenised alone is not
  guaranteed to match. Symbol chunks fail 0 / 8,138; text-first chunks 0 / 3,996 (by construction).
- **Quality: no difference from id slices was detected, but non-inferiority is not shown.** On the 21 instances valid
  under both chunkers (12 tasks, 8 definition clusters), text-first − id-sliced share of the naive→full masked-call NLL gap,
  QR: −0.01 / −0.05 / −0.04 / −0.05 at 5 / 10 / 15 / 20 % (20 %: 0.91 vs 0.96, [−0.19, +0.02]); Hybrid(QR) −0.08
  [−0.21, +0.04] at 10 %, −0.03 [−0.18, +0.00] at 20 %; ChunkStarts and Graph within ±0.03 (CIs ∋ 0). The lower bounds
  (QR −0.26 / −0.31 / −0.19 at 10 / 15 / 20 %) are larger than the QR-vs-ChunkStarts margin E4 used to rank arms.
- **What drives the pooled QR −0.05 (S1):** it is a ratio of means, and DocAgent holds 72 % (id slices) to 78 %
  (text-first) of the gap denominator. Per matched instance the QR 20 % difference averages **+0.01** (median −0.02);
  text-first is worse in 11 of 21. Two pairs carry the pooled loss: DocAgent seed 0 `SolutionIngestionService.cs:313:40`,
  0.43 vs 0.97 of its gap (**the only exact-match loss**), and AFClaude seed 1 `FoundryTools.cs:23:48`, 0.42 vs 0.93.
  Leave-one-cluster-out gives −0.03 to −0.09 (reviewer's recomputation).
- **The pairing is nominal (S2).** The seed does not reproduce the distractor draw when the chunker changes: the required
  chunk differs, so distractors and order differ. Chunks per context differ in **19 of 21** pairs, `required_first` in
  7 of 21, and the naive−full gap often differs 2–4× (e.g. AFClaude `FoundryTools.cs:23` seed 1: 1.31 vs 2.94 nats).
  Naive EM 0.67 vs 0.52 comes from three pairs where naive succeeds only in the text-first context. **The pairs share only
  the task**, so the within-pair difference is mostly context-draw noise; the cluster bootstrap stays valid for per-task
  expectations but has little power. A decisive test needs the **same context text** (same distractor file ranges and order)
  chunked both ways.
- **95 % / 20 % bar (S3): at the bar as a point estimate; not met, not validated.** QR (and Hybrid) at 20 %: EM 22 / 23 =
  0.96, Wilson 95 % [0.79, 0.99] on all valid text-first instances; 20 / 21 = 0.95 [0.77, 0.99] on the matched set (one
  more loss would give 0.91). DocAgent alone: 7 / 8 = 0.88 — and DocAgent is the only corpus that ran all three seeds (its
  seeds 1 and 2 ran only context 0, which holds the same 3 tasks in both). The data cannot tell 0.96 from 0.88 or from 1.00.
  E4's id slices: 32 / 32, Wilson [0.89, 1.00] (itself a point estimate on 10 clusters).
- **Within E4c the E4 ranking repeats:** QR > ChunkStarts at every budget (+0.14 to +0.28 of the gap, CIs > 0), Graph < QR
  at 10 / 20 % (−0.15 [−0.28, −0.07], −0.11 [−0.47, −0.02]), Hybrid(QR) ≈ QR (+0.01, +0.02 [0.00, 0.03]); Random (control)
  recovers only 0.09 / 0.15 at 10 / 20 %. On matched codesharp, Graph rows equal ChunkStarts exactly (no graph signal, chunk
  start fill), so they are not independent evidence.
- **Truncated (S4):** 15 of 24 planned contexts ran; 10 of E4's 32 valid id-slice instances have no text-first counterpart.
- **Not run (S8):** the spec's §5.11 extra arm, QR with the query placed **before** the context (the agent-loop layout,
  §5.6). It is an open item, not closed by E4c.

See **Implications** below for what this means for the wire and for `auto_validated`.

Data: `cross.csv` (paired text − slice), `curves.csv` (sets `text-valid|…`, `slice-valid|…`, `matched-*|…`), `pairs.csv`.

## Implications (controller's ruling on gate G-E4c)

- **Wire eligibility of `lines-512` (= `fixed-text-512`) is granted on correctness grounds.** A text-first chunk
  round-trips by construction: 0 / 3,996 failures on the real tokenizer, no invariant violations, 21 property tests,
  15 / 15 mutants killed. Eligibility must not depend on the data or the tokenizer, so id-sliced `fixed-512` stays
  ineligible even though it round-tripped 3,970 / 3,972 here.
- **Quality is NOT validated.** `auto_validated` stays empty. Validation moves to Phase I5 with:
  - a **non-inferiority margin**: lower 95 % bound of text − slice gap at QR 20 % ≥ −0.10, on ≥ 30 valid instances
    (and EM ≥ 0.95 × full);
  - the **9 missing contexts** (procedure under "Run");
  - a **same-context comparison** (one context text, chunked both ways);
  - the **query-before-context arm**.
- **Task 19 comes after Task 5b** (ruling 21, tokenisation): the chunker's size probes, not only its final ids, must use
  `EncodeRaw(MarkUntrustedSpecials(text))`. Otherwise a piece that fits under plain `EncodeRaw` can exceed 512 under the
  marked encoding, and the ids and store key will not match the server. This already matters on these corpora: codesharp
  `src/CodeSharp.Core/Persistence/CompactionSummaryValidation.cs:57` contains `<think>...</think>`, so that chunk's ids,
  the fixed-text-512 hashes in `run.ps1` and this census (computed with plain `EncodeRaw`) change after 5b and must be
  re-pinned / rerun.

## Why

E4 (`../E4-structure-aware`) found that fixed 512-token chunks with query-relevance (QR) selection were the only
configuration meeting the 95 % / 20 % bar (exact match ≥ 0.95 × full prefill at ≤ 20 % recompute). But E4's
`FixedSizeChunker` tokenises the whole file once and slices the **ids** into 512-token chunks. A server that receives a chunk
over the wire as **text** can only tokenise that text alone, which may give different ids (BPE merges across a cut, a cut
inside a multi-byte UTF-8 character). The integration spec (`docs/superpowers/specs/2026-11-02-chunk-cache-integration.md`,
§5.3 item 4 and §5.11) therefore blocks fixed chunks on the wire until their **text-first** variant is measured. E4c asks:

1. How often do E4's id-sliced chunks actually fail the text round trip? (tokenizer only, cheap)
2. Do text-first fixed chunks keep E4's quality on the same arms, call sites, seeds and context-subset rules?

## Text-first chunker

dotLLM `src/DotLLM.ChunkReuse/Corpus/TextFirstFixedChunker.cs`, name `fixed-text-512` (`e4 --chunker fixed-text`). Greedy,
left to right over the file text:

- If the rest of the file tokenises (alone, `EncodeRaw`, no BOS) to ≤ 512 ids, it is the last chunk.
- Otherwise binary-search a code-point boundary whose piece tokenises to ≤ 512 ids (each probe tokenises the candidate
  piece alone; only probed pieces that fit are accepted). Where token count is monotone in length this is the furthest such
  boundary; where it is not, it is *a* fitting boundary whose next probed boundary did not fit. The ≤ 512 guarantee holds
  either way.
- Cut at the **last line end** inside that piece (the furthest one whose piece fits); with no line end, cut at that character
  boundary. The cut never splits a surrogate pair (a 4-byte UTF-8 sequence; BMP characters are whole UTF-16 chars). It
  backs off one character to avoid splitting a `\r\n`; **edge case:** if the backed-off piece does not fit (only possible
  with non-monotone counts) it returns the original cut, which does split the CRLF, and a lone `"\r"` piece is possible when
  the fitting piece is one character long. Neither can occur with Qwen3 on LF-normalised corpora.
- The chunk's ids are its text tokenised alone, so the wire round trip holds by construction. Text is used as given (CRLF
  kept by the chunker; the corpus loader normalises CRLF → LF before chunking, as for every E-series chunker).

This is the spec's proposed `lines-512` in all but name (whole lines up to 512 tokens, over-long lines split at a character
boundary).

**Tests** (dotLLM `tests/DotLLM.Tests.Unit/ChunkReuse/TextFirstFixedChunkerTests.cs`, 21 tests, written first: the build
failed with CS0246 `TextFirstFixedChunker`): chunks concatenate to the file exactly with consistent offsets and lines; every
piece alone ≤ N tokens; chunk ids == the piece tokenised alone (round trip) and decode back to it; greedy cuts at the last
line end that fits; line end preferred over a fuller character cut; over-long lines cut at the last character that fits; no
split UTF-8 sequence or surrogate (byte-level test tokenizer, 2/3/4-byte characters, several N); CRLF preserved and never
split; deterministic; a character longer than the limit throws; id slicing fails the round trip where text-first does not;
a rest of exactly N tokens is one chunk; a rest of N + 1 is cut after N; non-monotone token counts never yield a piece over N.
ChunkReuse suite 254 → 257 tests, all green. **Mutation** (15 mutants of the chunker in a `git archive` scratch copy, never
the live worktree): round 1 killed 11 (one of them, "no step past a surrogate pair at the search floor", by
non-termination: the test host hung and was stopped by PID), one did not compile, three survived (rest-fits shortcut strict,
line-end fallback ignoring the limit, binary-search upper bound one short); three added tests and a rewritten mutant give
15/15 in round 2 (dotLLM `c4579f55`). Round 2 reran only the four round-1 non-kills; the other 11 are killed by tests
still in place. Because T11 is detected only by a hang, the same regression would hang CI rather than fail it; an iteration
guard in the search loop is a follow-up for the server-side chunker. Also for that port: probing is quadratic (each chunk
first tokenises the whole rest of the file, O(F²/N) per file — fine for the 1.4-min census, not for server-side `build`;
find the upper bound by doubling instead), and the size probes must use the marked encoding (see Implications).

The `ChunkKvLab roundtrip` command also asserts the text-first invariants on the **real** Qwen3 tokenizer over all three
corpora (concatenation, ≤ 512, no lone surrogate): no violations.

## Round-trip census (tokenizer only)

`ChunkKvLab roundtrip` (dotLLM `benchmarks/ChunkKvLab/RoundTripCommand.cs`; 1.4 min CPU for all three corpora; no weights
run). Per chunk and chunker: (a) **decoded-text round trip** — `EncodeRaw(Decode(ids)) == ids`, what a client holding only
the ids would send; (b) **file-range round trip** — `EncodeRaw(file[StartOffset..EndOffset]) == ids`, what a text-first
client sends; U+FFFD in the decoded text; where in the chunk the mismatch sits. Table in `summary.md` (first section) and
`roundtrip.csv.gz`; in both DocAgent failures the mismatch is confined to the first or last 3 ids of the slice. The `fixed-text-512` chunk-id
hashes printed there are the `--expect-hash` values in `run.ps1`.

| corpus | fixed (id slice) fails | symbol fails | fixed-text fails | fixed-text chunks (fixed) | median tokens per fixed-text chunk |
|---|---:|---:|---:|---:|---:|
| AFClaude | 0 / 30 | 0 / 74 | 0 / 30 | 30 (30) | 499 |
| DocAgent | 2 / 176 (U+FFFD) | 0 / 478 | 0 / 176 | 176 (176) | 503 |
| codesharp | 0 / 3,766 | 0 / 7,586 | 0 / 3,790 | 3,790 (3,766) | 497 |

## What was compared

Exactly E4's fixed-chunk cells with the chunker swapped: `e4 --mode kept --chunker fixed-text`, the kept Task 8 call
sites, `CrossFileTaskGenerator.GeneratePlansFor` grouping by required chunk (now the text-first chunk holding the
declaration) with distractors and order drawn by the seed, E4's seed- and chunker-independent context order (hash of the
first task id) and E4's `--contexts` per cell (4 for seed 0, 2 for seeds 1–2). Because the chunk set differs, **the
distractor draw and so the contexts differ from E4's** even for the same seed and task; the comparison is paired by (corpus,
seed, task), not by context. Every job runs `drop_required`, so validity (full EM 1, EM 0 without the required chunk,
masked NLL gain ≥ ln 2) is re-applied per context for both chunkers.

Arms: `full`, `naive`, `drop_required`, `chunk_starts`, `query` (QR, ProphetKV-like, query = the task's ≤ 256-token prefix)
at 5 / 10 / 15 / 20 %; `graph`, `hybrid_query` and `random` at 10 / 20 % only (light arms, to fit the CPU budget). E4 ran
no `random` on fixed chunks, so Random has no id-slice counterpart. The control is E4's own rows
(`../E4-structure-aware/results.csv.gz`, chunker `fixed`, mode kept), scored by E4's functions (imported). Sets:
`text-valid` (all valid text-first instances), `slice-valid` (E4's 32), `slice-covered` (E4's valid instances whose task
and seed E4c ran), `matched-text` / `matched-slice` (valid under both, 21).

## Run

dotLLM `c4579f55` (0 dirty files in every job log), Release, CPU `TransformerModel`, F32 `SimpleKvCache`;
`bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF` @ `ae44f08e1392f39c0e474af10c3ff8355c8b6688` (Q4_K_M, 2,497,280,736 bytes);
AMD Ryzen AI MAX+ 395, Windows 11 Pro 10.0.26200, .NET SDK 10.0.401; corpora = the Task 8 snapshots, fixed-text-512
chunk-id hashes enforced. CPU only (GPU busy; no T5500), at most 8 threads.

- Started as 2 jobs × 4 threads (19:40 UTC); after 11 min the full prefill was 81 s per job against 30 s for one 8-thread
  job alone (≈ 0.74× the throughput), so the queue was stopped and restarted as **1 job × 8 threads** (19:51). The
  resumable output kept AFClaude seed 0 context 0 (10.6 min counted); DocAgent seed 0's unfinished first context (~11 min)
  was lost and rerun. Caps were lowered to 22 min (seed 0) / 11 min (seeds 1–2) per job (a job starts no new context after
  its cap; contexts run to completion, so jobs overrun by up to one context).
- **Stopped at the ~2.5 h budget** (22:19 UTC, 2 h 40 min wall) after DocAgent seed 2. **Contexts run / planned: 15 / 24**:
  AFClaude 2/4, 2/2, 0/2 (seeds 0, 1, 2); codesharp 4/4, 2/2, 0/2; DocAgent 3/4, 1/2, 1/2. Truncation keeps a prefix of
  the same context order, so truncated cells hold a subset of E4's definitions. **Not run (9 contexts):** AFClaude seed 0
  p2–p3; DocAgent seed 0 p3, seed 1 p1, seed 2 p1; AFClaude seed 2 and codesharp seed 2 entirely. **10 of E4's 32 valid
  id-slice instances have no text-first counterpart** (AFClaude 2 + 5, codesharp 2, DocAgent 1); two of three corpora have
  only two seeds. AFClaude seed 0 also lost about one context to the restart (its p0 ran at 2 × 4 threads, 630 s, and those
  10.6 min counted against its 22-min cap). `logs/afclaude-fixed-text-s2-kept.log` holds only a provenance block: that job
  started at 22:19:36 and was stopped at 22:19:42, before it wrote a `.partial`. Times in `logs/queue.log`.
- **What can be resumed, and how to extend the capped cells.** Only **AFClaude seed 2 and codesharp seed 2** resume as-is
  (rerun `run.ps1`; it skips jobs whose CSV exists). The time-capped jobs (AFClaude seed 0, DocAgent seeds 0/1/2) ended
  normally at their cap, so `e4` **finalised** them (renamed `.partial` to `.csv`) and `run.ps1` skips them as complete. To
  extend one: rename its `raw/<job>.csv` back to `raw/<job>.csv.partial`; recreate `raw/<job>.csv.partial.done` with the
  line `key <RunKey>` (the job's configuration key as `E4Command.RunKey` builds it; it excludes `--max-minutes` and
  `--threads`) followed by one `<plan>,<minutes>` line per finished context; raise the job's cap in `jobs.csv`; rerun
  `run.ps1`. Or rerun those cells from scratch. Either way roughly 1.5–2.5 h of CPU for the 9 contexts.
- **Resume key limits:** the key covers the corpus hash and every row-changing option, but **not the model file hash or the
  dotLLM commit**. A resume across commits or models would not be refused; the provenance block `run.ps1` writes on every
  (re)start records both, so check it.
- **Corpus paths:** every job log's `--corpus` points at a session scratchpad (`…\Temp\claude\…\scratchpad\t8-corpus-*`),
  which will not last. The snapshots can be rebuilt exactly: `git archive <commit> src` of each source repo (commits in the
  provenance blocks and `run.ps1`), checked by the enforced fixed-text-512 chunk-id hash.
- Cost on this path (8 threads): a 1-task context 4.5–6.5 min, a 3–4-task context 11–21 min; QR probe ≈ 14 s per task;
  QR at 20 % ≈ 181 forwards / 22 s, ChunkStarts 5 forwards / 8 s.

**Resumability** (added for this run; dotLLM `8560d36a`): `e4` writes `<out>.partial` one whole context at a time (rows
flushed to disk, then the context index and the cumulative minutes appended to `<out>.partial.done`), resumes from it
(rows of unfinished contexts dropped; a configuration key must match), counts earlier minutes against `--max-minutes`, and
renames `.partial` to `<out>` when the job ends — including when it ends at its time cap (see above). Checked by a small job stopped by PID after its first context and
rerun: context 0 skipped, cumulative time carried (1.2 + 2.4 min), final CSV complete.

## Caveats

- **Small, clustered, truncated sample:** 23 valid text-first instances (14 tasks, 8 definition files), 21 matched; one
  DocAgent cluster (`DependencyCascade.cs`) holds 6 of the 21. The per-corpus AFClaude and DocAgent cells have 2–3 clusters
  (the bootstrap then has only a handful of distinct resamples), so `summary.md` prints their intervals as **n/a** (the CSVs
  keep the raw bounds). Only the pooled statements are worth reading. 9 of 24 planned contexts were not run (S4 above).
- **The pairs share only the task** (see S2 in the brief): the chunker swap changes the required chunk, the distractor draw,
  the order and the naive harm. Ids are almost identical between the two chunkers (round-trip census), so a chunker swap
  can only change where the cuts fall; this run cannot isolate that from the context draw. A same-context-text comparison
  is needed.
- **Non-inferiority is not shown:** the pooled QR difference is driven by two pairs and DocAgent's weight in the ratio of
  means (S1); the lower bounds admit losses up to 0.19–0.31 of the gap. The bar is at 0.96 as a point estimate with Wilson
  lower bound 0.79 — not met / not validated.
- **Round-trip rate is corpus- and tokenizer-specific** (S6): 1 failing cut in 2,518 on mostly-ASCII C# with Qwen3 at
  N = 512; no merge failures observed, none guaranteed.
- **Light arms:** Graph, Hybrid(QR) and Random at 10 / 20 % only; FirstK, Deviation and the oracles were not rerun.
- **Not run / open:** the spec's §5.11 extra arm (QR with the query placed **before** the context) — open for Phase I5;
  a second model.
- Exact match on one masked call is coarse; the NLL gap is the primary ranking (as in E4).

## Files

| file | content |
|---|---|
| `roundtrip.csv.gz`, `logs/roundtrip-*.log` | per chunk and chunker: decoded-text and file-range round trip, U+FFFD, length difference (`ChunkKvLab roundtrip`) |
| `run.ps1`, `jobs.csv` | job queue and driver (provenance block per log and per resume, chunk-id hash enforced; skips jobs whose CSV exists, so only unstarted or interrupted jobs resume — capped jobs need the manual steps under "Run") |
| `raw/*.csv` | the per-job CSVs written by `ChunkKvLab e4 --chunker fixed-text` |
| `summarize.py` | merges `raw/` with E4's id-sliced fixed rows → `results.csv.gz`, `curves.csv`, `pairs.csv`, `cross.csv`, `summary.md` (`uv run summarize.py`) |
| `logs/*.log` | job logs and `queue.log` |
