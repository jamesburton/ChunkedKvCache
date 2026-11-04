# e2e-chunkcache: Phase I5 Part A

First scripted end-to-end run of the chunk cache as it exists on `feature/chunk-cache-server`: CLI-built store ->
`dotllm serve --chunk-cache` -> annotated OpenAI / Anthropic requests, on the real Qwen3-4B-Instruct-2507 Q4_K_M
(bartowski, HF revision `ae44f08e`). **No request reuses K/V yet** (applied reuse is Part B). Plan:
`docs/superpowers/plans/2026-11-03-phase-i5-applied-reuse.md`.

Pins: server `S_A` = `feature/chunk-cache-server` `ea2279cf` (Task 16 accepted); client `C_A` = `feature/chunk-cache-client`
`5f003693` (PR #1547 head); both built from `git archive` exports under `C:\Development\dotLLM-e2e\` (nothing built in a
live worktree). **KV note:** this server branch does not contain dev's F16-default Vulkan KV (PR #1597); on Vulkan its KV is
F32 (capabilities report `kv_dtype f32`). V1-V3 behaved as the plan expects, so no workaround was needed.

Files: `run.ps1` (orchestration), `e2e.py` (stdlib driver + checks), `test_e2e_checks.py` (self-test, no model),
`mutants.py` (runs the 8 mutants against the self-test), `ClientSmoke/` (A7), `repro_a11_hang.py` (one hang-repro attempt).

## Run

```
pwsh run.ps1 -Backend cpu    -ServerCommit ea2279cf -ClientCommit 5f003693 -Model <gguf>   # A0-A12 plus A3g, A4b, A6m, A0r, A10r
pwsh run.ps1 -Backend vulkan -ServerCommit ea2279cf -ClientCommit 5f003693 -Model <gguf> -StoreFrom <cpu run id> -Only V1,V2,V3,VOH
python -I experiments/e2e-chunkcache/test_e2e_checks.py ; python experiments/e2e-chunkcache/mutants.py   # self-test, then mutants
```

Locks are held by the caller (ResourceLock `cpu-bench`; Vulkan: `gpu` plus `scripts/gpu-lock.sh`). The driver passes
`--device cpu|vulkan` explicitly and aborts when `/v1/chunk-cache` reports another backend (`dotllm serve` defaults to
`--device auto`, which is Vulkan on this box: our first run silently ran on the GPU, finding F-A0).

## Results (CPU run `results/20261104-cpu`, 913 s wall; Vulkan run `results/20261104-vulkan`, 83 s)

| check | CPU | Vulkan | evidence |
|---|---|---|---|
| A0 CLI build (10 chunks, 1,555 tokens, 28 s) | PASS | | `20261104-cpu/evidence/A0-build.json` |
| A1 flag off (404, no `chunk_cache`, same token ids) | PASS | | `checks/A1.json` |
| A2 capabilities | PASS | | `evidence/A2-capabilities.json` |
| A3 shadow, plan layout (one header per file) | **FAIL (F-A1)**: 12/12 `chunk_template_altered` | | `evidence/A3-response-report.json` |
| A3g shadow, header before every chunk | PASS (hit 8, miss 4, per-chunk status = `select` stored) | | `evidence/A3g-response-report.json` |
| A4 exact neutrality (blocking and streaming, cold plain baseline) | PASS | V1: PASS | `20261104-cpu-a4cold/evidence/A4-*.json` |
| A4b same on `--no-paged` (warm-slot prefix cache) | PASS | | `20261104-cpu-a4cold/evidence/A4b-*.json` |
| A5 strict / non-strict hash mismatch | PASS | | `checks/A5.json` |
| A6 Anthropic inline parts | **FAIL (F-A2)**: 3/3 `chunk_template_altered` | | `evidence/A6-report.json` |
| A6m Anthropic manifest over one string message | PASS (same counts as A3g) | | `evidence/A6m-report.json` |
| A7 ClientSmoke (C_A client) | PASS (hit 8, miss 4) | | `evidence/A7-smoke-output.json` |
| A8 server write, 2 sightings | PASS (queued 719 = F3 tokens; entries 10 to 14; third request hit 4/4) | V3: PASS | `evidence/A8-requests.json` |
| A9 server entries equal CLI entries | PASS (names and bytes equal, 4 files) | | `checks/A9.json` |
| A10 prewarm / evict / forget, plan fixture | **FAIL (F-A3, plan expectation)**: `kept_referenced 4` | | `evidence/A10.json` |
| A10r same, CLI index covering F1+F2 only | PASS (`evicted 4`, 212 MB freed) | | `evidence/A10r.json` |
| A11 auth and namespace isolation | PASS | | `evidence/A11.json` |
| A12 metrics (ro, write, auth servers) | PASS | | `evidence/A12-metrics-*.txt` |
| V2 Vulkan shadow vs CPU store | | PASS (hit 0, miss 12) | `20261104-vulkan/evidence/V2-report.json` |
| VOH Vulkan exact overhead | | -0.2 ms median (15 pairs) | `20261104-vulkan-voh15/checks/VOH.json` |

Vulkan exact overhead (server `prompt_ms`, annotated `exact` minus plain, alternating, ~2.7K-token prompt, F32 KV):
**-0.2 ms median over 15 pairs** (mean -2.0 ms; stdev 6-10 ms; plain 1,355-1,389 ms). The two 5-pair runs gave -5.4 and
+5.9 ms, so the 5 ms target (spec 12.5) cannot be resolved below the run-to-run noise on this box; 15 pairs is within it.

## Findings (owner)

- **F-A1 (chunker, Phase S symbol-512 / Task 19 `lines-512`; the server's verification is correct):** a symbol-512 chunk
  often starts with the blank line the previous chunk's last newline belongs with (a closing-brace line, then a line that
  starts with `///`). Shown back to back, as a harness reading a file would, Qwen's tokenizer merges the two newlines across
  the edge, the token check fails, and the server rightly reports `chunk_template_altered`: in our fixture all 12 annotated
  chunks were ignored (attribution ignores the first and last unproven span, so one broken edge costs a whole file). A header
  ending in a digit before each chunk avoids it (A3g). Real harnesses need token-stable chunk edges or per-chunk glue; ties
  into E4c.
- **F-A2 (Anthropic converter join rule x chunker):** inline text blocks are joined with a newline; a chunk ending in a
  newline or punctuation merges with the joiner, so every inline chunk was `chunk_template_altered` (A6). A manifest over a
  string message works (A6m). Needs a joiner-aware chunker or a documented rule for Anthropic harnesses.
- **F-A3 (plan, not a defect):** `chunkcache build --directory` indexes the whole tree, so server-written entries for any
  indexed chunk are index-referenced and `evict mode=path` keeps their files (`kept_referenced`), as `docs/CHUNK_CACHE.md`
  describes. The plan's A10 expectation (F3 files removed) holds only if the CLI index does not cover F3 (A10r).
- **F-A0 (operator trap):** `dotllm serve` defaults to `--device auto` = Vulkan on this box; a CPU-built store served that
  way is all misses (the backend is in the key), silently. A first run therefore used the GPU without the `gpu` lock (about
  5 min of short prefills, no incident); the driver now names the device and checks the backend.
- **Docs drift:** `docs/CHUNK_CACHE.md` says the default paged path has no cross-request prefix reuse; this build logs
  "paged KV-cache (q8_0 blocks) with cross-request prefix cache" and restores 2,672 of 2,676 tokens on a repeat.
- **Unexplained, unreproduced:** in a first draft of A11 a K_B shadow request (identical prompt to 14 earlier K_A probes,
  auth + writer CPU server) never completed (server log: `req#18 cancelled (client disconnected) after 36m45s`). One attempt
  to reproduce it (`repro_a11_hang.py`: 24 probes, then K_B) returned in 0.9 s, and with distinct probe prompts it did not
  recur. Excerpt: `20261104-cpu/evidence/r2-a11-hang-server-log-excerpt.txt`. Owner if it recurs: Task 10-15 request path.
- **Observations:** with an identical prompt the prompt cache restores it whole and chunks are reported `prefix`, not `hit`
  (by design; A8 and A11 probes use distinct system messages). Chunk counts differ from the plan's guess: F1+F2 are 10 chunks
  (plan: 3-8) because the plan's F1/F2 (`ChunkKey.cs`, `ChunkNamespace.cs`) hold 11 + 4 chunks and 3 are shorter than
  `min_chunk_tokens`; the fixture uses F1 `ChunkNamespace.cs`, F2 `IChunkStore.cs`, F3 `ChunkStoreBusyException.cs`,
  F4 `StoreStats.cs` (prompt ~2.7K tokens) and annotates only chunks of at least 32 tokens.

## Verdict

The wire, store, writer and control plane work end to end on the real Qwen3-4B: CLI-built entries are hits on the server,
server-written entries are byte-identical to the CLI's, exact and shadow requests are token-for-token the plain request
(blocking, streaming, cold and warm, CPU and Vulkan), counters partition, namespaces are isolated, and the C_A client
round-trips. Three plan checks fail, none in the K/V path: they show that **chunk edges are not token-stable when chunks are
shown adjacently** (F-A1, F-A2) and one wrong plan expectation (F-A3). No request reuses K/V yet.
