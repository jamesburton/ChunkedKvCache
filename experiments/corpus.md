# Code corpora for chunk-KV reuse (Task 8)

Three C# repositories from `C:\Development`, frozen with `git archive`, chunked by the Roslyn symbol chunker and turned into
cross-file completion tasks (dotLLM `src/DotLLM.ChunkReuse/Corpus`, lab command `ChunkKvLab tasks`). Task generation and the
validity filter are described below; the run script is `corpus/run.ps1`, raw outputs are in `corpus/`.

## Selection criteria

- C#, non-test source only (test/benchmark projects, generated code, `bin/`, `obj/` excluded by the loader).
- Different shape and size: at least one corpus many times larger than a 32K context, and one small enough to fit in a single
  32K context.
- Different from E1/E2's corpus (dotLLM `src` @ `4a781829`), so E4 is not tuned to one codebase. dotLLM stays available.
- Enough **resolvable** cross-file call sites. Resolution uses one Roslyn compilation per corpus with BCL-only metadata
  references (plus the SDK's implicit global usings), so calls on third-party types do not resolve and are skipped. This
  turned out to be the binding constraint for small repos (see "Rejected").

## Chosen corpora

Token counts are Qwen3-4B-Instruct-2507 tokens (the GGUF's own BPE tokenizer), symbol chunker with a 512-token limit.
`Decode(Encode(file)) == file` held for every file of every corpus, so chunk line/offset mapping is exact.

| role | repo (path) | commit (frozen) | dirty at freeze | archived | files kept | chunks | tokens | × 32K | chunk-id sha256 (symbol-512) |
|---|---|---|---|---|---:|---:|---:|---:|---|
| large | `C:\Development\codesharp` | `8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2` (main) | 0 files | `src` | 1390 | 7586 | 1,535,738 | 46.9 | `bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb` |
| medium | `C:\Development\CSharpDocAgentFrameworkMCP` | `6683823880bc2a7d62708907c725d9eaedf3a016` (main) | 0 files | `src` | 55 | 478 | 76,017 | 2.3 | `5d7e4560f8fea99d4b076d95e4ff4dcb0271f4572a3a0f6e1117eff00d4346c7` |
| small (fits one context) | `C:\Development\AFClaude` | `b3f29c30a2e25b3053d1d9adc8eb4068cde1ca2c` (main) | 1 untracked dir `.docs/` (no `.cs`) | `src` | 9 | 74 | 12,744 | 0.39 | `2601bb059c4f2cf9ae2ad558e0824a04086e5bab24c3771efe9405826545a938` |

Freeze: `git -C <repo> archive <commit> src | tar -x -C <fresh dir>` into new, uniquely named directories under the session
scratchpad (`t8-corpus-<repo>-<commit8>-20261101111016` / `-20261101111141`); nothing was deleted. The lab checks the hash
(`--expect-hash`) and refuses to run on a different snapshot. Re-create a snapshot with the same command; the hash proves it.

Chunk sizes (symbol-512): median 157 / 105 / 107 tokens (codesharp / DocAgent / AFClaude), max 512 / 511 / 510.

### Call-site census (`CallSiteCounts`, BCL-only resolution)

| corpus | invocations | unresolved (skipped) | BCL / delegate / local | same file | **cross-file usable** | distinct definition chunks |
|---|---:|---:|---:|---:|---:|---:|
| codesharp | 20,040 | 4,007 | 10,351 | 3,123 | **2,559** | 1,181 |
| DocAgent | 2,241 | 398 | 1,474 | 242 | **127** | 47 |
| AFClaude | 327 | 124 | 142 | 31 | **30** | 14 |

No call site was dropped for a duplicate definition (CS0101/CS0111 in the merged compilation) or for an unmaskable callee.

### Rejected candidates

- **AspireKitchenSink** (`8151ed30`, ~8.5K tokens, would fit a context): only **3** usable cross-file call sites (2 definition
  chunks). Nearly every cross-file call is an extension method on an Aspire builder type, which does not resolve with
  BCL-only references; 267 of 293 invocations are unresolved. Replaced by AFClaude as the small corpus.
- **LEANN.Net**, **DnxTools**: no tracked `.cs` files at HEAD (the `.cs` files on disk are untracked), so they cannot be frozen
  with `git archive`.
- **dotLLM `src`**: already the E1/E2 corpus; kept out so the task corpora differ from it.

Fixed-512 chunking of the same snapshots (`corpus-info --chunker fixed`, file tokenised once, tail kept; `corpus/corpus-info.log`):

| corpus | chunks | tokens | chunk-id sha256 (fixed-512) |
|---|---:|---:|---|
| codesharp | 3766 | 1,530,303 | `cde11b22a9d64764f3043bf1d7be6035190465e8d4ec03a7c22e765faa19dceb` |
| DocAgent | 176 | 75,636 | `8d083a63d5c1db7514596aec9bdabf880695ded868a45459f6c8be21a354f2b4` |
| AFClaude | 30 | 12,687 | `b90ef5fa2bbaae8fafbc08c27d19d8259465898c412609e7c31e06076f69cbb6` |

Symbol chunks cost 0.3–0.5 % more tokens than one tokenisation of the file (each chunk is tokenised on its own).

## Tasks

**Generator** (`CrossFileTaskGenerator`, defaults used here): mask a call site's callee name and arguments; the **required chunk**
is the chunk holding the callee's declaration (identifier position) in a **different** file, found with the Roslyn semantic
model (unresolved, ambiguous-overload, BCL, delegate and same-file calls are skipped, never guessed). A **plan** = one assembled
context + up to 4 tasks that share the required chunk (call sites of the same definition, from files outside the context), so
E4 can average over several continuations per context. Context = required chunk + seeded distractors up to **2048 tokens**
(≈ 14–17 chunks); distractors never come from a calling file, never contain a masked call's text, and never declare a member
of the callee's name. Query (prefix) = `// <path>` + whole calling-file lines up to the mask, ≤ **256 tokens**; expected
continuation = **32 tokens** of the original text. The query window is tokenised once and split at the last token boundary
at or before the callee name: Qwen's pre-tokenizer glues `.`/space to the identifier (`.TryGet`), so the mask includes it.
Splitting exactly at the name would teacher-force a token sequence the joint text never produces (before this fix only 0–8 %
of tasks tokenised consistently; after it 229/229). Every task records prefix, expected continuation, required and distractor
chunk ids, the mask token offset (relative to the query and absolute in the context) and the mask length. Deterministic per
seed (seed 0 here).

**Validity filter** (`TaskValidator`, Boxoffice-style B0/NC): full prefill of the context **with** and **without** the required
chunk, teacher-forced continuation. Keep a task only if (1) the reference reproduces the masked call greedily with the chunk
(drops B0), (2) it does not without it (drops NC), and (3) the masked-call NLL falls by ≥ ln 2 nats (the call is at least 2×
as likely with the definition). Greedy exact match is read from the teacher-forced argmaxes (identical to greedy decoding for
an exact match). Raw per-task scores are in `corpus/<name>.validation.csv`, so other criteria can be recomputed.

**Reference run** (dotLLM `4e558849`, CPU, Qwen3-4B-Instruct-2507 Q4_K_M @ `ae44f08e`, 2026-11-01; `corpus/summary.md`):

| corpus | tasks generated | validated | ref. EM with chunk | ref. EM without | mean mask NLL with / without (nats) | **kept** | reference fails | solved without | below margin |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| AFClaude (small) | 29 of 30 cross-file sites (13 definition chunks) | 29 | 69 % | 14 % | 4.85 / 10.71 | **16 (55 %)** | 9 | 4 | 0 |
| DocAgent (medium) | 100 | 100 | 41 % | 13 % | 6.89 / 13.01 | **27 (27 %)** | 59 | 13 | 1 |
| codesharp (large) | 100 | 87 (53 of 60 plans; time cap) | 38 % | 15 % | 7.57 / 15.10 | **21 (24 %)** | 54 | 12 | 0 |

Kept tasks cover 9 / 17 / 21 distinct definition chunks in 10 / 17 / 21 contexts. Median masked-call NLL gain of kept tasks:
6.9 / 4.3 / 7.4 nats. The reference solves 38–69 % of tasks with the chunk, so the task set is neither trivial nor impossible
and no difficulty retune was needed. The required chunk matters: removing it cuts exact match to 13–15 % and doubles the
masked-call NLL. 13–15 % of tasks are answerable without the chunk; they are dropped. Of those 29 solved-without tasks, the
callee name already appears in the prefix in 17, in a distractor chunk in 0, and in neither in 12 (a guessable name).
Mean continuation NLL per token (divided by each task's actual continuation length; 1 / 1 / 8 tasks are shorter than 32
because they reach the end of the file) with / without the chunk: 1.331 / 1.560, 1.027 / 1.222, 1.457 / 1.749 nats.

**Cost:** one plan (2K context, 1–4 tasks) takes 28.8–48.9 s (AFClaude), 30.7–64.6 s (DocAgent) and 31.2–76.8 s (codesharp) on
CPU (mean 35.5 / 45.2 / 42.9 s); the first measured plan (2 tasks)
took 44 s. Total model time 84.1 min (9.5 + 36.3 + 38.3). The codesharp run was capped at 38 min and stopped after 53 of 60
plans (87 of 100 tasks validated). The 13 unvalidated tasks are in `codesharp.plans.jsonl` (plans 53–59).

**For E4:** use the kept tasks (`Keep == 1` in the validation CSVs) and report scores normalised by the full-prefill reference.
AFClaude yields only 29 usable call sites in total (2 calling files), so its kept set is small (16); DocAgent's 100 tasks come
from 14 calling files. Plans can be regenerated at larger context sizes with the same seed; task ids (`path:line:col`) are
seed- and size-independent, so the kept set can be carried over (validity was established at 2K).
- Exact match (and the masked NLL) covers only the masked call tokens (`MaskTokenCount` from `MaskTokenOffset`), not the rest
  of the 32-token continuation.
- For zero-argument methods the masked text (e.g. `.Build()`) can occur verbatim inside the required chunk itself (its
  declaration or a recursive/sibling call); this holds for 6 kept tasks. That is a legitimate copy from the required chunk,
  not a leak from a distractor, but E4 should know such tasks are copy-style.

Reproduce one corpus: extract `git archive <commit> src` of the repo into a fresh directory `D`, then from `experiments/corpus`:
`./run.ps1 -Name codesharp -Corpus D -SourceRepo C:\Development\codesharp -CorpusCommit 8e2adbd82a50ce3a847f5b3eba6651d1dbe41bc2 -ExpectHash bf397403250ae02d840de51e004c46a7a2e38ef59e41edd80e41e30a865df1fb -MaxMinutes 38`
(DocAgent and AFClaude: their commit and hash from the table above, no `-MaxMinutes`).
