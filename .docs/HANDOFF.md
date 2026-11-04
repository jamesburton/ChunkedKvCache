> Live section ends at "Archives". Older material (full ledger, per-task reports) is in `.superpowers/` (GITIGNORED: the only copy) and `docs/`: do not read past this file unless a task needs it.

# Handoff: chunk-level KV reuse (dotLLM) — updated 2026-11-04

## Current state
- Goal: position-independent chunk KV reuse in the dotLLM fork (jamesburton/dotLLM; active branch `dev`; `main` tracks upstream and is protected: NEVER target or touch it). Research repo = here (branch `research/chunk-kv-reuse`).
- Maintainer/peer: session `dotllm-97` (merges PRs, files issues). `codesharp-d1` = CodeSharp session (read-only coordination; handoff appendix NOT sent).
- Upstream: MERGED #1547 client, #1575 lineage, #1577 core, #1582 CI step. OPEN: #1576 server pins (waiting CI), #1588 store (green after `83a30ed1`). Issues: umbrella #1542, #1543, #1567/#1568, #1589 (engine bugs, dotllm-97 fixing), #1590 (B2 seeder), #1591 (Vulkan has no cross-request prefix reuse).
- Local, UNPUSHED dotLLM branches (worktrees under `C:\Development\dotLLM\.claude\worktrees\`): `feature/chunk-cache` (library, CLI, scanner, selectors, B1 planner; dev merged), `feature/chunk-cache-server` (server Tasks 10-16), `feature/chunk-apply-seeder` (B2 engine hook `07df028e`, on dev `8221d6ce`, issue #1590), `feature/chunk-cache-upstream-prep` (3-assembly split), `research/chunk-kv-lab`, `pr/*` cuts.
- Reviewed + mutant-tested, all mutants killed (`.superpowers/sdd/2026-11-01-phase-s/mutant-rerun-report.md`): Task 16 server fix round (`feature/chunk-cache-server` HEAD `ea2279cf`) and Linux platform port (`feature/chunk-cache` `8ac13905`). Server branch merged `feature/chunk-cache` (`6fa9585d`). Linux Docker pass: 1105 passed / 0 failed / 5 skipped.
- F16 (dotllm-97 request; floors/speed results SENT): `feature/chunk-cache` = dev merge `5de45745` + Vulkan chunk backend F16 mode `3e569b8c` + GPU test calibration `4ec8698c` + hook flake fix `8d68357e` (local, unpushed). F16 floors == F32 floors; warm reuse 2.7-8.0x vs tiled prefill at 2K-8K; F16 makes ORDINARY prefill 1.8-3.9x faster (quote speedups vs the F16 baseline). The 'bit-identical' evidence did NOT cover the device key shift (see review above). Reports `f16-backend-report.md`, `f16-measure-report.md`; data `experiments/G0-floor-f16`, `G2-recompute-speed-f16`. Caveats: 2 contexts at 4K/8K, smaller F16 quality subsets, no F32 4K baseline.
- Works: exact/shadow server path, store/index/ledger/locks/namespaces, CLI, scanner, selector, client package, planner+AssembleAt, engine seeder hook, all reviewed + mutant-tested. NOT built: applied reuse (`balanced`) in the server (I5 Part B B3+), GPU test `VulkanServer_CpuWrittenStore_NoHits` never run.
- I5 Part A DONE (2026-11-04, `experiments/e2e-chunkcache/`, `c762882`): CPU 15/18 + Vulkan V1-V3 pass; 3 findings: F-A1/F-A2 (chunk boundary newline merges -> `chunk_template_altered`; folded into Phase I Task 19) and F-A3 (plan fixture wrong). Unexplained 36-min hang once on auth+writer server (not reproduced; owner Tasks 10-15 if it recurs). Vulkan exact overhead ~0 ms (noise > 5 ms target).
- Integration pipeline DONE 2026-11-04 (local branches, NOT pushed; James's per-PR go-ahead still required): `feature/chunk-cache-server` HEAD `22bdd19a` = merge of `feature/chunk-cache` (`11a95292`: F16 shift shader RNE + +-65504 saturation, 3 dev tests restored, GPU 12/12) + Task 19 (token-stable chunkers, lines-512 on the wire; join rule = client rule, contract ruling 75, ACCEPTED by James) + test-server fixes for dev #1596 (`9a4808b4` scheduler without prefix trie; `22bdd19a` Vulkan test servers PromptCacheEnabled=false; VulkanServer_CpuWrittenStore_NoHits now passes). Verified: full Windows suite 7538 pass / 0 fail / 57 skip; Linux Docker `unit` (7 partitions) all pass, `client` 205/205. Reports: `task-19-report.md`, `f16-fix-report.md` (in chunk-cache worktree). Task 19 e2e re-run (A3, A6, A3g, A6m) NOT done (cpu-bench was busy). Docker Desktop was started by me (4 GB VM).
- PR 5 OPEN: jamesburton/dotLLM#1622 (`pr/chunkcache-server-parse`, 2 commits on origin/dev `3e617a70`; Windows Server filter 989 pass, Docker 980 pass, 40/40 mutants killed; report `pr05-cut-report.md`). Cut recipe amendment for PRs 6-8: apply `git diff <prev milestone> <milestone>` with `git apply --3way`, NOT whole-dir checkout (reverts dev changes). Next: PR 6 after #1622 merges. Pushed with James's go-ahead for 'the next PR only'.
- Open design item (James: coexist): chunk reuse vs scheduler prefix-trie/Vulkan PrefixCache (#1596). A chunk served by the trie is reported `prefix`, never `hit`, and the ledger never sees it; make `prefix` coverage satisfy the chunk in report/accounting (also Vulkan PrefixCache + F16 #1597). Tests currently disable the trie. Not designed yet.

## Next steps
1. Integration pipeline is done (see Current state): re-run Task 19 e2e when `cpu-bench` is free; design prefix/chunk coexistence; reply to dotllm-97/93 as needed. Never merge `origin/dev` straight into the server branch (11 add/add conflicts): dev into `feature/chunk-cache` first, then that into the server branch.
2. Linux Docker check before each PR cut: `.superpowers/.../linux-ci.sh` with `-m:1 -p:UseSharedCompilation=false` (flags now in the `.superpowers` copy; csc OOMs at ~4 GB Docker VM otherwise); mounts `/src` git-ls-files snapshot, nuget volume `dotllm-nuget-app`.
4. Part B: B3 CPU applied path (`--chunk-cache-apply`, needs `--no-paged`); B4 Vulkan (F16 default is merged: target F16; NaN-holes + F16-plain-prefill GPU tests exist in `F16ChunkBackendTestsGpu`); B5 cost model; B6 quality (re-derive pass bar for placed-rows budget); B7 TTFT runs; B8 PR slicing.
5. Cut/open remaining PRs per `docs/superpowers/plans/2026-11-03-pr-split.md` (PRs 5-16): Linux-Docker check first; open/push ONLY with James's explicit per-PR go-ahead (peer requests are not authorization); merge dev INTO pushed branches (never rebase/force-push).
6. Remaining Phase I: Tasks 17 (server-backed CLI, `--offline` TryAcquire owner lock), 18 (MCP, SDK spike), 19 (in flight), 20 (GPU speed/cost calibration), 21 (release plumbing: NuGet trusted publishing details for James). Later: Phase D (F16/Q8 compact rows, direct-to-device), E10 (reuse x KV-quant), I5 validation of lines-512 (non-inferiority margin).
7. Open for dotllm-97: F16 RoPE-shift accumulation question (answer after the shift-shader fix lands); applied reuse (B3/B4) must target the F16 default.

## Decisions (don't relitigate)
- Default policy `exact`; lossy reuse opt-in per request AND server flag; `auto` stays exact until a quality cell validates. Cost: naive reuse loses accuracy, ChunkStarts 5-20% recovers 63-87% of gap (E4).
- No F32 dependence (James): backend-agnostic via `IPositionedHostKvCache`, tolerance vs measured floors, F16 target, Q8_0 later, F32 only CPU oracle.
- Wire contract + 72 rulings: `docs/contracts/chunk-cache-v1/README.md` (`check.py` must pass). Namespace server-assigned; `default` reserved; keys >=32 chars; keyless server has no store-wide destructive admin.
- Vulkan chunks = in-memory GPU-resident only (not persisted); Vulkan servers write nothing; ChunkReuse `IsPackable=false` until server PR needs it; research code stays on fork branch.
- G2b result (provisional, F32, seed 0): warm reuse 3.1-7.7x vs tiled-kernel prefill at 2K-8K; cold chunks pay only from ~16K.

## Gotchas
- **ResourceLock for everything heavy (James, 2026-11-03):** `gpu`, `cpu`, `cpu-bench`; release when idle, never sit on a lock. Another session runs big CPU model jobs without the `cpu` lock (starves Docker/probes).
- Tests that hold a file open to force a delete failure only fail on Windows: branch on `OperatingSystem.IsWindows()` and assert each OS's contract.
- Strix GPU cap (re-measured 2026-11-03, driver 26.10.1): per-process wall is 81-83 GiB OK / 82-84 fail regardless of free RAM (also with Docker/WSL off): an OS/driver limit ~0.64-0.66 x RAM; keep `DOTLLM_VK_UMA_USABLE_FRACTION` 0.64. Details `docs/superpowers/plans/2026-11-03-strix-gpu-memory-cap-remeasure.md`; probe on dotLLM `research/vk-cap-remeasure` `568c5dab`. GLM-5.3-Flash (320B-A18B, smallest quant 86.7 GiB) needs host-resident experts/tiering: plan `docs/superpowers/plans/2026-11-03-glm-5-3-flash-support.md` (lower priority than I5; start with smaller variants).
- `DOTLLM_SKIP_VULKAN=1` does NOT skip Vulkan unit tests: use `--filter "FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU"`.
- GPU locks: `scripts/gpu-lock.sh` (mandatory mutex between my agents) + ResourceLock plain `gpu` (not `Strix:GPU`: remote coordinator failure under contention); my subagents share one ResourceLock session (re-entrant). Box had unclean reboots during long ATTN_QPOS submits: keep GPU submits short.
- Windows vs POSIX file semantics broke CI (#1588): run store/lock/ledger/index tests in Linux Docker before any PR.
- Mutation runs: git-archive scratch copies in own scratch folder; mutants with constant conditions can fail to compile (counts as 'killed' wrongly: rerun compilable).
- Agents' reports/mutant logs live in gitignored `.superpowers/`; PR bodies in `docs/release/chunk-cache-issues/pr-bodies/`.

## Archives
| What | Where |
|---|---|
| Full controller ledger (chronological, rulings) | `.superpowers/sdd/2026-11-01-phase-s/progress.md`, `.superpowers/sdd/2026-11-01-phase-g/progress.md` |
| Task reports/reviews, mutant logs | `.superpowers/sdd/2026-11-01-phase-s/`, `.../phase-g/` |
| Plans / spec | `docs/superpowers/plans/` (phase-i, pr-split, i5), `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md` |
| Results | `REPORT.md`, `experiments/` (E1-E7, G0-G2, solution-scan, store) |
