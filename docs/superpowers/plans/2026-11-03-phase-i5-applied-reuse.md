# Phase I5 (first working end-to-end test; applied reuse `balanced`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (A) A scripted end-to-end run of the chunk cache as it exists today (CLI-built store → `dotllm serve --chunk-cache` →
annotated OpenAI / Anthropic requests) on the real Qwen3-4B, on CPU and Vulkan, with pass/fail checks. (B) The smallest
server change that makes an opted-in request **actually reuse** stored chunk K/V (policy `balanced`: assemble, recompute
chunk starts, prefill the rest), measured for TTFT and quality against plain prefill.

**Architecture:** Part A adds no serving feature: scripts in `experiments/e2e-chunkcache/` drive released-to-scratch builds of
`feature/chunk-cache-server`. Part B adds one engine seam (`IPromptKvSeeder`, called by `TextGenerator` between prefix
restore and prefill), one pure planner in `DotLLM.ChunkReuse` (`ReuseLayout`: placements, holes, selection), and a server
seeder that fills a fresh or prefix-restored cache from store entries (CPU, host rows) or from an in-memory device-resident
entry cache (Vulkan), recomputes the selection in one pass (Vulkan, tiled `ATTN_QPOS`) or per run (CPU), and hands the
tail to the normal prefill. Any failure before the first token falls back to plain prefill.

**Tech Stack:** C# / .NET 10, dotLLM server (ASP.NET Core minimal APIs), `DotLLM.ChunkReuse` (assembler, `RopeShift`,
`SelectiveRecomputer`, `CpuChunkBackend` / `VulkanChunkBackend`, `FileChunkStore`), `DotLLM.ChunkCache.Client`, the
`chunkcache` CLI, xUnit with `[SkippableFact]` GPU gating, PowerShell + Python (stdlib) drivers.

**Spec:** `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md` (§2.3–2.4 limits, §3 serving order, §5.5 policies,
§5.6 query, §5.7 fallback, §5.9 report, §5.10 admission, §5.11 validation, §14 L5 / L7). Inputs: Phase I plan
(`docs/superpowers/plans/2026-11-02-phase-i-integration.md`: Task 20, Phase D, Phase I5 section), `REPORT.md`,
`experiments/G2-recompute-speed/README.md` (G2b), contract rulings `docs/contracts/chunk-cache-v1/README.md` (1–65).

## Global Constraints

- **Default stays `exact`.** Applied reuse needs **both** a server flag (`--chunk-cache-apply`, off by default) **and** a
  per-request policy `balanced` / `fast` / `auto`. Without the flag, today's behaviour (degrade to `exact`, reason
  `chunk_policy_unavailable`) is unchanged, byte for byte.
- **Exact counters stay exact.** `usage.prompt_tokens_details.cached_tokens` / `timings.cache_n` count exact prefix rows only;
  assembled rows go to `chunk_cache.tokens.chunk_reused` and `timings.chunk_n`; restored approximate prefix rows to
  `prefix_reused_approx`. Partition (§5.9): `prompt = prefix_reused + prefix_reused_approx + chunk_reused + prefilled`;
  `chunk_recomputed ⊂ chunk_reused`.
- **Lineage.** Every row at or after the first assembled row is approximate: `FirstApproxRow = min(restored entry's
  FirstApproxRow, first placed row)` is passed to `PrefixCache.Store` (Task 12, ruling: caller contract). An `exact` request
  never restores approximate rows.
- **CPU and Vulkan entries never mix** (backend in key and header). **Vulkan servers persist nothing** (ruling 58): Vulkan
  reuse uses an in-memory device-resident entry cache only (decision 1).
- **Supported envelope (refuse otherwise, reason given, plain prefill):** attention-only models with plain RoPE; CPU: the
  `TextGenerator` path with an exact host-F32 `SimpleKvCache` (`--no-paged`, no `--cache-type-*`); Vulkan: `VulkanKvCache`
  F32 storage, no compact windows, `SupportsQueryPositionAttention`, no RoPE frequency factors, no attention sinks
  (`VulkanChunkBackend.CheckModelSupported` / `CheckCacheSupported`). No adapter, draft model, MTP, hybrid strategy,
  `n > 1`.
- **Worktrees:** never switch branches in `C:\Development\dotLLM`. Builds for runs come from `git archive` exports under
  `C:\Development\dotLLM-e2e\<sha8>\` so running servers never lock files in a live worktree. `feature/chunk-cache` is
  updated by `git merge origin/dev`, never rebased.
- **Resources.** CPU-heavy runs hold ResourceLock `cpu-bench`; GPU runs hold ResourceLock `gpu` **and**
  `scripts/gpu-lock.sh acquire <name> <reason>` (release both promptly; `refresh` past 60 min). Every GPU launch is
  coordinated through the user first. CPU unit tests use
  `--filter "FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU"` (`DOTLLM_SKIP_VULKAN=1` does not skip Vulkan unit
  tests). A device-lost kills the process: disable the case statically, never catch-and-skip.
- **TDD + mutants + review per task** (as Phases S / I): tests first and seen failing; each correctness test killed by a named
  mutant run in a `git archive` scratch copy; fresh reviewer per task; fix rounds until clean; ledger
  `.superpowers/sdd/2026-11-03-phase-i5/progress.md`, reports `task-<id>-report.md` beside it.
- **Provenance per measured run:** commit, dirty=0, model file + HF revision, backend, driver, lock holder, ≥ 3 repeats for
  timings. Numbers go to `~/.claude/STRIX_HALO.md` (hardware) and `~/.claude/LLMs.md` (model/runtime).
- **Upstream:** nothing is pushed or filed without the user's explicit per-PR approval; issue drafts in
  `docs/release/chunk-cache-issues/NN-<slug>.md`; PRs target `dev`.
- **Model:** Qwen3-4B-Instruct-2507 Q4_K_M (bartowski), from the HF hub cache (path as in `experiments/chunkcache-demo`).

## Review Focus

- **Approximate rows leaking into an `exact` request** on the same CPU slot (balanced, then exact with a shared prefix): the
  exact request must restore only rows below `FirstApproxRow` and return the plain request's tokens and `cached_tokens`.
  Test `Exact_AfterBalanced_SameSlot_RestoresExactRowsOnly` in Task B2.
- **A failure after the cache was partly written** (entry file vanished between plan and load, header backend mismatch, a
  qpos forward that did not route, device allocation failure): the response is the plain request's output, the report says
  `policy_applied: exact` with a `reason`, and no approximate row is stored. Tests `Fault_<kind>_FallsBackToPlainPrefill`
  in Tasks B3 and B4.
- **Prompt re-tokenised differently from the plan** (template options, generation-prompt suffix, a reasoning tag): the seeder
  checks the generator's `promptIds` against the plan's ids before touching the cache; a difference is `exact` with reason
  `prompt_ids_changed`. Test `PromptIdsDiffer_NoReuse` in Task B3.
- **Chunks straddling the restored prefix** or overlapping each other after BPE adjustment: a hit chunk starting below the
  restored length is never placed (counted `prefix` if wholly inside, else prefilled). Test
  `HitStraddlingRestoredPrefix_NotPlaced` in Task B1.
- **The scheduler / paged-Q8_0 default CPU path** (`serve` without `--no-paged`): applied policies must degrade with reason
  `kv_layout_unsupported`, never assemble into a paged or quantised cache. Test `PagedScheduler_DegradesWithReason` in
  Task B3.

---

## Facts established while planning (read-only; dotLLM `feature/chunk-cache-server` `2c85f5ed`)

| fact | where | consequence |
|---|---|---|
| CPU `serve` default is **paged KV with Q8_0 blocks** + `PrefixTrieManager` + continuous-batch scheduler | `ServerStartup.cs` `ResolvePagedBlockType` (l. 48–62), paged branch (l. 662–673), scheduler (l. 801–835); `ChatCompletionEndpoint.cs` l. 272 vs 296 | applied reuse on CPU needs `--no-paged` (→ `TextGenerator` + `PrefixCache` + F32 `SimpleKvCache`); decision 2 |
| Vulkan: model-owned `VulkanKvCache` (F32 by default for Qwen3), **no `PrefixCache`, no trie**, `TextGenerator` path for dense models | `ServerStartup.cs` l. 514–544, l. 697 | every Vulkan request starts from an empty cache: no lineage interplay on Vulkan |
| Prefix restore then prefill from `cachedTokenCount` | `TextGenerator.cs` `ResolveKvCache` l. 1579 (calls at l. 431, 1061), `prefillStart = cachedTokenCount` l. 541; `PrefixCache.FindMatch(promptIds)` exact only (l. 1614); `Store(fullSequence, kvCache)` without lineage (l. 1717) | the seam goes between `ResolveKvCache` and `ForwardPrefill`; Task 12's `allowApprox` / `firstApproxRow` are not yet called by any caller |
| `PrefixAdmission.RestoredTokens = CachedTokens + ApproxRowsReused` | `PrefixTrieManager.cs` l. 283 | prefill starts at restored; `cached_tokens` = exact |
| Plan already holds verified spans with token positions and keys | `ChunkCachePipeline.cs` `PlannedSpan(TokenStart, TokenCount, Hit){Span, Key}`; `ChunkCacheExchange.Prepare` | the seeder consumes the plan; no new locating or tokenising |
| Library pieces exist | `ChunkAssembler.Assemble` (appends at running offsets, shifts keys), `SelectiveRecomputer.Recompute(model, backend, cache, contextTokens, selection, Auto, maxRowsPerForward)`, `ChunkEncoder.EncodeResident`, `ResidentChunkKvEntry`, `ChunkStartsSelector.Rank` | missing: placement **with holes**, a planner, a resident LRU |
| On `origin/dev` but not on the server branch | `46ec0da1` (`ReadRows` via host-cached memory, 19× faster; #1549–#1551), `ac21f197` (tiled qpos with F16 KV 2K–32K); `e1232def` (device QR probe) **is** on the server branch | merge `origin/dev` into the I5 branch (Task B0) |
| Cost model is the pre-tiled kernel (16 µs / row·key Vulkan) | `chunk-cost-model.json`; Phase I Task 20 not run | recalibrate from G2b (Task B5) |
| CLI is CPU-only, chunkers `symbol` / `fixed`; `select --json --include-text` gives chunk text and `stored` | `tools/DotLLM.ChunkCache` | Part A uses `symbol` (wire `symbol-512`, the only listed wire chunker, `ChunkCacheWire.cs` l. 28) |

---

## Part A: working test on what exists today (no new serving feature)

**Precondition:** Phase I Task 16 accepted (its code is `5b2c2167..2c85f5ed`; review pending at plan time). Pin the server
commit `S_A` = head of `feature/chunk-cache-server` after that, and the client commit `C_A` = `feature/chunk-cache-client`
(PR #1547 head).

**Fixture repo:** `git archive <S_A> src/DotLLM.ChunkReuse/Store` exported to `%SCRATCH%\e2e-repo\` (≈ 14 C# files; frozen
by commit). Four files are used: F1 `ChunkKey.cs`, F2 `ChunkNamespace.cs` (both encoded by the CLI), F3 `ChunkRef.cs`
(not encoded: server-write target), F4 `StoreStats.cs` (prewarm target). Prompts stay ≈ 1.5–3K tokens so CPU prefill is
≈ 10–25 s.

### Task A1: Driver, checks and their self-test [CPU, no model]

**Files (this repo):**
- Create: `experiments/e2e-chunkcache/run.ps1` (orchestration: export, build, CLI build, server start/stop, driver, locks)
- Create: `experiments/e2e-chunkcache/e2e.py` (stdlib only: builds requests, sends them, evaluates checks, writes
  `results/<run-id>/checks.json` + `summary.md`)
- Create: `experiments/e2e-chunkcache/ClientSmoke/ClientSmoke.csproj` + `Program.cs` (one OpenAI-surface request through
  `ChunkAnnotatingChatClient` + `ChunkCacheBodyHandler` from `C_A`, prints the parsed `ChunkCacheReport` as JSON)
- Create: `experiments/e2e-chunkcache/test_e2e_checks.py` (unit tests of the check functions over canned responses)
- Create: `experiments/e2e-chunkcache/README.md` (how to run, expected outputs, results table filled by A2/A3)

**Interfaces:**
- `run.ps1 -Backend cpu|vulkan -ServerCommit <sha> -ClientCommit <sha> -Model <gguf> [-Only <check-ids>]`; exit 0 only when
  every selected check passes; ports 18080+ (never 8080).
- `e2e.py check <id> --base-url ... [--api-key ...] --store <dir> --out <dir>`; each check returns
  `{id, passed, expected, observed, evidence_files}`.
- Request builder: chunk texts come from `chunkcache select --store <S> --path <F> --include-text --json` (document order),
  joined into one tool-result string with a glue header per file (`// <path> (lines a-b)\n`); manifest annotations
  (`chunk_cache.chunks[].at = {message, start, end}`, UTF-8 byte offsets, `hash = "sha256:" + hex`) on the OpenAI surface
  (ruling 19: string content); inline part annotations on the Anthropic surface.

- [ ] **Step 1: Write failing tests** in `test_e2e_checks.py`: `test_shadow_counts_match_expected_hits`,
  `test_exact_neutrality_detects_token_difference`, `test_exact_neutrality_void_when_plain_baseline_nondeterministic`
  (plain₁ ≠ plain₂ ⇒ check result `void`, which fails the run), `test_partition_holds`, `test_metrics_counter_delta`,
  `test_namespace_isolation_detects_cross_hit`, `test_manifest_offsets_are_utf8_bytes` (a `é` before a span).
- [ ] **Step 2:** `python -I -m unittest experiments/e2e-chunkcache/test_e2e_checks.py`; expected FAIL (functions missing).
- [ ] **Step 3:** Implement `e2e.py` checks and request builder; `run.ps1`; `ClientSmoke`.
- [ ] **Step 4:** Rerun; PASS. Mutants (scratch copy of `e2e.py`): partition check ignores `prefilled`; neutrality compares
  text not token ids; isolation check reads the wrong key; offsets in UTF-16 units. Each must turn a test red.
- [ ] **Step 5:** Commit (`experiments/e2e-chunkcache/`).

### The checks (ids, expected outputs, pass rule)

| id | action | expected (pass rule) |
|---|---|---|
| A0 build | `chunkcache build --model M --store S --directory e2e-repo --chunker symbol --path ChunkKey.cs --path ChunkNamespace.cs --threads 8 --json` | exit 0; `encoded` = number of F1+F2 chunks (call it `H`, expected 3–8); store holds `H` `.ckv` files; ≤ 3 min |
| A1 flag-off | server **without** `--chunk-cache`; annotated vs plain, temperature 0, `max_tokens` 32 | `GET /v1/chunk-cache` → 404; no `chunk_cache` field; token ids identical |
| A2 capabilities | server `--chunk-cache --chunk-store S` (loopback, no keys) | `versions [1]`; `policies` ⊇ the five; `selectors ["chunk_starts"]`; `wire_chunkers ["symbol-512"]`; `auto_validated []`; `model.supported true`; `store.entries == H`; `store.dtype "f32"` |
| A3 shadow | request annotating F1, F2, F3 chunks, `policy: shadow`, `report: per_chunk` | `policy_applied "exact"`; `chunks.hit == H`, `miss` = F3 chunk count, `ignored 0`; `plan.tokens.chunk_reused` = Σ hit chunk tokens; `plan.predicted_ttft_ms < plan.full_prefill_estimate_ms`; per-chunk status matches `select --json` `stored` |
| A4 exact neutrality | order plain₁, annotated(`exact`)₁, plain₂, annotated₂; blocking **and** streaming; then `shadow` then `exact` on the warm slot | all token ids identical to plain₁; `cached_tokens(annotated₂) == cached_tokens(plain₂)`; plain₁ ≠ plain₂ ⇒ **void (fail)**; report partition holds with `chunk_reused 0` |
| A5 strict | `strict: true` with one wrong `hash` | 400 `invalid_request_error`, `code chunk_hash_mismatch`; non-strict: 200 + warning |
| A6 Anthropic | `/v1/messages` stream, inline parts, `shadow` | `message_delta` carries `chunk_cache` with the A3 counts |
| A7 client | `ClientSmoke` (OpenAI surface, `shadow`) | exit 0; report counts equal A3's |
| A8 server write (2 sightings) | restart with `--chunk-store-write --chunk-store-budget 4GB`; send the F3 request twice, then poll capabilities ≤ 120 s | 1st: `encode_queued 0`; 2nd: `encode_queued` = F3 tokens (each chunk ≤ 512, ruling 65); `store.entries` rises by F3's chunk count; 3rd request shadow: F3 chunks `hit` |
| A9 server = CLI | `chunkcache build` of F3 into a **second** store `S2` (8 threads); compare | same key file names; payload bytes equal (report max abs diff if not; a difference fails and is investigated); `chunkcache status --store S` lists F3 as stored |
| A10 prewarm / evict / forget | prewarm F4 chunk texts with `source.path`; `evict` default; `evict mode=path path=F3 dry_run=false`; send F3 once after forget | prewarm `queued` = F4 count, entries appear; default evict deletes nothing (file list unchanged); path evict removes F3's server-written files + ledger rows, keeps CLI-indexed F1/F2 files (`kept_referenced`); one post-forget F3 request does not queue (sightings cleared) |
| A11 auth isolation | restart with `--chunk-cache-api-keys keys.txt` (keys K_A, K_B, 40 chars, K_A admin) | no key → 401; K_A shadow F1 → `hit 0` (CLI store is the default namespace); prewarm F4 with K_A → K_A hit, K_B miss; K_B `evict mode=namespace` leaves K_A's files; capabilities for K_B shows own figures only; namespace strings absent from all bodies and the server log |
| A12 metrics | `/metrics` before and after A3–A11 | `dotllm_chunk_cache_chunks_total{status="hit"}` delta = Σ reported hits; `tokens_total{kind}` present; no namespace label |
| V1 Vulkan capabilities + neutrality | `--device vulkan --chunk-cache --chunk-store S` | identity backend `vulkan`; A4 passes on Vulkan |
| V2 Vulkan shadow vs CPU store | as A3 | `hit 0`, `miss` = all verified chunks (backend in key; runs the never-run Task 15 GPU check) |
| V3 Vulkan writes nothing | `--chunk-store-write --chunk-store-budget 1GB`; A8's requests | warning `chunk_encode_skipped`; store directory listing byte-identical before/after |

### Task A2: CPU run [CPU; ResourceLock `cpu-bench`]

- [ ] **Step 1:** Export and build `S_A` and `C_A` (`dotnet build -c Release`) into `C:\Development\dotLLM-e2e\`; record
  provenance.
- [ ] **Step 2:** Acquire `cpu-bench`; `run.ps1 -Backend cpu ...` (A0–A12); release.
- [ ] **Step 3:** Every check passes. A failure is a finding: write it into `results/<run-id>/summary.md`, open a fix task
  against the owning Phase I task (no workaround in the script). **Runtime budget:** ≤ 20 min wall (build store ≈ 3 min,
  4 server starts ≈ 2 min, ≈ 25 requests ≈ 8 min, encodes ≈ 1 min); hard timeout 30 min.
- [ ] **Step 4:** Commit results (small JSON/MD only; no store files) and README table.

### Task A3: Vulkan run [GPU-lock; slot via the user]

- [ ] **Step 1:** Ask the user for a GPU slot. Acquire ResourceLock `gpu` and `scripts/gpu-lock.sh acquire e2e-chunkcache
  "I5 Part A Vulkan checks"`.
- [ ] **Step 2:** `run.ps1 -Backend vulkan -Only V1,V2,V3` against the CPU-built store from A2. Budget ≤ 6 min holding the
  lock. Release both locks.
- [ ] **Step 3:** All pass; commit results; record the Vulkan exact-overhead number (server `prompt_ms` annotated − plain,
  target < 5 ms, spec §12.5) in the README.

### Task A4: Report [docs]

- [ ] Write the README's result table (check, CPU, Vulkan, evidence file) and the one-paragraph verdict ("the wire, store,
  writer and control plane work end to end on the real model; no request reuses K/V yet"); update
  `.superpowers/sdd/2026-11-03-phase-i5/progress.md`; report to the user.

---

## Part B: applied reuse (`balanced`) in the server

### How a request is served (target design)

1. **Plan (unchanged, before the gate):** `ChunkCacheExchange.Prepare` → verified `PlannedSpan`s with `TokenStart`,
   `TokenCount`, `Key`, `Hit`. New: `AppliedPolicyResolver` decides `exact` vs `balanced` / `fast` from the flag, the
   request, the envelope (Global Constraints) and the cost gate (Task B5), and builds an `IPromptKvSeeder` or none.
2. **Restore (engine):** `ResolveKvCache` restores the exact prefix (CPU `PrefixCache`; with an applied policy
   `allowApprox: true`). Restored length `R`; exact part `E ≤ R`.
3. **Seed (new, inside the generator gate):** the seeder gets `(model, cache, promptIds, R)`:
   - `ReuseLayout.Plan`: hit spans with `TokenStart ≥ R` become **placements**; region `[R, End)` with `End` = end of the last
     placement (`End < promptLen`, always ≥ 1 tail token); every non-placed position in the region (glue, misses, partial
     prefix) is a **hole** and goes into the selection; chunk rows add `round(budget × placed rows)` positions ranked by
     `ChunkStartsSelector` (equal prefixes per placed chunk). Too few placed rows (< `MinPlacedTokens` = 256) → no reuse.
   - **Assemble:** per placement, ascending: CPU loads the entry from the store (one at a time) and `AssembleAt` writes it at
     its position with keys re-rotated; Vulkan copies from the resident entry (`CopyRows` + device `ShiftKeys`). Holes are not
     written.
   - **Recompute:** `SelectiveRecomputer.Recompute(model, backend, cache, promptIds[0..End), selection, Auto,
     maxRowsPerForward: 128)`: Vulkan one pass in ascending 128-row batches; CPU per run. Holes are recomputed before any
     later row reads them (ascending order + the forward writes a layer's rows before that layer's attention).
   - Returns `SeededRows = End`, `FirstApproxRow` = first placed position.
4. **Prefill tail (unchanged code):** `ForwardPrefill(promptIds, End, promptLen − End)` → first-token logits.
5. **Store snapshot (CPU):** `PrefixCache.Store(seq, cache, firstApproxRow: min(restored FirstApproxRow, first placed row))`.
6. **Report:** `policy_applied`, `chunks{prefix,hit,miss}`, `tokens{prefix_reused = E, prefix_reused_approx = R − E,
   chunk_reused = placed rows, chunk_recomputed = selected chunk rows, prefilled = holes + tail}`, `recompute{selector,
   budget, rows, forwards, attn_kernel}`, `timings_ms{assembly, recompute, prefill, full_prefill_estimate}`; `timings.chunk_n`,
   `chunk_recomputed_n`.
7. **Fallback:** any refusal or exception in step 3 → `cache.SetCurrentLength(R)` (rows below `R` were never touched), plain
   prefill from `R`, `policy_applied: exact`, `reason: reuse_failed:<kind>`, warning `chunk_policy_unavailable`; Vulkan:
   if truncation is refused, dispose and allocate a fresh cache and prefill from 0.

**Memory:** Qwen3-4B F32 K/V = 294,912 B/token. CPU: transient, one entry at a time (≤ 151 MB per 512-token chunk) plus the
request cache. Vulkan: the resident cache `--chunk-resident-budget` (default 2 GiB ≈ 7.3K tokens; 6 GiB for the 16K
measurement) + the request's cache (16K ≈ 4.7 GB); LRU by bytes; cleared on model swap.

### Order, owners, worktrees, parallelism

| task | owner (implementer → reviewer) | worktree / branch | depends on | runs |
|---|---|---|---|---|
| B0 integration branch | controller agent | new `chunk-apply`, branch `feature/chunk-cache-apply` off `feature/chunk-cache-server` (after Task 16), merges `origin/dev` and `feature/chunk-cache` | Task 16 accepted; the running dev-merge of `feature/chunk-cache` | CPU |
| B1 `ReuseLayout` + `AssembleAt` | subagent → fresh reviewer | `chunk-cache` (`feature/chunk-cache`), merged into B0 | dev-merge agent finished there | CPU (one GPU-lock step) |
| B2 engine seam + lineage | subagent → fresh reviewer **+ dotLLM session review** (prefix cache / engine owner) | `chunk-apply` | B0 | CPU; parallel with B1 |
| B3 server CPU applied path | subagent → fresh reviewer (+ security pass on fallbacks) | `chunk-apply` | B1, B2 | CPU |
| B4 Vulkan resident cache + Vulkan path | subagent → fresh reviewer **+ Vulkan owner review** | `chunk-apply` | B3 (seeder), B1 | CPU + GPU-lock |
| B5 cost model + gates | subagent → fresh reviewer | `chunk-apply` | B0; parallel with B3 | CPU |
| B6 quality harness | subagent → fresh reviewer (statistics) | this repo `experiments/I5-applied-reuse/` + B3/B4 builds | B3 (CPU), B4 (Vulkan) | CPU + GPU-lock |
| B7 TTFT measurement | subagent | same | B4, B5 | GPU-lock (+ CPU 2K under `cpu-bench`) |
| B8 docs, issue drafts, PR slicing | controller | this repo + local dotLLM branches | B1–B7 | docs |

Part A (A1) runs in parallel with B0–B2; A2/A3 need only Task 16.

### Task B0: Integration branch [CPU]

- [ ] Create worktree `C:\Development\dotLLM\.claude\worktrees\chunk-apply` on `feature/chunk-cache-apply` from the accepted
  Task 16 head; `git merge origin/dev` (brings `46ec0da1`, `ac21f197`); `git merge feature/chunk-cache`; build; CPU suite
  (filter above) green; record counts in `task-B0-report.md`. Commit merges only.

### Task B1: Placement with holes and the reuse planner (L5, library) [CPU + one GPU-lock step]

**Files (dotLLM, `feature/chunk-cache`):**
- Create: `src/DotLLM.ChunkReuse/Applied/ReuseLayout.cs`
- Modify: `src/DotLLM.ChunkReuse/ChunkAssembler.cs` (add `AssembleAt`)
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ReuseLayoutTests.cs`, `ChunkAssemblerAtTests.cs`,
  `tests/DotLLM.Tests.Unit/Vulkan/ChunkAssemblerAtVulkanTests.cs` (GPU-gated)

**Interfaces (produces):**
- `public readonly record struct ReuseSpan(int TokenStart, int TokenCount)`;
  `public readonly record struct ChunkPlacement(int SpanIndex, int Position, int Length)`.
- `public sealed record ReuseLayout(int RegionStart, int RegionEnd, IReadOnlyList<ChunkPlacement> Placements, int[] Selection,
  int PlacedRows, int ChunkRowsSelected, int HoleRows)`; `RegionEnd == RegionStart` means "no reuse".
- `public static ReuseLayout ReuseLayout.Plan(int promptLength, int restoredRows, IReadOnlyList<ReuseSpan> hits,
  ReadOnlySpan<int> promptIds, double budget, int minPlacedTokens = 256)`: hits sorted by start, overlapping or `< restoredRows`
  dropped; `RegionEnd < promptLength`; `Selection` strictly ascending ⊆ `[RegionStart, RegionEnd)` ⊇ every hole;
  chunk-row picks from `ChunkStartsSelector` over a `ChunkedContext` of the placed chunks (seed 0), mapped to global positions.
- `public void ChunkAssembler.AssembleAt(IKvCache destination, int position, ChunkKvEntry entry, string expectedFingerprint)`
  and the same for `ResidentChunkKvEntry`: `position ≥ destination.CurrentLength`; writes rows at `position`, re-rotates keys
  by `position`, sets `CurrentLength = position + Length`; rows in `[old length, position)` untouched; validation before
  any write; rollback to the old length on a write failure (as `Assemble`).

- [ ] **Step 1: Write failing tests:** `Plan_HolesAreAllSelected`; `Plan_SelectionAscendingWithinRegion`;
  `Plan_TailAlwaysAtLeastOneToken` (last chunk ends at `promptLength`: it is dropped or trimmed);
  `HitStraddlingRestoredPrefix_NotPlaced` (Review Focus); `Plan_OverlappingHits_SecondDropped`;
  `Plan_BudgetCountsChunkRowsOnly` (20 % of 1,000 placed rows = 200 chunk rows, holes extra);
  `Plan_TooLittleReuse_NoRegion`; `Plan_ChunkStartsAreEqualPrefixesPerChunk`;
  `AssembleAt_LeavesHole_LengthIsEnd`; `AssembleAt_KeysEqualEncodeAtPosition` (CPU: entry encoded at 0 and placed at `p`
  equals the model's own K at `p` for a one-chunk context, within the E1 RoPE bound 3e-5 of the head norm);
  `AssembleAt_BelowCurrentLength_Refused`; `AssembleAt_WrongFingerprint_NothingWritten`;
  `HolesThenRecompute_EqualsFullPrefill_WhenEverythingSelected` (CPU, synthetic model: all positions selected ⇒ bit-identical
  to prefill of the same tokens).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** PASS. Mutants: hole not selected; selection sorted descending; shift by placement index instead of
  position; tail allowed to be empty; straddling hit placed; length not advanced.
- [ ] **Step 5 [GPU-lock]:** `AssembleAt_Vulkan_EqualsCpu` (resident entry, device copy + shift, F32) under the locks; slot via
  the user.
- [ ] **Step 6:** Commit; merge into `feature/chunk-cache-apply`; issue draft `NN-library-reuse-layout.md`.

### Task B2: Engine seam `IPromptKvSeeder` and lineage wiring [CPU]

**Files (dotLLM, `feature/chunk-cache-apply`):**
- Create: `src/DotLLM.Engine/PromptCache/IPromptKvSeeder.cs`
- Modify: `src/DotLLM.Engine/TextGenerator.cs` (`ResolveKvCache` returns exact and restored counts; both generation paths
  call the seeder between restore and prefill; `StoreInPrefixCache` passes `firstApproxRow`), the inference options type
  (gains `IPromptKvSeeder? KvSeeder`; located at task start), `InferenceTimings` (`ChunkReusedTokens`,
  `ChunkRecomputedTokens`, `ApproxPrefixTokens`, `SeedMilliseconds`)
- Test: `tests/DotLLM.Tests.Unit/Engine/PromptKvSeederTests.cs`

**Interfaces (produces):**
```csharp
public interface IPromptKvSeeder
{
    bool AcceptsApproximatePrefix { get; }   // ResolveKvCache uses FindMatch(..., allowApprox: true) when set
    PromptSeedResult Seed(IModel model, IKvCache cache, ReadOnlySpan<int> promptIds, int restoredRows, CancellationToken ct);
}
public readonly record struct PromptSeedResult(int SeededRows, int? FirstApproxRow, int ChunkRows, int ChunkRowsRecomputed,
    double AssemblyMs, double RecomputeMs, int Forwards, string? FallbackReason);
```
Contract: on entry `cache.CurrentLength == restoredRows`; on success `restoredRows ≤ SeededRows < promptIds.Length` and rows
`[0, SeededRows)` valid; the generator prefills from `SeededRows`. On exception or `FallbackReason != null` the generator
truncates to `restoredRows` (fresh cache if refused) and prefills as today. Seeder ignored (never called) on the recurrent,
hybrid-strategy, MTP, draft, adapter paths. Nothing changes when `KvSeeder` is null.

- [ ] **Step 1: Write failing tests** (synthetic model, fake seeder): `NoSeeder_BehaviourAndTokensUnchanged`;
  `Seeder_PrefillStartsAtSeededRows` (fake seeder writes exact rows by prefill ⇒ tokens equal plain);
  `Seeder_Throws_FallsBackToPlainPrefill_SameTokens`; `Seeder_FallbackReason_TruncatesToRestored`;
  `Seeder_StoresFirstApproxRowInPrefixCache`; `Exact_AfterBalanced_SameSlot_RestoresExactRowsOnly` (Review Focus);
  `CachedTokens_CountExactRowsOnly_WhenApproxRestored`; `SeederNotCalled_OnHybridMtpDraftAdapterPaths`;
  `Streaming_And_Blocking_BothCallSeeder`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement (additive; `ResolveKvCache`'s exact semantics untouched when no seeder).
- [ ] **Step 4:** PASS + the existing PromptCache / TextGenerator suites. Mutants: approximate restore without the seeder's
  opt-in; `firstApproxRow` dropped; fallback leaves the seeded length; `cached_tokens` = restored.
- [ ] **Step 5:** Commit; request the dotLLM session's review of the diff (prefix cache owner) before B3 merges on top; issue
  draft `NN-engine-prompt-kv-seeder.md`.

### Task B3: Server CPU applied path (`balanced`, `fast`) [CPU]

**Files (dotLLM, `feature/chunk-cache-apply`):**
- Create: `src/DotLLM.Server/ChunkCache/Apply/AppliedPolicyResolver.cs`, `ChunkReuseSeeder.cs`
- Modify: `ChunkCacheExchange.cs` (holds the resolver outcome and the seed result; `Finish` reports them),
  `ChunkCachePipeline.cs` / `ChunkCacheReport.cs` (applied fields), `ChunkCacheOptions.cs` + `ServeCommand.cs`
  (`--chunk-cache-apply`), `Endpoints/ChatCompletionEndpoint.cs`, `MessagesEndpoint.cs` (pass `KvSeeder` on the generator
  path), `ChunkCacheEndpoint.cs` (capabilities: `"applied": true|false`), `ChunkCacheMetrics.cs`
  (`dotllm_chunk_cache_tokens_total{kind="chunk_reused"|"chunk_recomputed"}`, `..._applied_total{outcome}`),
  `docs/CHUNK_CACHE.md`
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/AppliedReuseTests.cs`,
  `tests/DotLLM.Tests.Integration/ChunkCacheAppliedCpuTests.cs`

**Interfaces:**
- Consumes: B1 (`ReuseLayout`, `AssembleAt`), B2 (`IPromptKvSeeder`), `PlannedSpan`, `IChunkStore`, `CpuChunkBackend`,
  `SelectiveRecomputer`.
- Produces: `AppliedPolicyResolver.Resolve(ChunkCachePlan plan, ServerState state, ChunkCaller caller) ->
  AppliedDecision(string PolicyApplied, string? Reason, IPromptKvSeeder? Seeder, double Budget)`. Budgets: `balanced` 0.20
  (§5.5; request `recompute.budget` in [0, 0.5] overrides), `fast` 0.05 (`budget: 0` = naive). Reasons (stable strings):
  `apply_disabled` (no flag; keeps today's `chunk_policy_unavailable`), `kv_layout_unsupported` (scheduler / paged /
  quantised / CUDA), `model_unsupported`, `no_hits`, `too_little_reuse`, `no_predicted_gain` (B5), `not_validated` (`auto`,
  B5), `prompt_ids_changed`, `reuse_failed:<kind>`.
- `ChunkReuseSeeder(ChunkCachePlan plan, IChunkStore store, IChunkBackend backend, ChunkAssembler assembler, double budget,
  string fingerprint)` implements `IPromptKvSeeder` (`AcceptsApproximatePrefix = true`); per placement: `store.TryGet(key)`,
  re-check the entry's token ids equal `promptIds[pos..pos+len)` (else the span becomes a hole), then `AssembleAt`.

- [ ] **Step 1: Write failing tests:** `FlagOff_BalancedIsExact_BytesUnchanged`; `Balanced_Cpu_ReportPartitionHolds`;
  `Balanced_Cpu_MatchesLabRecompute_Bitwise` (synthetic model: the server's cache rows and first-token logits equal
  `ChunkAssembler` + `SelectiveRecomputer.Run` on the same layout); `Balanced_NoHits_ExactWithReason`;
  `PagedScheduler_DegradesWithReason` (Review Focus); `PromptIdsDiffer_NoReuse` (Review Focus);
  `Fault_EntryMissingAtLoad_SpanBecomesHole`; `Fault_HeaderBackendMismatch_FallsBackToPlainPrefill`;
  `Fault_ExceptionMidRecompute_FallsBackToPlainPrefill_NoApproxStored` (Review Focus); `Exact_WithApplyFlagOn_StillBitIdentical`
  (blocking + streaming); `CachedTokens_NeverIncludeChunkRows`; `Fast_BudgetZero_IsNaive`; `Metrics_AppliedCounters`;
  `Unauthenticated_NoReuse` (no namespace ⇒ no lookup, as today); `Capabilities_AppliedTrueOnlyWithFlagAndSupportedPath`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** PASS + Server / ChunkCache / Engine suites. Mutants: holes not recomputed; placed rows counted as
  `cached_tokens`; fallback skips truncation; `exact` routed through the seeder; reason dropped; token re-check skipped.
- [ ] **Step 5 [CPU, real model, `cpu-bench`]:** one smoke run: `serve --no-paged --chunk-cache --chunk-cache-apply
  --chunk-store S` (Part A store), the A3 request with `policy: balanced`: 200, `policy_applied "balanced"`,
  `chunk_reused` = Σ hit tokens, output is fluent text; record `prompt_ms` vs plain.
- [ ] **Step 6:** Commit; issue draft `NN-server-applied-cpu.md`.

### Task B4: Vulkan: device-resident entry cache and the single-pass path [CPU + GPU-lock]

**Files (dotLLM, `feature/chunk-cache-apply`):**
- Create: `src/DotLLM.Server/ChunkCache/Apply/ResidentChunkCache.cs`
- Modify: `ChunkReuseSeeder.cs` (resident source), `ChunkStoreService.cs` / `ChunkEncodeQueue.cs` (on Vulkan, admitted
  encodes go to the resident cache via `ChunkEncoder.EncodeResident` instead of refusing; still nothing persisted, ruling 58),
  `ChunkCacheEndpoint.cs` (prewarm on Vulkan fills the resident cache; capabilities `resident{entries, bytes, budget_bytes}`),
  `ServeCommand.cs` (`--chunk-resident-budget <bytes>`, default 2 GiB, 0 = off), `docs/CHUNK_CACHE.md`
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/ResidentChunkCacheTests.cs` (CPU, fake entries),
  `tests/DotLLM.Tests.Unit/Vulkan/ChunkCacheAppliedVulkanTests.cs` (GPU-gated)

**Interfaces:**
- `ResidentChunkCache(long budgetBytes)`: `bool TryGet(ChunkKey key, out ResidentChunkKvEntry entry)` (lease; an entry in use
  is never evicted), `bool TryAdd(ChunkKey key, ResidentChunkKvEntry entry)` (LRU eviction by bytes; refuses an entry larger
  than the budget), `void Clear()` (model swap, shutdown), `ResidentStats Stats`. Keyed by the full `ChunkKey` (namespace,
  backend `vulkan`, fingerprint).
- Seeder on Vulkan: `VulkanChunkBackend.CheckModelSupported` / `CheckCacheSupported` and `SupportsQueryPositionAttention`
  before anything is written (refusal ⇒ `model_unsupported` / `kv_layout_unsupported`); recompute `SinglePass`,
  `maxRowsPerForward 128`; report `attn_kernel` = `qpos_tiled` when `QueryPositionAttentionLayers` moved, else
  `reuse_failed:qpos_not_routed`.
- Encodes run only while idle (`ServerState.TryAcquireIdleModel`, as Task 15), one chunk per acquisition.

- [ ] **Step 1: Write failing tests (CPU):** `Resident_LruEvictsByBytes`; `Resident_LeasedEntryNotEvicted`;
  `Resident_OversizeRefused`; `Resident_ClearedOnModelSwap`; `Resident_KeyIncludesNamespace`;
  `VulkanAdmission_GoesToResident_NothingPersisted` (fake encode host; store directory unchanged).
- [ ] **Step 2:** Run; FAIL. **Step 3:** Implement. **Step 4:** PASS; mutants: eviction by count not bytes; leased entry
  evicted; namespace dropped from the key; Vulkan admission persists.
- [ ] **Step 5 [GPU-lock; slot via the user]: GPU tests** (synthetic model and the real model behind `DOTLLM_REAL_MODEL`):
  `Balanced_Vulkan_MatchesLabSinglePass` (server rows vs `AssembleAt` + `SelectiveRecomputer` single pass, same layout,
  within the G2b tiled tolerance: K/V mean ≤ 1e-2, first-token KL ≤ 1e-3); `Balanced_Vulkan_HolesRecomputedBeforeRead`
  (a layout whose first selected batch is all holes); `Fault_DeviceCopyFails_FallsBackToPlainPrefill`;
  `F16Cache_Refused_WithReason`; `Exact_Vulkan_StillBitIdentical`.
- [ ] **Step 6 [GPU-lock]:** real-model smoke: prewarm F1–F4, then the A3 request with `balanced`: `policy_applied
  "balanced"`, `attn_kernel "qpos_tiled"`; record `prompt_ms` vs plain.
- [ ] **Step 7:** Commit; issue draft `NN-server-applied-vulkan.md` (needs the Vulkan wiring PRs of Phase I Task 22 first).

### Task B5: Cost model on the tiled kernel; `balanced` guard; `auto` gates [CPU]

**Files (dotLLM):** `ChunkCostModel.cs`, `chunk-cost-model.json`, `AppliedPolicyResolver.cs`, `ServeCommand.cs`
(`--chunk-cache-auto-cells <list>`); **(this repo)** `experiments/I1-shadow-cost/` (Phase I Task 20 Steps 1–2 folded in).

**Interfaces:**
- `ChunkCostModel.PredictReuseMs(long placedRows, long selectedRows, long holeRows, long regionStart, long tailRows)` and
  `PredictPlainMs(long promptRows)`; coefficients per backend and resident/host source: Vulkan from G2b (tiled qpos,
  resident assembly, host-write assembly), CPU from E4 per-run timings and A2/B3 `prompt_ms`.
- Gate: reuse applies when `PredictReuseMs ≤ GainMargin × PredictPlainMs`, `GainMargin = 0.8`; else `exact`, reason
  `no_predicted_gain`. **`balanced` and `fast` obey the gate** (decision 4). **`auto`** additionally needs the
  (chunker × selector × budget) cell in the validated table, which stays empty (§5.11); an operator may list cells with
  `--chunk-cache-auto-cells symbol-512:chunk_starts:0.20` (documented as unvalidated, lossy); otherwise reason
  `not_validated` (decision 5).

- [ ] **Step 1: Write failing tests:** `CostModel_PredictsG2bWithin25Percent` (G2b CSV rows: 2K, 8K; 5 / 10 / 20 %; resident and
  host-write); `Gate_NoGain_Exact`; `Auto_EmptyTable_NotValidated`; `Auto_OperatorCell_Applies`;
  `Capabilities_AutoValidatedStaysEmpty_OperatorCellsListedSeparately`.
- [ ] **Step 2:** FAIL. **Step 3:** Fit and implement. **Step 4:** PASS; mutants: margin inverted; operator cells reported as
  `auto_validated`; gate skipped for `balanced`.
- [ ] **Step 5:** Commit both repos.

### Task B6: Quality harness [CPU + GPU-lock]

**Files (this repo):** `experiments/I5-applied-reuse/make_requests.py`, `run_quality.ps1`, `score.py`, `README.md`.

**Design:**
- Tasks: the G2 / E4 2K masked-call tasks (28, frozen corpora); 8K from the E4 8K contexts (validated tasks only). Each
  context's chunks become one user message (glue header per chunk + chunk text, manifest-annotated), then the masked-call
  query; arms **query-after** (E4's shape) and **query-before** (§5.6).
- Entries: `prewarm` with each chunk's text (CPU: store, written by the server; Vulkan: resident). Store root in scratch.
- Arms per task: plain (no annotations), `exact`, `balanced` at budget 0.05 / 0.10 / 0.20, `fast` with `budget: 0` (naive).
  Temperature 0, `max_tokens` 24, `logprobs` + `top_logprobs: 20` on the first generated token.
- Metrics vs plain: EM of the masked call (E4's scorer), first-token top-1 agreement, first-token **top-20 truncated KL**
  (labelled as such; not comparable to the lab's full-vocabulary KL), generated-text exact match; paired cluster bootstrap
  (cluster = definition file) as E4.
- **Pass rules:** `exact` = plain on 100 % of tasks (neutrality; any difference fails the phase); `balanced` 0.20 EM ratio to
  plain ≥ 0.76 on the 2K tasks (G2b lab arm 24/28 = 0.86, minus 0.10); results reported per arm whatever they are. The
  95 / 20 bar is **not** expected to hold (§2.3) and is reported, not gated.
- [ ] **Step 1:** Write `score.py` tests (`test_em_matches_e4_scorer_on_g2_rows`, `test_truncated_kl_zero_for_identical`,
  `test_bootstrap_cluster_by_file`); FAIL; implement; PASS; mutant: KL without renormalisation.
- [ ] **Step 2 [CPU, `cpu-bench`]:** CPU server (`--no-paged --chunk-cache --chunk-cache-apply --chunk-store-write`), 2K tasks,
  all arms. Budget ≈ 3 h (28 tasks × 6 arms × ≈ 30 s + prewarm encodes ≈ 25 min); run unattended.
- [ ] **Step 3 [GPU-lock]:** Vulkan server (resident budget 4 GiB), 2K and 8K, all arms; ≤ 45 min holding the lock.
- [ ] **Step 4:** README with tables and CIs, side by side with E4 / G2b lab numbers; commit; record in `LLMs.md`.

### Task B7: TTFT on Strix Halo [GPU-lock; CPU 2K under `cpu-bench`]

**Files (this repo):** `experiments/I5-applied-reuse/ttft.ps1`, `ttft.py`, results in the same README.

- Contexts: 2K, 8K, 16K tokens built from corpus chunks (≥ 90 % of prompt tokens in annotated chunks; system prompt + query
  glue), `--ctx-size 20480`, resident budget 6 GiB. Per size: prewarm, one warm-up request, then 3 repeats each of plain,
  `balanced` 0.05 and 0.20 (warm resident), plus one `balanced` 0.20 after `Clear()` (cold: encode on the request path is
  not done; it is a miss ⇒ plain, so the cold row documents fallback overhead). Server `timings.prompt_ms` and client
  first-byte TTFT (streaming).
- **Success criteria (median of 3, Vulkan, warm resident, against the server's own plain prefill):** `balanced` 0.20 ≥ 2.0× at
  2K, ≥ 4× at 8K, ≥ 6× at 16K; `balanced` 0.05 ≥ 3× / 8× / 12×. (G2b lab: 4.1 / 9.4 / 14.2× at 20 % and 7.8 / 19.7 / 36.6× at
  5 % against the ordinary prefill; the criteria allow for glue, tail, per-request overhead and an improved ordinary prefill,
  e.g. dotLLM #1548.) Also reported: ratio against a tiled-kernel prefill estimate. **CPU 2K:** reported, target ≥ 1.5× at
  0.20, not a gate. **Exact overhead:** annotated `exact` − plain < 5 ms median.
- [ ] Run under the locks (≤ 40 min holding the GPU); write the table; record in `STRIX_HALO.md` / `LLMs.md`; commit; report.

### Task B8: Docs, issue drafts, PR slicing [docs]

- [ ] `docs/CHUNK_CACHE.md` (dotLLM): applied policies, flags, envelope, reasons, lossy warning. Spec §5.5 / §5.9 edits here:
  new reasons, `applied` and `resident` capability fields, `--chunk-cache-auto-cells`.
- [ ] Issue drafts and the PR order (below) in `docs/release/chunk-cache-issues/00-umbrella.md`. Nothing filed or pushed
  without the user's per-PR approval.

**PR slicing (after #1547 client, #1575 lineage, #1576 pins, #1577 core, PR4 store, and the server group I1a 10/11/13/14 and
I1b 15/16):**

| PR | content | size target | after |
|---|---|---|---|
| I5-1 | `ReuseLayout` + `AssembleAt` (library) | ≤ 500 lines | PR4 store |
| I5-2 | engine `IPromptKvSeeder` + lineage wiring in `TextGenerator` | ≤ 400 | #1575 |
| I5-3 | server CPU applied path + flag + report fields + metrics | ≤ 700 | I5-1, I5-2, server group |
| I5-4 | cost model recalibration + gates | ≤ 300 | I5-3 |
| I5-5 | Vulkan resident cache + Vulkan path | ≤ 600 | I5-3, Task 22 Vulkan wiring PRs |

---

## Risks

| risk | likelihood / impact | mitigation |
|---|---|---|
| **Quality loss of approximate reuse** (chunk starts below the 95 / 20 bar; EM 24/28 at 20 % in G2b) | certain / high | default `exact`; double opt-in (flag + per request); `auto` needs a validated cell (empty table); reports say `chunk_starts` and the budget; B6 measures it on the server path |
| Approximate rows contaminating exact requests (CPU prefix cache) | low / high | lineage tag on every store; Review Focus test; Task 12 caps exact lookups |
| Vulkan default KV moving to F16 (dotllm-97 F16 work) | medium / medium | applied path refuses F16 with a reason today; follow-up: F16 rows (RoPE shift kernel and tiled qpos already handle F16) |
| CPU default (paged Q8_0 + scheduler) cannot take reuse | certain / medium | `--no-paged` required and documented; reason `kv_layout_unsupported`; full L5 (paged / quantised assembly) stays a later item |
| Cost-model mis-prediction makes `balanced` slower | medium / low | gate with margin 0.8; B5 calibration; TTFT reported per request |
| Resident memory pressure on the UMA iGPU (16K: ≈ 4.7 GB cache + resident entries) | medium / medium | byte budget, leases, refuse oversize; 16K run only with 6 GiB budget and nothing else on the GPU |
| Llama-3.1 (RoPE frequency factors) refused on Vulkan | certain / low | CPU only for Llama; documented |
| Background encodes competing with requests on the GPU | low / medium | idle-only acquisition, one chunk at a time |
| A device-lost during GPU tests | low / high | locks, 128-row submits, static disable of a crashing case |

## Decisions needed (with recommendations)

1. **Vulkan entry source.** Recommend an **in-memory device-resident cache** filled by prewarm and by 2-sighting idle encodes
   (no persistence, ruling 58 kept, no shader / driver versioning question, no `ReadRows` cost). Persisting Vulkan entries
   waits for Phase D (D5b versioning; `ReadRows` is now 19× faster on `dev`).
2. **CPU KV layout.** Recommend requiring `--no-paged` (F32 `SimpleKvCache`, `TextGenerator` path) for applied reuse; paged /
   Q8_0 / scheduler assembly is later L5 work.
3. **Server opt-in.** Recommend a new `--chunk-cache-apply` flag (off by default) in addition to the per-request policy.
4. **Cost guard on explicit `balanced` / `fast`.** Recommend yes (reason `no_predicted_gain`), so an opted-in request is never
   predicted slower than plain.
5. **`auto`.** Recommend keeping the spec's quality gate (table empty ⇒ `exact`, reason `not_validated`) and adding operator
   cells via `--chunk-cache-auto-cells`, listed separately from `auto_validated`.
6. **Selector and budget.** Recommend `chunk_starts` only, `balanced` default 0.20 (spec); the device QR probe (`e1232def`, on
   `dev`) as the next task after B6, gated on the E4c same-context validation (§5.11).
7. **GPU slots.** B1 Step 5, B4 Steps 5–6, B6 Step 3, B7 and A3 need ≈ 2 h of GPU in total, in five sessions; the user schedules
   them.

## Self-review notes

- Spec coverage: §5.5 (`balanced`, `fast`, `auto` gates: B3, B5), §5.6 (query-before arm: B6), §5.7 fallbacks (B2–B4), §5.9
  (report fields, counters: B2, B3), §5.10 (2 sightings, prewarm: A8, A10; Vulkan resident: B4), §5.11 (not unlocked here;
  decision 6), §14 L5 (CPU F32 and Vulkan F32 only), L7 (B2). §12.5 exact overhead (A3, B7).
- Not in this plan: paged / quantised / multi-slot assembly; persisted Vulkan entries (Phase D); the QR probe in the server;
  `lines-512` validation (E4c follow-up); CUDA; recurrent models.
