> Live section ends at "Archives". Older material is in `.docs/archives/` (full pre-2026-11-05 text), `.superpowers/` (GITIGNORED: the only copy of reports/mutant logs) and `docs/`: do not read past this file unless a task needs it.

# Handoff: chunk-level KV reuse (dotLLM) — updated 2026-11-05

## Current state
- Goal: position-independent chunk KV reuse in the dotLLM fork (jamesburton/dotLLM; PRs target `dev`; `main` tracks upstream and is PROTECTED: never target or touch it). Research repo = here (branch `main`, greenfield, no ceremony).
- Peers: `dotllm-93` = dotLLM lead session: reviews (adversarial reviewer agent), merges PRs, confirms with James before merging an auth PR, opens issues. `dotllm-97` = earlier maintainer. `codesharp-d1` = read-only coordination.
- PR series (plan `docs/superpowers/plans/2026-11-03-pr-split.md`): MERGED PRs 0-8 = #1547 client, #1575 lineage, #1576 pins, #1577 core, #1588 store, #1622 parse, #1636 span locator, #1639 endpoint wiring, #1640 auth + control endpoints (dev `ad312078`). OPEN: PR 9 = #1646 (`pr/chunkreuse-csharp` `5fa6df86`, SymbolChunker + Corpus, Roslyn 5.9.0), under dotllm-93's review: DO NOT push to it. dotllm-93 also has a follow-up issue (non-blocking review items + contract fixtures re-sync: contract `fixtures.sha256` capabilities.json line 23d87cd vs dotLLM copy cfe93e3).
- Local, UNPUSHED research branches (worktrees under `C:\Development\dotLLM\.claude\worktrees\`): `feature/chunk-cache-upstream-prep` (source of truth for library/CLI cuts), `feature/chunk-cache`, `feature/chunk-cache-server` (`22bdd19a`), `feature/chunk-apply-seeder` (B2 hook, issue #1590), `research/chunk-kv-lab`. Applied reuse (`balanced`) in the server is NOT built (I5 Part B B3+).
- Prefix stays SEPARATE from hit (both counts reported; James confirmed). Open design item: make trie `prefix` coverage satisfy a chunk in accounting (#1596/#1597); not designed.

## Next steps
1. **PR 10 (index + naming), cut locally, not pushed** (James said continue with it, 2026-11-05): worktree `.claude/worktrees/pr10`, branch off `pr/chunkreuse-csharp` (PR 9 unmerged; do NOT open the PR until #1646 merges, then merge dev in). Source from `feature/chunk-cache-upstream-prep`: `Store/{ChunkIndex,ChunkIndex.Naming,ChunkRef}.cs`; tests `ChunkIndexTests`, `WireChunkingTests`, moved `Index_SavedUnderOtherNamespace_LoadsEmptyWithNote`. Restore what PRs 8/9 trimmed: 3 `ChunkIndex.DefaultPath` lines in `ChunkCacheEndpointTests.Capabilities_MatchesFixtureShape` and the 2 `ChunkIndex.Update` calls at the end of `CorpusTests.FixedSizeChunker_EncodeStripsACharacter_ChunksTileAndMatchTheirIds`. Core diff dev vs prep also has ChunkNamespace/ChunkStoreBusyException/FileChunkStore/StoredContextAssembler tweaks: check what PR 10 needs. Mutants: `phase-i-task-4b-mutate.py`, `phase-i-task-5-mutants.py` (anchors may be stale; adapt like pr07/pr09 scripts). Linux Docker check before handing over.
2. Hand-over flow for every PR (needs James's explicit per-PR go): Windows tests, Linux Docker, mutants on a fresh `git archive` copy (verify copy pristine afterwards), cut report `.superpowers/sdd/2026-11-01-phase-s/prNN-cut-report.md`, body `docs/release/chunk-cache-issues/pr-bodies/prNN-*.md`; merge dev INTO the branch (never rebase/force-push); push; `gh pr create --base dev --body-file` (utf-8 file under the scratchpad path); fix a body with `gh api -X PATCH repos/jamesburton/dotLLM/pulls/N -F body=@file` (`gh pr edit` fails on token scope); `SendMessage` dotllm-93 to review + merge; never push to a PR under review.
3. Then PRs 11-15 per the plan: 11 locks/ledger/registry, 12 graph + selection (in `.CSharp`), 13 Solution scanner, 14 Vulkan backend, 15 CLI (after Phase I Task 17). Remaining Phase I: 17 server-backed CLI, 18 MCP, 20 GPU calibration, 21 release plumbing.
4. When `cpu-bench` is free: re-run Task 19 e2e (A3, A6, A3g, A6m) in `experiments/e2e-chunkcache/` against `feature/chunk-cache-server` `22bdd19a`+ (hold the lock only while running).
5. Part B (after the PR series): B3 CPU applied path (`--chunk-cache-apply`, needs `--no-paged`), B4 Vulkan (target F16), B5 cost model, B6 quality, B7 TTFT runs. Open for dotllm-97: F16 RoPE-shift accumulation question. LOW priority: NPU exploration (no fit today; see archive).

## Decisions (don't relitigate)
- Default policy `exact`; lossy reuse opt-in per request AND server flag; `auto` stays exact until a quality cell validates.
- No F32 dependence: backend-agnostic via `IPositionedHostKvCache`, tolerance vs measured floors, F16 target, Q8_0 later.
- Wire contract + rulings: `docs/contracts/chunk-cache-v1/README.md` (`check.py` must pass). Ruling 46: the Anthropic delta fixture does NOT carry `cache_read_input_tokens` (ruling 40 prevails). Namespace server-assigned; `default` reserved; keys >= 32 chars.
- Vulkan chunks are in-memory only; ChunkReuse `IsPackable=false`; research code stays on fork branches. `--chunk-cache-max-chunks` is 1..65536.

## Gotchas
- **ResourceLock for everything heavy:** `cpu`, `cpu-bench`, `gpu`; release when idle. Docker in Git Bash needs `MSYS_NO_PATHCONV=1` (path mangling otherwise); run Docker with `linux-ci.sh` (4 GB VM; `-m:1`), filter e.g. `'filter:FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse'`.
- **Tests must send real wire bytes** (memory `test-real-wire-bytes`): a vacuous HTTP test hid a real HTTP 500 on #1639. Also: a Python/heredoc `\n` inside a C# string literal turns into a real newline: write test files with the Edit/Write tools; never `open(p,'w')` a gitignored file before its content is built (the PR 7 cut report was truncated once).
- Mutation runs: scratch `git archive` copy in own folder, filter by the PR's namespace; constant-condition mutants fail to compile (use `false.Equals(true)`); a killed runner leaves the copy mutated: re-extract fresh. Equivalent mutants are documented, not tested around.
- Windows vs POSIX file semantics break CI: run store/lock/ledger/index tests in Linux Docker before any PR. `DOTLLM_SKIP_VULKAN=1` does not skip Vulkan unit tests (filter `FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU`).
- Default paged server path reuses prefixes across requests (#1596): a prefix-served chunk is `prefix`, not `hit`; tests that expect a hit must avoid a shared prefix. Never merge `origin/dev` into the server research branch directly (add/add conflicts): dev into `feature/chunk-cache` first.
- Strix GPU cap: keep `DOTLLM_VK_UMA_USABLE_FRACTION` 0.64 (details in archive/`docs/superpowers/plans/2026-11-03-strix-gpu-memory-cap-remeasure.md`).

## Archives
| What | Where |
|---|---|
| Full handoff as of 2026-11-04/05 (F16 results, Task 19, I5 Part A, PR 5-9 narrative, NPU note) | `.docs/archives/HANDOFF-ARCHIVE-2026-11-05.md` |
| Controller ledger, task reports, mutant logs | `.superpowers/sdd/2026-11-01-phase-s/`, `.../phase-g/` (cut reports `pr05..pr09-cut-report.md`) |
| Plans / spec | `docs/superpowers/plans/` (phase-i, pr-split, i5), `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md` |
| Results | `REPORT.md`, `experiments/` (E1-E7, G0-G2, solution-scan, store, e2e-chunkcache) |
