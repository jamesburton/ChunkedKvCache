# Phase S Task 7 report: `chunkcache` CLI and compare

**Status: DONE_WITH_CONCERNS.** The CLI, its tests and the dotLLM demo are done; the concerns are listed at the end.

## Commits

dotLLM worktree `C:\Development\dotLLM\.claude\worktrees\chunk-cache`, branch `feature/chunk-cache`, not pushed:

- `99aceb24` the `chunkcache` CLI (`tools/DotLLM.ChunkCache`, in `dotLLM.slnx`, `IsPackable=false`, assembly
  `chunkcache`), `FileChunkStore.TryReadFingerprint`, `ChunkCacheCliTests`, and a byte-level vocabulary option in
  `SyntheticDenseGguf`
- `a41c90c2` compare: with `--json` the table goes to stderr
- `8788e78c` **library fix:** `FixedSizeChunker`'s last chunk ends at the end of the text (found by the demo, see below)
- `94ed8630` tests: KL direction, top-1, line range; partial recompute must differ from full prefill
- `1ce81e82` tests: `--order rank` vs `document` (mutant M21 survived the first round)

ChunkedkvCache (own paths only): `experiments/chunkcache-demo/` (`README.md`, `run.ps1`, `logs/`), this report,
`task-7-mutants.log`, `task-7-mutants.py`.

## What was built

**Verbs** (`chunkcache <verb> --help` documents each):

- **`build`** `--model M --store DIR (--solution X | --directory D)`, plus:
  - `--chunker symbol|fixed`, `--chunk-tokens 512`, `--configuration` (default **Release**)
  - `--strict`, `--strict-model-id`, `--json`, `--max-chunks N`, `--dry-run`
  - selection options (`--path`, `--symbol` + `--hops`, `--since` [`--merge-base`], `--exclude`, `--budget`,
    `--max-per-hop`): encode only what the selection picks; the whole tree is still indexed
  - `--reroot`, `--lock-timeout`, `--threads` (default min(8, cores))
- **`select`**: `ContextSelector` options plus `--order rank|document`, `--include-text`. With `--store` the source
  defaults to the one recorded for the index, and each chunk says whether it is stored.
- **`status`**: missing chunks by file and line range; stale/new/deleted files after a rescan (`--no-scan` skips it);
  store statistics; `--strict` exits 3 when not up to date; `--list-missing`.
- **`evict`**: a dry run by default, listing `ChunkIndex.StoreWideOrphans`. `--apply` deletes them under the store
  lock. `--all-for-model --model M` selects every entry whose **header** fingerprint is M's
  (`FileChunkStore.TryReadFingerprint`, new, reads the header only), plus M's index files.
- **`compare`** `--task FILE --selectors chunkstarts,queryrelevance,hybrid,deviation,random,firstk --budgets 5,10,20
  --chunkers fixed,symbol`. It prints one table row per chunker × arm: KL(full ‖ reuse), top-1, exact match (when the
  task gives the continuation), tokens recomputed, forward calls, reuse ms (assembly + scoring + selection + recompute +
  query) vs full ms, speedup, and **the path of each timing** (`cpu-prefill` / `cpu-per-run`).

**Exit codes** (help text and `ExitCodes`): 0 ok; 1 error (I/O, busy lock, model load, symbol not found, unreadable
index); 2 usage; 3 strict failure (`build --strict`: skipped projects, unattributed load failures, files on another
volume; `status --strict`: not up to date).

**Contracts honoured:**

- `RelativizeScan` for scanner paths. Files on another volume are excluded with a warning and fail `--strict`.
- When the root widens (e.g. a `.csproj` whose files reach `../Lib`), the scan's per-project compilations are
  **re-keyed** to index paths, so the graph and the selector work. Test: App.csproj → root = fixture root, and the
  App → Lib edge resolves.
- One index file per chunker.
- `ContextSelector(files, graph, git, root)` with `ChangedSince`/`MergeBase`; git is created only when `--since` is given.
- `SolutionScanOptions.Configuration`: `--configuration`, default Release.
- `StoredContextAssembler.ForModel` + `GgufIdentity` (sampled id; `--strict-model-id` hashes every byte).
- Isolated positioning (the assembler's keys).
- `SelectiveRecomputer` behind `IRecomputeStrategy`.
- `StoreWideOrphans` + `AcquireStoreLock`: **build holds the lock from index update through every put to the end**. The
  index is saved before encoding, and encoding is driven from `Status` (everything missing), not the diff, so an
  interrupted build resumes. `evict --apply` holds the lock from the orphan computation through the deletes.
- Unattributed `Failure` diagnostics fail `--strict` (re-review N10). An extra target framework is informational.

**Store layout additions** (decisions, not in any spec):

- **Index file name `index-<chunker>.<producer12>.json`**, one per chunker **and model**. A plain
  `index-<chunker>.json` (L9) is overwritten by a second model's build, whose `Load` sees another producer and starts
  empty, orphaning the first model's entries. Mutant M12 shows the tests catch this. **Deviation from L9; flag for the
  integration spec.**
- **`chunkcache.json`** in the store root records each index's tree root, source, configuration and model (not named
  `index-*`, so eviction ignores it). A build against a different root is refused (exit 1) unless `--reroot`.

**JSON (`--json`)**: one document on stdout, snake_case. The result field names of `chunkcache_build`, `_select`,
`_status` and `_evict` (integration spec §7.2) are present, and a test checks them. CLI-only extras are added
alongside. Progress and warnings go to stderr. Differences a thin MCP wrapper must map:

- **Inputs:**
  - the chunker is `symbol|fixed` plus `--chunk-tokens`, not `symbol-512`
  - evict modes are `orphans` and `all_for_model` only (no `path`/`namespace`)
- **`wire_ineligible_chunks`** (build) counts only the chunks this run encoded (`EncodeRaw(text) == ids`), and is absent
  on a dry run.
- **`stored`** is answered from the local store.
- **Offline writer:** the CLI encodes and writes itself (L1 allows this when no server runs, under the lock).

**`compare`:**

- **Backend seam:** `IChunkBackend` is not on this branch. `compare` goes through an internal `IRecomputeStrategy`, with
  one implementation, `CpuPerRunRecompute` (`SelectiveRecomputer`: one forward per contiguous run). A single-pass Vulkan
  strategy plugs in there, and every timing row names its path. The help text and table footer say that on CPU the
  recompute is per run.
- **Store access:** the store is read-only (`ReadOnlyChunkStore`). Misses are encoded in memory, counted and flagged.
- **Task file:** JSON with
  - `select` (the select options)
  - exactly one of `query` / `query_from` (a corpus file's lines; then the graph knows the query's references, for
    hybrid)
  - an optional `continuation`. Without it, the reference is full prefill's greedy output and EM is omitted.
  - Unknown fields are a usage error.

## Tests (`tests/DotLLM.Tests.Unit/ChunkReuse/ChunkCacheCliTests.cs`, 24 tests)

**Setup:**

- Everything runs in process (`ChunkCacheCli.Run(args, out, err, workingDirectory)`).
- **Model:** two synthetic qwen3 GGUFs (seeds 7 and 8) with a new **byte-level GPT-2 vocabulary** option. The GGUF's own
  tokenizer encodes one token per byte, so the real `ModelHandle` / `GgufBpeTokenizerFactory` / `GgufIdentity` path is
  exercised.
- **Sources:** a generated 3-file source tree and the Task 5 MiniSolution fixture.
- **Oracles are independent of the CLI:**
  - the index file loaded by the library
  - the store's files
  - `ChunkIndex.Status`
  - the synthetic geometry for the size estimate
  - full prefill for 100 % recompute

**Coverage:**

- exit codes and output for each verb
- `Build_Rerun_IsAllHits`: nothing re-encoded, and the entry files are untouched
- `Build_SkippedProject_ExitsNonZeroOnlyWithStrictFlag`: slnx 0 → `--strict` 3 with nothing written; App.csproj
  `--strict` 0
- dry run: writes no index and no entries; the estimate equals the real store size byte for byte
- `--max-chunks` and resume
- selection-restricted encoding
- `--reroot`
- status after edit, new and deleted files; a rebuild encodes only the keys of the edited and new files
- select: paths, symbol and hops, budget, order, wire hash, stored flags, symbol-not-found → 1; the cross-project
  symbol on a widened root
- evict dry run does not delete; `--apply` deletes exactly the orphans
- evict keeps entries referenced by any index (symbol + fixed + a second model's index); an unreadable `index-*.json`
  blocks eviction
- `--all-for-model`
- lock tests:
  - a held lock makes `build` and `evict --apply` exit 1 with nothing written; the dry runs still work
  - a hook inside build, after the index save, runs `evict --apply`, which must fail
  - concurrent build + evict leave the store complete (4 rounds; weak as a race detector, the hook test is the
    deterministic one)
- paths with spaces and non-ASCII characters (`my src ü 日本`, `Ünïcødé Name.cs`), a relative `--store` and a relative
  `--model`
- `Compare_PrintsTheTable…` (adapted from `Compare_PrintsTableWithBothPaths`):
  - row count; the `cpu-per-run` / `cpu-prefill` path names; tokens recomputed equals the budget
  - **100 % recompute is exactly full prefill (KL < 1e-9, top-1 1, one forward)**
  - every partial arm differs from full prefill
  - the text table
- cold compare writes nothing
- bad task or selector → 2
- the KL direction and line-range helpers
- the MCP schema names

**Results:**

- **RED:** in a `git archive` copy, with every verb throwing `NotImplementedException` after argument parsing, 23 of 24
  fail; the metrics-helper test does not go through a verb. **Process note:** I wrote a first implementation before the
  tests rather than strictly test-first. The RED evidence is the stub run.
- **GREEN:** 24 of 24. The whole ChunkReuse suite: 499 passed, 1 skipped (the existing backend-tag TODO).
- The `FixedSizeChunker` fix has its own test (`CorpusTests.FixedSizeChunker_DecodeDropsACharacter_ChunksStillTileTheFile`),
  which fails on the old chunker and passes on the fix.

## Mutation evidence (`task-7-mutants.log`, script `task-7-mutants.py`)

- **Where:** a `git archive` copy at a short temp path. The scratchpad path is too long for the fixture paths (MAX_PATH),
  and the first attempt silently extracted a partial tree; that run is discarded.
- **Result: 35 mutants, 33 killed, 2 survive.** After round 1, M21 (`--order rank` ignored) survived and was killed after
  a test was strengthened (`1ce81e82`), and M25 did not compile, was rewritten, and was killed. Pristine runs pass before
  and after.
- **Killed:**
  - encoding driven by the diff
  - the build takes no lock, or releases it after the index save
  - `--strict` ignored; an extra TFM fails `--strict`
  - dry run saves the index
  - `--max-chunks` off by one
  - other root accepted
  - selection ignored
  - estimate counts K only, or omits headers
  - compilations not re-keyed
  - one index per chunker, not per model
  - orphans ignore an index
  - evict dry run deletes
  - `--all-for-model` takes every entry, or keeps the index files
  - evict takes no lock
  - status `--strict` never fails; status ignores the rescan
  - stored flag always true
  - wire hash over UTF-16
  - KL direction swapped
  - recompute only the first position
  - compare writes misses
  - arms reuse the previous arm's cache
  - list options not split
  - usage errors exit 1; busy lock exits 2
  - header fingerprint misread
  - wire-eligibility inverted
  - relative paths against the process directory
- **Survivors:**
  - **M33** (an arm's exact match read from the reference rows): not killable with this fixture, because EM equals
    full's at 100 % and is unconstrained elsewhere. Would need a continuation equal to full's greedy output, which
    byte-level greedy output cannot round-trip as text.
  - **M34** (unattributed load failures do not fail `--strict`): equivalent on the MiniSolution, where Broken already
    fails `--strict` as a skipped project.

## Step 5: the dotLLM solution with Qwen3-4B Q4_K_M (CPU, 8 threads)

Full write-up: `experiments/chunkcache-demo/README.md`. Run at dotLLM `94ed8630`, dirty=0, Release; the CPU was shared
with E4c.

**Dry run of a full encode:**

- 29 projects, 0 skipped, 2,534 authored files
- symbol-512: 40,029 chunks, 8,044,994 tokens (7,877,157 distinct)
- estimated store **2.11 TiB** (8,192 B/token/layer × 36)
- about **31–33 h** of CPU encode at the measured 66–71 tokens/s
- **Not run.** The disk had 47 GB free.

**Budgeted build:** the whole tree indexed, plus the 2-hop neighbourhood of `ChunkIndex.Update` under 24,000 tokens
encoded:

- 81 chunks / 23,708 tokens in 360 s (**65.9 tokens/s**)
- total 491 s: scan 22 s, index 35 s, graph and selection 71 s
- **rerun:** added/removed 0, 0 encoded, 107 s (dominated by the scan and the graph; the index update takes 0.3 s)
- **fixed-512** compare context: 8 chunks / 3,935 tokens in 56 s
- **store:** 89 entries, **8,152,403,216 B** (27,643 tokens × 294,912 B + 150,800 B of headers). The pre-encode
  estimate uses the same formula. The store was deleted afterwards.

**Compare** (one task):

- **Task:**
  - context: the 1-hop neighbourhood of `ChunkIndex.Update` under 4,096 tokens, without the query's file
  - query: `BuildCommand.cs` lines 155–166
  - expected continuation: the `index.Update` call
- **Warm store:** 15 symbol or 8 fixed chunks, every one a store hit.
- **Full prefill:** 147 s (symbol) / 132 s (fixed) for about 3.9K tokens plus a 225-token query, slow on the contended CPU.
- **Naive:** KL 0.24 / 0.31, 12.4× / 10.9× faster.
- **Chunk starts:** 5–20 % gives KL 0.03–0.04 (symbol) at 7.6–4.6× faster, with 10–14 forwards.
- **Query relevance:** KL 0.024 at 10 % (symbol), but 139–369 forwards, so only 1.4–1.8× faster.
- **Hybrid:** poor at 5–10 % on this task (KL 0.18–0.30).
- **EM:** uninformative; full prefill itself misses one of the 13 tokens.
- **Path:** every recompute timing is `cpu-per-run`, and the run count sets the cost.
- **Run time:** 20.5 min.

**Bug found by the demo and fixed (`8788e78c`):**

- `build --chunker fixed` failed on dotLLM. `src/DotLLM.Tokenizers/ControlTokenGuard.cs` holds U+FDD0, which the Qwen BPE
  decode drops. `FixedSizeChunker`'s decode-based offsets fell one character short, so the chunks did not tile the file
  and `ChunkIndex.Update` refused it. This is the drift the Task 4 re-review (R2) predicted.
- **Fix:** the last chunk always ends at the end of the text.
- **What it does not change:** symbol chunking is untouched. The pinned fixed corpora already tiled, since
  `index-roundtrip` and `Update`'s tiling check passed on them, so their hashes should not move. I did not re-run them.
- Interior offsets can still drift by dropped characters.

**Process note:** the first demo run picked up an uncommitted test edit I made in the worktree while the scan ran (40,020
vs 40,018 chunks). It was stopped by task id and discarded. The second run, after the chunker fix, failed at the fixed
build; the reported run is a complete rerun at `94ed8630`.

## Concerns

1. **Lock scope:** build holds the exclusive store lock for the whole encode (6 min here, hours on a real tree). That is
   the current `AcquireStoreLock` contract, but integration spec L3 wants short scopes and a per-index lock. Needs the
   L3 change before a server shares a store.
2. **Index naming deviates from L9** (`index-<chunker>.<producer12>.json`, for multi-model stores). The integration spec
   should adopt it or choose another per-model scheme.
3. **Every `select` / `compare` / selection-`build` builds the Roslyn graph over the whole solution:** about 70–80 s on
   dotLLM, plus a 21–25 s scan. No graph cache.
4. **`FixedSizeChunker` interior offsets** can still drift on characters the decode drops or replaces. A proper fix is
   prefix-decode offsets, or the `lines-512` chunker (L6).
5. **The demo timings are rough:** one task, a shared CPU, slow full prefill. Exact match was uninformative on the
   chosen task.
6. **Mutation survivors M33 and M34** (see above). The concurrent build/evict test is weak as a race detector; the
   deterministic hook test covers the lock.
7. **Unverified on Linux and macOS.** The tests use Windows-only paths nowhere, but the scanner fixture and path casing
   are Windows-verified only.
8. **Analyzer warnings:** the test file has analyzer warnings (MA0006/IDISP004 style), like the repo's other test files.
   The tool project builds with no warnings.
9. **`SyntheticDenseGguf.Build` gained an optional parameter.** Defaults are unchanged, and the other tests pass.

## Fix round 1 (summary pasted by controller from the implementer's final message)

dotLLM fb351745, aa11975a; ChunkedkvCache 028ce89. S1 selection applied before dedupe-by-key; S2 registry index names validated before delete; S3 scan/graph/selection before the lock; S4 UTF-8 stdout/stderr (no BOM, child-process test), repeatable list options, comma in a value = usage error (exit 2); S5 --json failures print {"error":{"code","exit_code","message"}} on stdout; S7 diagnosis corrected (U+FDD0 stripped at encode), offsets after the marker now exact; S8 full row real forward count, one untimed warm-up, "continuation exact match", reuse time = sum of parts test, compare refuses non-CPU recompute strategy; S9 catch-all exit 1 (stack with --verbose), build exits 1 if a store write failed, read-only verbs and --dry-run don't create the store dir. Tests: 29 CLI + chunker test; ChunkReuse 504 (+1 skip). Mutants 17 run, 16 killed, 1 equivalent (F10). No test for S3 lock move or the warm-up.
Notes for Tasks 17/18: build encodes everything by default, MCP chunkcache_build defaults index-only (--max-chunks 0 = index-only today); --max-chunks counts chunks, MCP max_encode_tokens counts tokens; CLI-only fields beside schema fields (nest under extras or declare outputs open); budget_bytes never emitted; evict modes orphans/all_for_model with --apply instead of dry_run; --server, CHUNKCACHE_API_KEY, optional --model left to Task 17 (a server-backed CLI must key with the server's producer).
Notes for Task 5b: file list must add FixedSizeChunker and the CLI's own raw encodes (build's wire-eligibility check, compare's query and continuation); codesharp's pinned symbol-512/fixed-512 hashes will change under 5b (<think> at CompactionSummaryValidation.cs:57); FixedSizeChunker skips only U+FDD0, must follow if 5b changes what the encoder strips. Open: non-empty file encoding to zero ids gets no chunks and the index refuses it; M33/M34 survive; drive-relative C:foo paths not handled.
