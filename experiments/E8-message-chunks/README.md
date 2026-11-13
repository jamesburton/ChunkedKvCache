# E8: message-level chunk reuse after a system-prompt / tool-list edit (design; not run yet)

Tracks dotLLM#1782. Library harness only (extend `ChunkKvLab` on the kept `chunk-cache` worktree; NOT the server, no
`PrefixCache` / `TextGenerator` / trie / snapshot changes). Dense models only. Needs `cpu-bench` (Qwen3-4B-Instruct-2507
Q4_K_M, the E4-E4c model) and TwIL-8B (dense Granite; check `LLMs.md` for the runnable quant).

## Question
Chat history is reused when the prefix cache misses because the system prompt or tool list changed. Each message chunk was
encoded under the OLD prefix. After a position shift (RoPE re-rotation, exact: E1/E2 floor 0) how much of full-prefill
quality does selective recompute at 5 / 10 / 20 / 40 % recover, and does the E4c bar (EM >= 0.95 x full at 20 %) hold?

## Why E4-E4c do not answer it
They replace/reorder stale code-context chunks under an UNCHANGED instruction prefix. Here the whole prefix changes, so
every message chunk is stale (not only its start), and assistant turns encode the old system prompt / tool list.

## Design
- Transcripts: real multi-turn agent runs (system prompt + tool list + user / assistant / tool-result messages), 6-12
  turns, taken from the AFClaude / DocAgent / codesharp corpora tasks (E4's call sites), 2-8K tokens. Chunks = one per
  message at template-token boundaries (sub-chunk > 512 tokens with the text-first lines-512 chunker).
- Edit conditions (the prefix change): E-sys-small (one sentence changed), E-sys-large (rewritten), E-tools (a tool added
  / description changed / list reordered), E-none (control: unchanged prefix, must be lossless).
- Arms at each budget 5/10/20/40 %: naive (no recompute), chunk-starts, query-relevance (QR), Hybrid(QR) as in E4; plus
  random control; full prefill = reference.
- Metrics: NLL / KL of the next assistant turn (or the masked call, as E4), exact-match of the produced tool call vs full,
  share of the naive-to-full gap recovered, cluster bootstrap by transcript source (as E4).
- TTFT cost check (separate, `cpu-bench` quiet): wall time of re-rotate + selective recompute vs plain prefill at 2 / 4 / 8K,
  CPU and (later, `gpu`) Vulkan F16.
- Pass bar (same as E4c): lower 95 % bound of EM >= 0.95 x full at <= 20 %, >= 30 valid instances; otherwise report the
  budget at which it holds. The policy stays opt-in regardless.

## Open before running
1. Transcript source: record fresh runs (TwIL / Qwen3 on the corpora) vs synthesize from corpus tasks. Recommend recording
   with the exact model so assistant turns are on-distribution.
2. Confirm `ChunkKvLab` has what is needed (E4 arms and selectors exist; a `transcript` context builder is new code).
3. Do not mix with E4 data; new `jobs.csv` and provenance block as in E4c `run.ps1`.
