> Live section ends at "Archives". Older material (full ledger, per-task reports) is in `.superpowers/` (GITIGNORED: the only copy) and `docs/`: do not read past this file unless a task needs it.

# Handoff: chunk-level KV reuse (dotLLM) — updated 2026-11-03

## Current state
- Goal: position-independent chunk KV reuse in the dotLLM fork (jamesburton/dotLLM; active branch `dev`; `main` tracks upstream and is protected: NEVER target or touch it). Research repo = here (branch `research/chunk-kv-reuse`).
- Maintainer/peer: session `dotllm-97` (merges PRs, files issues). `codesharp-d1` = CodeSharp session (read-only coordination; handoff appendix NOT sent).
- Upstream: MERGED #1547 client, #1575 lineage, #1577 core, #1582 CI step. OPEN: #1576 server pins (waiting CI), #1588 store (green after `83a30ed1`). Issues: umbrella #1542, #1543, #1567/#1568, #1589 (engine bugs, dotllm-97 fixing), #1590 (B2 seeder), #1591 (Vulkan has no cross-request prefix reuse).
- Local, UNPUSHED dotLLM branches (worktrees under `C:\Development\dotLLM\.claude\worktrees\`): `feature/chunk-cache` (library, CLI, scanner, selectors, B1 planner; dev merged), `feature/chunk-cache-server` (server Tasks 10-16), `feature/chunk-apply-seeder` (B2 engine hook `07df028e`, on dev `8221d6ce`, issue #1590), `feature/chunk-cache-upstream-prep` (3-assembly split), `research/chunk-kv-lab`, `pr/*` cuts.
- Agents running at handoff (may have died with the session; check each worktree `git log`/`status` + reports): Task 16 fix round (server worktree `chunk-cache-server`, mutant re-run) and Linux-port agent (`chunk-cache` worktree: ports `83a30ed1` platform fixes, Linux Docker test pass).
- Works: exact/shadow server path, store/index/ledger/locks/namespaces, CLI, scanner, selector, client package, planner+AssembleAt, engine seeder hook, all reviewed + mutant-tested. NOT built: applied reuse (`balanced`) in the server (I5 Part B B3+), GPU test `VulkanServer_CpuWrittenStore_NoHits` never run.

## Next steps
1. Read newest reports in `.superpowers/sdd/2026-11-01-phase-s/` (`phase-i-task-16-report.md`, `linux-port-report.md`); review/accept (reviewer = opus agent on diff; fix round; accept w/o re-review only if docs-only/covered by mutants).
2. Merge `origin/dev` into `feature/chunk-cache-server` (`git merge`, one-hunk test csproj conflict: keep both sides); apply the Linux platform port there; then run CI-equivalent tests in Docker Linux (command in `pr1588-ci-fix-report.md`).
3. Part A e2e scripts (`docs/superpowers/plans/2026-11-03-phase-i5-applied-reuse.md`) in `experiments/e2e-chunkcache/`; real Qwen3-4B; take `cpu-bench`/`gpu` locks.
4. Part B: B3 CPU applied path (`--chunk-cache-apply`, needs `--no-paged`); B4 Vulkan (waits for dotllm-97's F16-default merge; add NaN-holes + F16-plain-prefill tolerance GPU tests); B5 cost model; B6 quality (re-derive pass bar for placed-rows budget); B7 TTFT runs; B8 PR slicing.
5. Cut/open remaining PRs per `docs/superpowers/plans/2026-11-03-pr-split.md` (PRs 5-16): Linux-Docker check first; open/push ONLY with James's explicit per-PR go-ahead (peer requests are not authorization); merge dev INTO pushed branches (never rebase/force-push).
6. Remaining Phase I: Tasks 17 (server-backed CLI, `--offline` TryAcquire owner lock), 18 (MCP, SDK spike), 19 (`lines-512` on wire), 20 (GPU speed/cost calibration), 21 (release plumbing: NuGet trusted publishing details for James). Later: Phase D (F16/Q8 compact rows, direct-to-device), E10 (reuse x KV-quant), I5 validation of lines-512 (non-inferiority margin).
7. When dotllm-97 pings F16-default merged: re-measure G0 floors + G2b on F16; ask about F16 RoPE-shift accumulation result.

## Decisions (don't relitigate)
- Default policy `exact`; lossy reuse opt-in per request AND server flag; `auto` stays exact until a quality cell validates. Cost: naive reuse loses accuracy, ChunkStarts 5-20% recovers 63-87% of gap (E4).
- No F32 dependence (James): backend-agnostic via `IPositionedHostKvCache`, tolerance vs measured floors, F16 target, Q8_0 later, F32 only CPU oracle.
- Wire contract + 72 rulings: `docs/contracts/chunk-cache-v1/README.md` (`check.py` must pass). Namespace server-assigned; `default` reserved; keys >=32 chars; keyless server has no store-wide destructive admin.
- Vulkan chunks = in-memory GPU-resident only (not persisted); Vulkan servers write nothing; ChunkReuse `IsPackable=false` until server PR needs it; research code stays on fork branch.
- G2b result (provisional, F32, seed 0): warm reuse 3.1-7.7x vs tiled-kernel prefill at 2K-8K; cold chunks pay only from ~16K.

## Gotchas
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
