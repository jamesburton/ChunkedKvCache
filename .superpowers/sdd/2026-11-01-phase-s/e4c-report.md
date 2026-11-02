# E4c report — text-first fixed chunks

**Status: DONE_WITH_CONCERNS** (run truncated by the time budget at 15 of 24 planned contexts; small clustered sample;
negative QR point estimates; the spec's "query before context" arm not run).

## Commits

dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-kv-reuse` (branch `feature/chunk-kv-reuse`, not pushed):

- `8560d36a` ChunkReuse: `TextFirstFixedChunker` (fixed-text-512), lab `roundtrip` command, `e4 --chunker fixed-text`,
  resumable `.partial` output for `e4`.
- `c4579f55` TextFirstFixedChunkerTests: tests killing the round-1 surviving mutants. (All E4c jobs ran at this commit,
  0 dirty files.)

ChunkedkvCache: `experiments/E4c-text-first-chunks/` (README, run.ps1, jobs.csv, summarize.py, raw/, logs/, results,
curves, pairs, cross, roundtrip census) and this report + `e4c-mutants.log` (commit hash in the final message to the
controller; not pushed).

## Tests

- `tests/DotLLM.Tests.Unit/ChunkReuse/TextFirstFixedChunkerTests.cs`: 21 tests, written first (red build: CS0246). Properties:
  concatenation to the file with consistent offsets/lines; each piece alone ≤ N; ids == piece tokenised alone (round trip)
  and decode back; greedy last-line-end cut; line end preferred over a fuller char cut; over-long line cut at the last char
  that fits; no split UTF-8 sequence / surrogate (byte tokenizer, 2/3/4-byte chars, several N); CRLF preserved and never
  split; deterministic; char longer than N throws; id slicing fails the round trip where text-first does not; rest of exactly
  N is one chunk; rest of N+1 cut after N; non-monotone token counts never yield a piece > N.
- ChunkReuse suite 257/257 green.
- Mutation (git-archive scratch copy, never the live worktree): 15 mutants. Round 1: 11 killed (T11 by non-termination —
  its test host hung and was stopped by PID), T6 did not compile, T7/T14/T15 survived. Round 2 with three added tests and T6
  rewritten: 15/15 killed. Log: `e4c-mutants.log`.
- Real-tokenizer invariants (`ChunkKvLab roundtrip`, Qwen3 tokenizer, all three corpora): concatenation, ≤ 512, no lone
  surrogate — no violations.
- Resume check of `e4`: a small job stopped by PID after context 0 and rerun skipped context 0, carried its minutes and
  produced a complete CSV.

## Numbers

**Round trip (tokenizer only, CPU, 1.4 min):** id-sliced 512 chunks fail the decoded-text round trip in **2 / 3,972 (0.05 %)**
— AFClaude 0/30, DocAgent 2/176 (1.1 %), codesharp 0/3,766. Both failures: slice ends inside a multi-byte UTF-8 character
(U+FFFD), mismatch confined to the first/last 3 ids. Zero failures from BPE merges at cuts. Symbol chunks 0/8,138;
fixed-text 0/3,996. File-range text of id slices: 3/3,972.

**Quality (E4 fixed arms with text-first chunks, CPU, 1 × 8 threads):** 29 instances run, 23 valid (14 tasks, 8 clusters);
21 matched with E4's valid id-slice instances (same corpus, seed, task).

| matched (n = 21, 8 clusters), gap recovered | text | slice | text − slice [95 % CI] | EM text / slice |
|---|---:|---:|---|---|
| QR 5 % | 0.83 | 0.84 | −0.01 [−0.08, +0.14] | 0.95 / 0.90 |
| QR 10 % | 0.84 | 0.90 | −0.05 [−0.26, +0.04] | 0.86 / 0.90 |
| QR 15 % | 0.89 | 0.93 | −0.04 [−0.31, +0.05] | 0.90 / 0.95 |
| QR 20 % | 0.91 | 0.96 | −0.05 [−0.19, +0.02] | 0.95 / 1.00 |
| Hybrid(QR) 10 / 20 % | 0.80 / 0.92 | 0.88 / 0.95 | −0.08 [−0.21, +0.04] / −0.03 [−0.18, +0.00] | 0.86 / 0.90, 0.95 / 1.00 |
| ChunkStarts 5 / 10 / 15 / 20 % | 0.75 / 0.76 / 0.85 / 0.87 | 0.73 / 0.76 / 0.85 / 0.85 | +0.01 / −0.00 / −0.01 / +0.02 (CIs ∋ 0) | 0.95 / 0.81 at 5 %; equal at 15–20 % |
| Graph 10 / 20 % | 0.72 / 0.87 | 0.73 / 0.84 | −0.01 / +0.03 (CIs ∋ 0) | |
| naive EM | 0.67 | 0.52 | | |

- **95 / 20 bar:** QR (and Hybrid) at 20 % EM 22 / 23 = 0.96, Wilson 95 % [0.79, 0.99] (matched 20 / 21 = 0.95 [0.77,
  0.99]; DocAgent alone 7 / 8 = 0.88; E4 id slices 32 / 32 [0.89, 1.00]). **At the bar as a point estimate; NOT met / not
  validated.**
- **What drives the pooled QR −0.05 (review S1):** a ratio of means with DocAgent at 72–78 % of the gap denominator;
  per-instance mean +0.01 (median −0.02), text-first worse in 11 of 21; two pairs carry it — DocAgent s0
  `SolutionIngestionService.cs:313:40` 0.43 vs 0.97 (the only EM loss) and AFClaude s1 `FoundryTools.cs:23:48` 0.42 vs 0.93
  (verified by my recomputation).
- **Pairing is nominal (S2):** chunks per context differ in 19 / 21 pairs, `required_first` in 7 / 21; the pairs share only
  the task. A same-context-text comparison is needed.
- **Round trip (S6):** the 2 failures are two sides of one cut: 1 failing cut in 2,518; no BPE-merge failure observed, not
  guaranteed; corpus/tokenizer/N-dependent.
- Within E4c: QR > ChunkStarts at every budget (+0.14 to +0.28, CIs > 0); Graph < QR at 10 / 20 % (−0.15, −0.11, CIs < 0);
  Hybrid ≈ QR; Random 0.09 / 0.15 of the gap at 10 / 20 %.
- Coverage (contexts run / planned): AFClaude 2/4, 2/2, 0/2; codesharp 4/4, 2/2, 0/2; DocAgent 3/4, 1/2, 1/2 (seeds 0/1/2):
  9 of 24 not run; 10 of E4's 32 valid instances uncovered.

**Verdict (controller's ruling, README "Implications"):** wire eligibility of `lines-512` is granted on correctness grounds
(round-trips by construction: 0 / 3,996, 15 / 15 mutants). Quality is **not validated**: no difference detected, but
non-inferiority not shown; `auto_validated` stays empty. Validation moves to Phase I5: non-inferiority margin (lower CI
bound of text − slice gap at QR 20 % ≥ −0.10, ≥ 30 valid instances), the 9 missing contexts, a same-context comparison and
the query-before-context arm. Task 19 comes after Task 5b (ruling 21: the chunker's size probes must use
`EncodeRaw(MarkUntrustedSpecials(text))` too; codesharp `CompactionSummaryValidation.cs:57` holds `<think>` spellings, so
its chunk, the pinned hashes and the census change after 5b).

## Review fix round (docs only, no model runs)

Addressed `review-e4c-report.md` S1–S6, S8 and nits N1, N3–N8 in `experiments/E4c-text-first-chunks/README.md`, the
`run.ps1` header comment (the false "resumable" claim: capped jobs are finalised and skipped; only AFClaude s2 and
codesharp s2 resume as-is; manual extension procedure documented) and `summarize.py` (summary.md prints n/a for intervals
of sets with fewer than 4 clusters; curves/pairs/cross CSVs regenerate byte-identically). S7 is recorded under
Implications (no code change here; Task 5b). N2 (quadratic probing) and N4 (iteration guard) are noted as follow-ups for
the server-side port.
## Concerns

1. **Truncated:** 15/24 contexts; AFClaude and codesharp seed 2 not run at all (resumable as-is); the four capped cells need the manual extension in README "Run".
   Wall 2 h 40 min (19:40–22:19 UTC), ~10 min over the 2.5 h target to let DocAgent seed 2's first context finish.
2. **Restart mid-run:** the queue started as 2 × 4 threads, which proved slower (full prefill 81 s vs 30 s at 1 × 8);
   it was stopped after 11 min and restarted at 1 × 8 threads (one unfinished DocAgent context, ~11 min, was lost and rerun;
   AFClaude's finished context was kept by the resume path). Caps were lowered then (22 / 11 min). Recorded in `logs/queue.log`.
3. **Confound:** the chunker swap changes the contexts (different chunk boundaries → different required chunk and distractor
   draw), and the ids are near-identical anyway, so the measured differences are about cut placement/contexts, not
   tokenisation. Naive harm differs between the matched sets (EM 0.67 vs 0.52).
4. **Small n, few clusters:** per-corpus CIs degenerate (2–4 clusters); ~80 paired cells reported with no multiplicity
   adjustment.
5. **Light arms:** Graph/Hybrid/Random at 10/20 % only; Random has no E4 fixed counterpart.
6. **Not run / open:** the spec's §5.11 extra arm (QR with the query placed before the context) — open for I5; a second model.
7. The `e4` command itself still has no unit test (as in E4/E4b); its resume path was checked by a manual interrupt/rerun.

LLMs.md: one appended note on the Qwen3-4B-Instruct-2507 row (round-trip rate, text-first quality, 2×4 vs 1×8 throughput).
