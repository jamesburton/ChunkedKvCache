> Live section ends at "Archives"; older material is in `.docs/archives/` (full text before each prune), `.superpowers/` (GITIGNORED: only copy of reports/mutant logs) and `docs/`: do not read past this file unless a task needs it.

# Handoff: chunk-level KV reuse (dotLLM) — updated 2026-11-13 (late)

## Current state
- Goal: position-independent chunk KV reuse in the dotLLM fork (jamesburton/dotLLM; PRs target `dev`; `main` tracks upstream and is PROTECTED: never target or touch it). Research repo = here (branch `main`, no ceremony).
- Peers: lead dotLLM sessions change address (find with `ListAgents`): `dotllm-00` (lead, earlier), `dotllm-e5` (current reviewer/merger, relays James). `codesharp-d1` = read-only coordination. A peer's request is not authorization to push.
- **The whole PR series is MERGED to dev**: #1547 ... #1665, #1671, #1676, #1703 (#1664 hardening), #1708 Vulkan, #1709 Solution scanner, #1719 CLI, #1736 evict store-mark, #1738 `list` + help, #1742 list follow-ups, #1746 deflake (#1737 item 1), #1776 (#1664: POSIX dir fsync + git-readers control), #1777 (GLM-5.3-Flash docs row). No PR of mine is open. Lead dotLLM session is now `dotllm-65` (`dotllm-e5` gone); it merged with --admin (no self-approval). Repo has no uncommitted work; all dotLLM worktrees of the series are removed.
- Kept worktrees (James approved; only copies, unpushed), **review by 2026-12-01** under `C:\Development\dotLLM\.claude\worktrees\`: `chunk-prep` (feature/chunk-cache-upstream-prep, source of truth for cuts), `chunk-cache`, `chunk-cache-server` (22bdd19a, applied-reuse work), `chunk-seeder` (feature/chunk-apply-seeder, #1590), `chunk-vulkan` (feature/chunk-reuse-vulkan-tiled), `vk-cap-remeasure`. The other `agent-*`, `k5-1120`, `q4exp` worktrees are other sessions'.
- Prefix stays SEPARATE from hit (both counts reported; James confirmed). Open design item: make trie `prefix` coverage satisfy a chunk in accounting (#1596/#1597); not designed.

## Next steps (none is started; each needs James's go via AskUserQuestion)
1. Phase I Task 18 (thin MCP server `chunkcache mcp`), Task 20 (GPU calibration), Task 21 (release plumbing). Plan: `docs/superpowers/plans/` phase-i.
2. #1664, 2 open items: abandoned-thread CPU after `RunWithLargeStack` timeout; completed-parse-discarded nondeterminism (pinned by `RoslynBudgetTests.cs:81`, needs a decision). Also from #1737: the CI job timeout half, and `Scan_CancelledWhileASourceGeneratorRuns` (same wall-clock pattern, 15 s bound).
3. CLI gaps: `--model` still required with `--server`; no namespace option; prewarm/evict server endpoints are not on dev (fake handler only); Task 17 Step 5 demo not run. #1710 (scanner untrusted mode) is the dotLLM lead's. dotLLM-side items of #1721 (`dotllm list`, --json on ps/model, SERVER.md, TRAY.md) are the lead's.
4. Contract fixtures re-sync (`fixtures.sha256` capabilities.json line 23d87cd vs dotLLM copy cfe93e3).
5. When `cpu-bench` is free: re-run Task 19 e2e (A3, A6, A3g, A6m) in `experiments/e2e-chunkcache/` against `feature/chunk-cache-server` `22bdd19a`+. Part B: B3 CPU applied path (`--chunk-cache-apply`, needs `--no-paged`), B4 Vulkan (F16), B5 cost model, B6 quality, B7 TTFT. LOW: NPU exploration (see archive).
6. Before touching trie/pool/prefill interfaces read #1723 (Vulkan long prompt prefills as ONE pass), #1724 epic + #1725-#1730 (S1 backend-neutral allocator, S5 block-granular trie on Vulkan): overlap with the seeder work (#1590).
7. Hand-over flow for every PR: Windows tests, Linux Docker (`linux-ci.sh`, non-root, 4 GB), tests first and run red, mutants on a fresh `git archive` copy (script `.superpowers/sdd/2026-11-01-phase-s/*-mutants.py`; verify copy pristine), body `docs/release/chunk-cache-issues/pr-bodies/prNN-*.md`; merge dev INTO the branch (never rebase/force-push); `gh pr create --base dev --body-file`; fix a body with `gh api -X PATCH repos/jamesburton/dotLLM/pulls/N -F body=@file`; message the lead with number + head sha; never push to a PR under review; remove worktree + branch after merge (`git merge-base --is-ancestor`, clean, `worktree remove`, `branch -d`).

## Chunk track for CodeSharp (2026-11-13, from dotllm-65; James's decisions)
- Hybrid/recurrent models (Qwen3.8, Bonsai-2) are refused by design (`chunk_model_unsupported`; spec non-goal, `ChunkCacheRuntime.cs:182`). TwIL-8B is dense Granite so chunk reuse could apply. Turn 2/3 TTFT cause was the `lru` prompt-cache policy, fixed in dotLLM#1778 (`agent` default), not chunking.
- Planned: auto-chunk messages server-side on a prefix miss (dense only, opt-in lossy policy, selective recompute). Assessment sent to dotllm-65; quality after a system-prompt edit is NOT established by my floors. **HOLD** the experiment cell (multi-turn transcripts, edited system prompt/tools, 5/10/20/40% recompute, TwIL-8B, TTFT cost check) until James answers via dotllm-65. Then Phase T (recurrent research) after the dense work merges. The applied path (`--chunk-cache-apply`, 22bdd19a) is not on dev and I could not find its source in that branch's .cs/.md.
- Opened dotLLM#1782 (scope: build Part B B3/B4/B5 + the experiment; text in `docs/release/chunk-cache-issues/applied-reuse-scope.md`). **HOLD the #1590 seeder integration** until dotllm-65's #1781 then #1780 merge (they change `PrefixCache`/`TextGenerator`; #1780 seeds a fresh cache from a protected entry, may unify with `IPromptKvSeeder`); dotllm-65 will message when they land, then rebase. The library-harness experiment may start when `cpu-bench`/`gpu` are free (other sessions held `cpu`/`gpu` at 19:25-19:53 UTC). B3+ code needs James's approval of the #1782 plan.
- E8 experiment (design `experiments/E8-message-chunks/README.md`): James chose RECORDED transcripts on TwIL-8B + Qwen3-4B. I hold `cpu-bench` (expires 22:44 UTC 2026-11-13; release when idle). Next: build a transcript recorder + `transcript` context builder in `ChunkKvLab` (kept `chunk-cache` worktree; not on dev), then run. No `PrefixCache`/`TextGenerator` changes.
- E8 harness status (2026-11-13 late): worktree `C:\Development\dotLLM\.claude\worktrees\e8-chunks`, branch `research/e8-message-chunks` (3 LOCAL commits on `11a95292`, unpushed = only copy; review/delete after #1782 is decided or by 2026-12-01). `E8Core` tests red->green (control KL 4e-13, wrong-shift KL 0.66). `E8Command`/`E8ContextTests` written but NOT built/run; Hybrid arm dropped (needs Roslyn graph); mask = tool call to closing `}` or first 32 tokens. Recorder `experiments/E8-message-chunks/record.py` + `tasks-pilot.json` unrun. Blocked on `cpu` (held by other sessions until ~00:07 UTC). Next: build, mutants, serve Qwen3-4B/TwIL-8B check, pilot 2 tasks x 6 turns, then report before the full run.
- Do not touch trie/snapshot/`PrefixCache`/`PrefixRetention` without telling dotllm-65 first.

## Decisions (don't relitigate)
- Default policy `exact`; lossy reuse opt-in per request AND server flag; `auto` stays exact until a quality cell validates.
- No F32 dependence: backend-agnostic via `IPositionedHostKvCache`, tolerance vs measured floors, F16 target, Q8_0 later.
- Wire contract + rulings: `docs/contracts/chunk-cache-v1/README.md` (`check.py` must pass). Anthropic delta fixture does NOT carry `cache_read_input_tokens`. Namespace server-assigned; `default` reserved; keys >= 32 chars.
- Vulkan chunks in-memory only; ChunkReuse `IsPackable=false`.
- Scanner trust: MSBuild evaluation runs scanned code, analyzers/generators in-process (James accepted; opt-in untrusted mode is #1710).
- CLI: `--server` = prewarm, text only, never writes the ledger; `--offline` holds the owner lock for the whole run; key from `CHUNKCACHE_API_KEY` env only, redirects disabled. `evict --apply` needs one strong store mark or both weak ones; `list` warns (exit 0) on an unmarked dir.
- `CLAUDE.md` rules: every question via AskUserQuestion (recommended first); remove merged worktrees.

## Gotchas
- **ResourceLock for everything heavy:** `cpu`, `cpu-bench`, `gpu`; `cpu` does NOT exclude a `cpu-bench` holder: check both; release when idle. Helper agents share THIS session's lock identity. A stale MCP pipe needs `/mcp` reconnect (ResourceLock now auto-reconnects). Do not run GPU tests while another session holds `gpu`. Run no local builds during a lead's benchmark round.
- Docker in Git Bash needs `MSYS_NO_PATHCONV=1`; filter e.g. `'filter:FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse'`. A hung testhost can idle for hours: use `--blame-hang-timeout 120s`.
- **Process-wide static test hooks race across parallel xUnit classes**: per-flow `AsyncLocal`, never plain statics. Wall-clock bounds on thread-pool timers flake on loaded CI: gate the work and use a hang backstop (`HangGuard`).
- **Tests must send real wire bytes** (memory `test-real-wire-bytes`). A Python/heredoc `\n`/`\u` inside a C# string breaks: write test files with Edit/Write. A killed mutant runner leaves the scratch copy mutated: re-extract; constant-condition mutants fail to compile (use `false.Equals(true)`); a test-host crash counts as a kill; document equivalent mutants. Windows Python cannot open `/c/...`: `cygpath -w`.
- Windows vs POSIX file semantics break CI (rename under open reader, case-sensitive paths): run store/lock/ledger/index tests in Linux Docker. `DOTLLM_SKIP_VULKAN=1` does not skip Vulkan unit tests.
- Roslyn does NOT poll the token inside exponential lambda overload resolution (use corpus-budget + short grace in tests).
- Default paged server path reuses prefixes across requests (#1596): a prefix-served chunk is `prefix`, not `hit`. Never merge `origin/dev` into the server research branch directly: dev into `feature/chunk-cache` first.
- Strix GPU cap: keep `DOTLLM_VK_UMA_USABLE_FRACTION` 0.64 (`docs/superpowers/plans/2026-11-03-strix-gpu-memory-cap-remeasure.md`).

## Archives
| What | Where |
|---|---|
| Handoff before this prune (2a1-2a11 PR-by-PR narrative: #1665..#1746 reviews, fixes, numbers) | `.docs/archives/HANDOFF-ARCHIVE-2026-11-13.md` |
| Handoff before the 2026-11-06 prune (PR 10 / PR 12 narrative) | `.docs/archives/HANDOFF-ARCHIVE-2026-11-06.md` |
| Handoff 2026-11-04/05 (F16 results, Task 19, I5 Part A, PR 5-9, NPU note) | `.docs/archives/HANDOFF-ARCHIVE-2026-11-05.md` |
| Controller ledger, task reports, mutant logs | `.superpowers/sdd/2026-11-01-phase-s/`, `.../phase-g/` |
| Plans / spec | `docs/superpowers/plans/`, `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md` |
| Results | `REPORT.md`, `experiments/` |
