# Selection tools: `ContextSelector` (Phase S Task 6)

**Question:** given a scanned solution, which chunks go into a context? The selection can be made by path globs, by the
reference-graph neighbourhood of a symbol, or by the files changed since a git revision. It is trimmed to a token budget,
the order is deterministic, and each chunk records why it was picked.

**Answer:** `ContextSelector` does this in 0.17–0.51 s on dotLLM once the graph is built. The corpus is 8.0 M tokens in
39,651 symbol chunks with 375 K edges. The first request in each process includes JIT, and later ones take 0.17–0.30 s.
Scanning, chunking and building the graph take about 80 s, a one-off cost that `chunkcache` (Task 7) will persist.
- The 2-hop neighbourhood of `ChunkIndex.Update` is **378 chunks / 90.5 K tokens in 45 files**.
- Under 20 K tokens the selection keeps **71 chunks / 19.9 K tokens in 13 files**: the definition, all of hop 1, and the
  part of hop 2 with the most edges to or from hop 1.

The code is in dotLLM, worktree `chunk-cache`, branch `feature/chunk-cache`, at `1f87c375`. It is not pushed. The source
is under `src/DotLLM.ChunkReuse/Tooling/`. The tests are `tests/DotLLM.Tests.Unit/ChunkReuse/ContextSelectorTests.cs` and
`GitCliInfoTests.cs`, and the lab command is `benchmarks/ChunkKvLab/SelectCommand.cs`.

## API

```csharp
SelectionResult ContextSelector.Select(SelectionRequest request, IReadOnlyList<SourceFile> files, ReferenceGraph graph,
                                       IGitInfo? git = null, string? rootDirectory = null)
```

- **`files`**: the corpus files. For a solution, pass `ChunkIndex.RelativizeScan(scan.AuthoredFiles, scan.RootDirectory).Files`.
  The `graph` must be built over chunks of these files, and a chunk whose file is not among them is an `ArgumentException`.
  Token counts are the chunks' own token ids, so the selector needs no chunker or tokenizer.
- **No dependency on the Solution assembly.** `ContextSelector` is in `DotLLM.ChunkReuse` and does not reference
  `DotLLM.ChunkReuse.Solution`. This follows the controller's ruling; the plan's `Select(..., ScanResult, ...)` would have
  been a circular reference. Skipped projects and diagnostics stay in the CLI (Task 7).
- **`git` and `rootDirectory`** are needed only for `ChangedSince`. `GitCliInfo(workingDirectory)` is the real
  implementation; tests use a fake.
- **`SelectionRequest` fields:**
  - `Paths`: globs; a leading `!` negates.
  - `Exclude`: globs.
  - `Symbol` and `Hops`: default 1, at most 100.
  - `ChangedSince`: a git revision.
  - `ChangedSinceMergeBase`.
  - `TokenBudget`.
  - `EdgeKinds`: default Call, Use and Definition. Imports are left out because a namespace links everything that uses it.
  - `MaxNeighboursPerHop`: off by default.
  - `ChunkKind`: stamped on each `ChunkRef`.
- **`SelectionResult`** is an `IReadOnlyList<SelectedChunk>` in rank order. It also carries:
  - `Trimmed`;
  - `SelectedTokens` and `CandidateTokens`;
  - `SymbolDefinitions`;
  - `UnmatchedPatterns` and `UnmatchedChangedFiles`;
  - `Notes`: excluded definitions, excluded changed files, capped hops;
  - `InDocumentOrder()`, the order for assembling a context.
- **`SelectedChunk`** is `ChunkRef` + `Reason` + `Priority` + `Detail`. It also has:
  - `Reasons`: every criterion the chunk matched, as flags;
  - `Hop`;
  - `Weight`: edges to or from the previous hop.

## Semantics

- **The criteria are a union.** A chunk matched in several ways appears once. It keeps the highest-priority reason and all
  the flags. `Exclude` removes files from every criterion (path, changed, symbol) and also cuts the symbol walk.
- **Priority** (higher is kept longer):

  | reason | priority |
  |---|---:|
  | definition: the chunk that holds the declaration's name | 1000 |
  | definition body: the rest of the declaration | 900 |
  | path glob | 800 |
  | changed since the revision | 700 |
  | neighbour at hop h | 600 − h |

  Ties are broken by `Weight` (descending), then by path (**ordinal**, independent of the current culture), then by offset.
- **Path above changed.** A glob names the files the caller wants, while a git range sweeps in merges. The first version
  ranked changed above path, and the paths + since example then trimmed every requested `Tooling/` chunk.
- **Trimming is strict.** The selection is the longest prefix of the ranking that fits the budget. Once a candidate does not
  fit, nothing ranked below it is taken, even if it is smaller; a lower priority never displaces a higher one. A budget
  smaller than the first candidate gives an empty selection, with everything in `Trimmed`.
- **The neighbourhood walk** is breadth-first over the selected edge kinds, in both directions. A Caller has an edge into
  the previous hop; a Callee is the target of an edge from it. Edges inside one chunk are ignored.
  - **`MaxNeighboursPerHop`** (off by default) keeps the best neighbours of each hop (weight, path, offset). The walk
    continues from those only. Dropped neighbours are not reconsidered at later hops, and a note records how many were
    dropped. It bounds the fan-out through hub types such as `Chunk` and `ChunkRef`.
- **Symbol lookup** is syntax-based (`SymbolLocator`). It accepts a simple name or a dotted suffix of the qualified name.
  Generic arguments, a parameter list and `global::` are ignored, and matching is case-sensitive.
  - It finds types, delegates, methods, constructors, properties (including **positional record parameters**), events,
    fields and enum members. Every matching declaration counts.
  - With no match, `SymbolNotFoundException` names the symbol and suggests close names (another case or another container).
    A declaration that the graph has no chunk of gives the same exception, naming the file.
  - **Not supported:** indexers, operators, conversion operators and finalizers. Their names are not identifiers, and a
    keyword such as `this` is rejected with a message saying so. Declarations inside inactive `#if` regions are not found
    (no preprocessor symbols). Identifiers written with `\uXXXX` escapes are skipped by the text prefilter. Overloads cannot
    be told apart, because the parameter list is ignored.
- **Globs:**
  - `*` and `?` match within one path segment; `**` as a whole segment matches any number of segments.
  - A bare name such as `*.cs` matches at any depth.
  - A trailing `/` means the whole directory.
  - **Every other character is literal**, so `[ab]` and `{a,b}` match those exact characters, not gitignore classes or
    alternatives.
  - `\` is a separator, and `.` and empty segments are dropped in both patterns and paths (`./src//x.cs` = `src/x.cs`).
  - Matching is case-insensitive on Windows (as `RoslynGraphBuilder.PathComparer`), and the regex is non-backtracking.
  - Rooted patterns (`/x`, `C:\x`, `c:x`, UNC) and `..` segments are rejected. A path outside the root (`../x`, or a path on
    another volume) never matches a glob, though the symbol walk or `ChangedSince` can still reach it if it is in the corpus.
- **Git (`GitCliInfo`):**
  - **Requirements:** git on PATH. **Git 2.30 or later is recommended**: `rev-parse --end-of-options` is used only from
    2.30 (`GitVersion` is detected once). Older git still works safely, because `ValidateRef` already rejects every
    revision that git could read as an option.
  - **Injection:** arguments are passed through `ProcessStartInfo.ArgumentList`, never through a shell. `ValidateRef`
    rejects, before git runs: an empty ref, leading or trailing white space, a leading `-` (for example `--output=FILE`),
    and control characters. Only the resolved SHA (40 or 64 hex digits) reaches
    `diff --name-only -z --no-renames --no-ext-diff --no-textconv <sha> --`.
  - **Two-dot by default:** the working tree against the revision, plus untracked, non-ignored files.
    **`ChangedSinceMergeBase`** compares against `merge-base <ref> HEAD` instead: this branch's changes since it forked
    (`<ref>...HEAD`), plus uncommitted and untracked ones. Unrelated histories give a "no merge base" `GitException`.
  - **Links:** paths are made absolute under the working directory's spelling of the top level (`rev-parse --show-cdup`).
    `--show-toplevel` would resolve junctions, symlinks and `subst` drives, and a solution opened through a link would
    then match nothing. `ContextSelector` also maps a resolved path against the link-resolved root, for other `IGitInfo`
    implementations. `subst` drives are handled by the first mechanism only.
  - **Environment:** every inherited `GIT_*` variable is removed from git's environment. `GIT_DIR`, `GIT_WORK_TREE`,
    `GIT_INDEX_FILE` and the like, set by a git hook or a wrapper, would otherwise point git at another repository or index.
    Git also runs with `GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0` and `core.fsmonitor=false`, and is killed by its
    process handle on timeout. A missing executable is a clear `GitException`.
  - **Mapping:** changed paths are mapped to corpus paths against `rootDirectory` (case-insensitively on Windows). Files
    with no chunk are listed in `UnmatchedChangedFiles` (deleted files, non-C# files, files outside the corpus); files
    removed by `Exclude` are listed in a note.
  - **Submodules** appear as one gitlink path, which is unmatched; files inside them are not listed.

## Worked example: dotLLM itself

`run.ps1` runs `ChunkKvLab select` six times, each request without and then with a budget of 20,000 tokens. The setup:
- The solution is the dotLLM worktree `chunk-cache` at `1f87c375`, dirty=0, scanned with **Configuration=Release**, which
  built and loaded fine. Git is 2.53.
- Scan: 28 projects, 0 skipped, 2,604 files, of which 85 are generated; 2,519 authored files after `RelativizeScan` (root
  unchanged, 0 excluded).
- Chunking: symbol-512, giving 39,651 chunks and 8,003,073 tokens.
- Graph: per-project compilations, 374,804 edges.
- Only the tokenizer of Qwen3-4B-Instruct-2507 Q4_K_M (HF snapshot `ae44f08e`) is used; no weights are run.
- Time: scan 15–28 s (the first, cold run is the slowest), chunking 24–27 s, graph 28–35 s; 70–92 s wall per run. Each
  selection takes 0.17–0.51 s.
- Logs: `symbol-2hops-20k.log`, `symbol-2hops-20k-no-tests.log`, `symbol-2hops-20k-cap25.log`, `paths-since-20k.log`,
  `since-dev-two-dot.log`, `since-dev-merge-base.log`.

### "The neighbourhood of `ChunkIndex.Update` within 2 hops, under 20K tokens"

`--symbol ChunkIndex.Update --hops 2 --budget 20000` finds one definition, `DotLLM.ChunkReuse.Store.ChunkIndex.Update`
(method) at `src/DotLLM.ChunkReuse/Store/ChunkIndex.cs:365`.

| reason | hop | candidates (chunks / tokens) | selected under 20K (chunks / tokens) |
|---|---:|---:|---:|
| Definition | 0 | 1 / 486 | 1 / 486 |
| DefinitionBody | 0 | 2 / 687 | 2 / 687 |
| Callee | 1 | 20 / 2,776 | 20 / 2,776 |
| Caller | 1 | 20 / 7,915 | 20 / 7,915 |
| Callee | 2 | 34 / 5,319 | 7 / 1,042 |
| Caller | 2 | 301 / 73,297 | 21 / 6,950 |
| **total** | | **378 / 90,480 in 45 files** | **71 / 19,856 in 13 files** |

- **Hops 0 and 1 fit easily** (44 chunks, 11.9 K tokens).
- **Hop 2 is much larger:** 335 chunks and 78.6 K tokens, 7.6 times hop 0+1 in chunks and 6.6 times in tokens.
- **What hop 2 is made of.** It holds two kinds of chunk: those that reference `Update`'s hop-1 callers (mostly tests and
  the E7 lab command), and other users of its hop-1 callees, the hub records `ChunkRef`, `Chunk` and `ChunkKey`. The
  no-tests run below reaches 118 hop-2 callers only through callees, because excluding tests leaves no hop-1 callers. The
  logs do not split the full run's 301 hop-2 callers between the two routes.
- **The budget keeps the hop-2 chunks with the most edges to or from hop 1.** The first trimmed chunk is
  `ChunkIndex.cs:460-477` (312 tokens, 8+3 edges), with 144 tokens of budget left.

### Without tests and benchmarks

`--exclude tests/**,benchmarks/**`:

| reason | hop | candidates (chunks / tokens) | selected under 20K (chunks / tokens) |
|---|---:|---:|---:|
| Definition + body | 0 | 3 / 1,173 | 3 / 1,173 |
| Callee | 1 | 20 / 2,776 | 20 / 2,776 |
| Caller | 2 | 118 / 27,206 | 62 / 15,971 |
| Callee | 2 | 1 / 31 | 0 / 0 |
| **total** | | **142 / 31,186 in 19 files** | **85 / 19,920 in 16 files** |

**Every hop-1 caller of `ChunkIndex.Update` is in a test or in the E7 lab command, so excluding them removes all hop-1
callers.** The hop-2 callers that remain are users of `Update`'s callees. `Exclude` also cuts the walk: it does not walk
through the excluded tests to reach the callers of test helpers.

### With a per-hop cap

`--max-per-hop 25`:

| reason | hop | chunks / tokens |
|---|---:|---:|
| Definition + body | 0 | 3 / 1,173 |
| Callee | 1 | 11 / 1,481 |
| Caller | 1 | 14 / 5,772 |
| Callee | 2 | 6 / 847 |
| Caller | 2 | 19 / 6,386 |
| **total** | | **53 / 15,659 in 12 files** |

- The notes report "hop 1 capped: kept 25 of 40" and "hop 2 capped: kept 25 of 330".
- The capped neighbourhood fits the 20 K budget whole, so nothing is trimmed.
- The cap changes *which* hop-1 chunks are kept: 15 of the 40 are dropped, by weight. Without a cap all 40 survive, and hop 2
  is trimmed by the budget instead. The cap is off by default; a caller that wants the strongest links rather than complete
  hops can set it.

### Paths plus changed files

`--paths src/DotLLM.ChunkReuse/Tooling/,src/DotLLM.ChunkReuse/Store/ChunkRef.cs --since 69eb5772 --budget 20000`. The ref
is pinned to the merge of the scanner fix round, so the example does not drift as `HEAD` moves.

| reason | candidates (chunks / tokens) | selected under 20K (chunks / tokens) |
|---|---:|---:|
| Path | 104 / 15,619 | 104 / 15,619 |
| Changed | 83 / 18,409 | 10 / 3,971 |
| **total** | **187 / 34,028 in 10 files** | **114 / 19,590 in 7 files** |

All five `Tooling/` files are also in the range, because the fix round changed them; they count once, as Path. Every
requested path chunk is kept. The first trimmed chunk is a changed lab file (510 tokens).

### Two-dot against merge base

`--since dev`, with and without `--since-merge-base 1`. Here `dev` (`16b25d65`) is 14 commits past the merge base
`4a781829`.

| mode | candidates (chunks / tokens / corpus files) | changed files with no chunk |
|---|---:|---:|
| two-dot (working tree vs `dev`) | 1,864 / 353,592 / 94 | 48 |
| merge base (`dev...HEAD` + working tree) | 1,543 / 304,158 / 89 | 30 |

- **Two-dot sweeps in what only `dev` changed:** 321 chunks / 49.4 K tokens in 5 more corpus files, plus 18 more non-corpus
  files such as `CLAUDE.md`, `README.md` and `docs/*.md`.
- **Under 20 K both modes select the same 73 chunks.** All candidates have one priority, so the budget takes them in path
  order, and the first paths alphabetically (`benchmarks/ChunkKvLab/...`) are this branch's changes in both modes.
- **Changed files carry no relevance ranking.** Within the changed set the budget takes files in path order. Combining
  `ChangedSince` with `Symbol` or `Paths` gives the budget something to rank by.

## Tests and mutation evidence

- **Tests:** 101 test cases in `ContextSelectorTests`, `GitCliInfoTests` and `GitCliInfoEnvironmentTests`.
  - **Git argument injection**, against a fake and against real temporary repositories.
  - **Paths outside the root.**
  - **Symbol lookup:** not found with suggestions, positional record properties, keyword names rejected.
  - **Globs:** Windows separators, `./` in paths, literal `[ab]` and `{a,b}`, and two patterns matching one file.
  - **Empty selection, and a budget smaller than the first chunk.**
  - **Determinism:** reversed inputs, and ordinal order under the sv-SE, tr-TR and en-US cultures.
  - **Exclude** on all three criteria, including the note for excluded changed files.
  - **Merge base:** a real repository with a diverged branch, plus unrelated histories.
  - **Links:** a real junction (a symlink off Windows; the test is skipped if one cannot be created) for both
    `GitCliInfo` and the selector's resolved-root fallback.
  - **Inherited environment:** `GIT_DIR`, `GIT_WORK_TREE` and `GIT_INDEX_FILE` set to another repository. This test runs
    in a non-parallel collection because it changes the process environment.
  - **Git version:** parsing, and `--end-of-options` used only from 2.30.
  - **Git missing and timeout.**
  - **Per-hop cap:** it keeps the heaviest neighbour, and dropped neighbours never return.
- **ChunkReuse suite:** 474 pass, 1 skipped.
- **Mutation testing:** done live in the worktree, which I was alone in. Each file was restored byte for byte, checked by
  SHA-256 and `git status`, and the pristine tests passed after each round. **All 52 distinct compiled mutants were
  killed.** The logs are `.superpowers/sdd/2026-11-01-phase-s/task-6-mutants.log`.
  - Task rounds 1–3: 30 mutants. M14 (weight tie-break) and M16 (the edge-kind filter) survived round 1 and were killed
    after the tests were strengthened.
  - Review fix round 4: 22 mutants covering:
    - the link spelling, the resolved-root fallback and link resolution;
    - the `--end-of-options` version gate;
    - environment sanitising;
    - the merge base and the "no merge base" error;
    - Exclude in the path and changed-file loops, and the excluded-changed note;
    - the cap: ignored, lightest kept, dropped neighbours returning;
    - `./` normalisation in paths;
    - positional record properties and the keyword check;
    - culture-dependent order in the rank and in document order;
    - unmatched-pattern accounting.

    F13 and F14 (cap details) survived, a hub fixture was added, and both were killed in round 5.

## Caveats

- **Symbol lookup is syntax only** (see above for what is not supported).
- **`ChangedSince` works at file granularity**, as `git diff --name-only` does. Selecting only the changed chunks would need
  the diff hunks or a comparison of the old and new chunking (the `ChunkIndex` diff).
- **The budget counts chunk tokens only.** Separators or a prompt template are the caller's job.
- **Hop expansion follows the reference graph**, so a heavily used type pulls in many users at hop 2; `MaxNeighboursPerHop`
  bounds this. Per-project compilations bind 99.97 % of calls on dotLLM (`experiments/solution-scan/README.md`).
- **Platforms:** verified on Windows only, with git 2.53. The Linux paths (symlinks instead of junctions, ordinal path
  comparison) are covered by code but have not been run.
- **Only symbol-512 was run on dotLLM.**
