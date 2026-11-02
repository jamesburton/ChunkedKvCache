# E4c — text-first fixed chunks (wire-eligible) on the E4 arms

**Result in brief** (Qwen3-4B-Instruct-2507 Q4_K_M, CPU, 2K contexts, E4's kept call sites and context rules; 95 %
cluster-bootstrap CIs; full tables in `summary.md`):

- **E4's id-sliced chunks almost always survive the text round trip with this tokenizer.** Decoding each 512-id slice and
  re-tokenising the text alone gives the same ids for **3,970 of 3,972 chunks (0.05 % fail)**: 0 / 30 AFClaude, 2 / 176
  DocAgent, 0 / 3,766 codesharp. Both failures are slices ending **inside a multi-byte UTF-8 character** (the decoded text
  holds U+FFFD), in the one DocAgent file with non-ASCII text; **no failure comes from a BPE merge across a cut**. (Qwen3's
  pre-tokenizer splits at word / punctuation / whitespace classes, and merges never cross those splits.) Symbol chunks fail
  0 / 8,138 and text-first chunks 0 / 3,996 (by construction). The file-range text of an id slice fails 3 / 3,972 (its char
  offsets come from decoding, so the U+FFFD case also shifts the range). The whole-file and per-piece token counts are equal
  for all three corpora (12,687 / 75,636 / 1,530,303). So for Qwen3 the wire problem of fixed chunks is narrow; text-first
  cutting removes it entirely.
- **Text-first fixed chunks keep E4's quality within the CIs, with slightly lower point estimates for query relevance.**
  On the 21 instances valid under both chunkers (same task and seed, 12 tasks, 8 definition clusters), text-first minus
  id-sliced, share of the naive→full masked-call NLL gap recovered: **QR −0.01 / −0.05 / −0.04 / −0.05 at 5 / 10 / 15 /
  20 %** (20 %: 0.91 vs 0.96, CI [−0.19, +0.02]); Hybrid(QR) −0.08 [−0.21, +0.04] at 10 %, −0.03 [−0.18, +0.00] at 20 %;
  ChunkStarts +0.01 / −0.00 / −0.01 / +0.02 (CIs ∋ 0); Graph −0.01 / +0.03. Exact match at 20 %: QR and Hybrid 0.95 vs
  1.00 (one instance lost, 0 wins / 1 loss), ChunkStarts 0.95 vs 0.95; naive EM is higher with text-first chunks (0.67 vs
  0.52). No paired CI excludes 0 against the id slices, but the intervals admit QR losses up to 0.19 of the gap.
- **The 95 % / 20 % bar holds as a point estimate for text-first fixed chunks, just:** all valid text-first instances (n =
  23, 8 clusters, full EM 1 by construction): QR and Hybrid(QR) at 20 % EM **0.96** (22 / 23), gap 0.91 [0.83, 0.99] /
  0.93 [0.83, 1.01]; matched set 0.95 (20 / 21), exactly at the bar. E4's id slices: 1.00 (32 / 32). Per corpus it fails
  on DocAgent (QR 20 % 0.88, 8 instances, 2 clusters) and holds on AFClaude and codesharp.
- **Within E4c the E4 ranking repeats:** QR > ChunkStarts at every budget (+0.14 to +0.28 of the gap, CIs > 0), Graph < QR
  at 10 / 20 % (−0.15 [−0.28, −0.07], −0.11 [−0.47, −0.02]), Hybrid(QR) ≈ QR (+0.01, +0.02 [0.00, 0.03]); Random (control)
  recovers only 0.09 / 0.15 at 10 / 20 %.
- **Answer:** text-first fixed chunks (`fixed-text-512` ≈ the spec's `lines-512`) match the id-sliced quality within the
  CIs of this small, truncated sample, and meet the bar for QR at 20 % as a point estimate (0.96). By the spec's §5.11 rule
  that makes them wire-eligible, with the caveats below (n = 21–23 in 8 clusters, negative QR point estimates, DocAgent
  below the bar, 15 of the 24 planned contexts, and the "query before context" arm not run).

Data: `cross.csv` (paired text − slice), `curves.csv` (sets `text-valid|…`, `slice-valid|…`, `matched-*|…`), `pairs.csv`.

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
- Otherwise binary-search the furthest code-point boundary whose piece tokenises to ≤ 512 ids (each probe tokenises the
  candidate piece alone; only probed pieces that fit are accepted, so the bound holds even where token count is not monotone
  in length).
- Cut at the **last line end** inside that piece (the furthest one whose piece fits); with no line end, cut at that character
  boundary, moved back so that it never splits a surrogate pair (a 4-byte UTF-8 sequence; BMP characters are whole UTF-16
  chars) or a `\r\n`.
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
15/15 in round 2 (dotLLM `c4579f55`).

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
  the same context order, so truncated cells hold a subset of E4's definitions; AFClaude and codesharp seed 2 are missing
  entirely. Both are resumable (`run.ps1` skips finished jobs). Times in `logs/queue.log`.
- Cost on this path (8 threads): a 1-task context 4.5–6.5 min, a 3–4-task context 11–21 min; QR probe ≈ 14 s per task;
  QR at 20 % ≈ 181 forwards / 22 s, ChunkStarts 5 forwards / 8 s.

**Resumability** (added for this run; dotLLM `8560d36a`): `e4` writes `<out>.partial` one whole context at a time (rows
flushed to disk, then the context index and the cumulative minutes appended to `<out>.partial.done`), resumes from it
(rows of unfinished contexts dropped; a configuration key must match), counts earlier minutes against `--max-minutes`, and
renames `.partial` to `<out>` when the job ends. Checked by a small job stopped by PID after its first context and
rerun: context 0 skipped, cumulative time carried (1.2 + 2.4 min), final CSV complete.

## Caveats

- **Small, clustered, truncated sample:** 23 valid text-first instances (14 tasks, 8 definition files), 21 matched; the
  per-corpus cells have 2–4 clusters, so per-corpus CIs are degenerate (AFClaude's paired gap intervals with 2 clusters
  are not meaningful). Only the pooled statements are worth reading. 9 of 24 planned contexts were not run.
- **The chunker swap also changes the contexts.** Ids are almost identical between the two chunkers (round-trip census), so
  the differences measured here come from where the cuts fall (line ends, chunks of ~500 instead of 512 tokens, different
  required chunk) and the resulting different distractor draws, not from tokenisation. Naive harm differs between the two
  matched sets (naive EM 0.67 vs 0.52), which changes the gap denominators.
- **QR point estimates are negative** (−0.04 to −0.05 from 10 %), the matched set loses one exact match at 20 %, and
  DocAgent alone is below the bar. A small QR loss for text-first chunks is not ruled out.
- **Light arms:** Graph, Hybrid(QR) and Random at 10 / 20 % only; FirstK, Deviation and the oracles were not rerun.
- **Not run:** the spec's extra arm (QR with the query placed **before** the context, §5.11) and a second model.
- Exact match on one masked call is coarse; the NLL gap is the primary ranking (as in E4).

## Files

| file | content |
|---|---|
| `roundtrip.csv.gz`, `logs/roundtrip-*.log` | per chunk and chunker: decoded-text and file-range round trip, U+FFFD, length difference (`ChunkKvLab roundtrip`) |
| `run.ps1`, `jobs.csv` | job queue and driver (provenance block per log and per resume, chunk-id hash enforced, resumable) |
| `raw/*.csv` | the per-job CSVs written by `ChunkKvLab e4 --chunker fixed-text` |
| `summarize.py` | merges `raw/` with E4's id-sliced fixed rows → `results.csv.gz`, `curves.csv`, `pairs.csv`, `cross.csv`, `summary.md` (`uv run summarize.py`) |
| `logs/*.log` | job logs and `queue.log` |
