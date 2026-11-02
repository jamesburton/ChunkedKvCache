# Selection tools: `ContextSelector` (Phase S Task 6)

**Question:** given a scanned solution, which chunks go into a context? The selection can be made by path globs, by the
reference-graph neighbourhood of a symbol, or by the files changed since a git revision, and it is trimmed to a token
budget. The order is deterministic and each chunk records why it was picked.

**Answer:** `ContextSelector` does this in about 0.3 s on dotLLM (7.99 M tokens, 39,612 symbol chunks, 374 K edges) once the
graph is built. Scanning, chunking and building the graph take about 70 s and are a one-off cost, which `chunkcache` (Task 7)
will persist.
- The 2-hop neighbourhood of `ChunkIndex.Update` is **373 chunks / 88.6 K tokens in 45 files**.
- Under 20 K tokens the selection keeps **71 chunks / 19.9 K tokens in 13 files**: the definition, all of hop 1, and the
  best-connected part of hop 2.

The code is in dotLLM, worktree `chunk-cache`, branch `feature/chunk-cache`, at `fe6b7fea`. It is not pushed. The source
files are under `src/DotLLM.ChunkReuse/Tooling/`, the tests are `tests/DotLLM.Tests.Unit/ChunkReuse/ContextSelectorTests.cs`,
and the lab command is `benchmarks/ChunkKvLab/SelectCommand.cs`.

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
  - `TokenBudget`.
  - `EdgeKinds`: default Call, Use and Definition. Imports are left out because a namespace links everything that uses it.
  - `ChunkKind`: stamped on each `ChunkRef`.
- **`SelectionResult`** is an `IReadOnlyList<SelectedChunk>` in rank order. It also carries:
  - `Trimmed`;
  - `SelectedTokens` and `CandidateTokens`;
  - `SymbolDefinitions`;
  - `UnmatchedPatterns` and `UnmatchedChangedFiles`;
  - `Notes`;
  - `InDocumentOrder()`, the order for assembling a context.
- **`SelectedChunk`** is `ChunkRef` + `Reason` + `Priority` + `Detail` (for example "definition of A.B.Run", or "references
  hop-1 chunks (hop 2, 8 edges)"). It also has:
  - `Reasons`: every criterion the chunk matched, as flags;
  - `Hop`;
  - `Weight`: the number of edges to the previous hop.

## Semantics

- **The criteria are a union.** A chunk matched in several ways appears once. It keeps the highest-priority reason and all
  the flags.
- **Priority** (higher is kept longer):

  | reason | priority |
  |---|---:|
  | definition: the chunk that holds the declaration's name | 1000 |
  | definition body: the rest of the declaration (a long method, the members of a matched type) | 900 |
  | path glob | 800 |
  | changed since the revision | 700 |
  | neighbour at hop h | 600 − h |

  Ties are broken by `Weight` (descending), then by path (ordinal), then by offset.
- **Path above changed** was decided after running the worked example. The first version ranked changed (800) above path
  (700). The paths + `--since HEAD~3` request then trimmed **every** requested `Tooling/` chunk in favour of
  `ChunkKvLab/Program.cs`, which a merge had swept into the git range. A glob names the files the caller wants, so it is now
  ranked first. Mutant M29 pins this.
- **Trimming is strict.** The selection is the longest prefix of the ranking that fits the budget, so the lowest ranked go
  first. Once a candidate does not fit, nothing ranked below it is taken, even if it is smaller; a lower priority never
  displaces a higher one.
  - A budget smaller than the first candidate gives an empty selection, with everything in `Trimmed`.
  - In the worked example, the first trimmed chunk was 312 tokens with 144 tokens of budget left.
  - Greedy gap-filling would be a separate option if Task 7 wants it.
- **Symbol lookup** is syntax-based (`SymbolLocator`). It accepts a simple name or a dotted suffix of the qualified name.
  Generic arguments, a parameter list and `global::` are ignored, and matching is case-sensitive.
  - Every matching declaration counts: overloads, partial parts, and the same name in different types.
  - With no match, `SymbolNotFoundException` says which name was looked for and suggests close names: the same last name in
    another case or another container.
  - A declaration that the graph has no chunk of is the same exception, naming the file.
  - A malformed name is an `ArgumentException`.
- **The neighbourhood walk** is breadth-first over the selected edge kinds, in both directions. A Caller has an edge into
  the previous hop; a Callee is the target of an edge from it. Edges inside one chunk are ignored. Excluded files are
  neither selected nor walked through.
- **Globs:**
  - `*` and `?` match within one path segment; `**` as a whole segment matches any number of segments.
  - A bare name such as `*.cs` matches at any depth.
  - A trailing `/` means the whole directory.
  - `\` is accepted as a separator, and `.` and empty segments are dropped.
  - Matching is case-insensitive on Windows (as `RoslynGraphBuilder.PathComparer`).
  - The regex is non-backtracking.
  - Rooted patterns (`/x`, `C:\x`, `c:x`, UNC) and `..` segments are rejected, and a path outside the root (`../x`, or a
    path on another volume) never matches a glob. Such files can still be reached by the symbol walk or by `ChangedSince`
    if they are in the corpus.
- **Git (`GitCliInfo`):**
  - Arguments are passed through `ProcessStartInfo.ArgumentList`, never through a shell.
  - `ValidateRef` rejects, before git runs: an empty ref, leading or trailing white space, a leading `-` (which git would
    read as an option such as `--output=FILE`), and control characters.
  - The ref is then resolved with `rev-parse --verify --quiet --end-of-options <ref>^{commit}`, and only the resulting SHA
    reaches `diff --name-only -z --no-renames --no-ext-diff --no-textconv <sha> --`.
  - Untracked, non-ignored files come from `ls-files --others --exclude-standard -z`.
  - Paths are made absolute against the repository's top level and mapped to corpus paths against `rootDirectory`
    (case-insensitively on Windows). Files with no chunk are listed in `UnmatchedChangedFiles`.
  - Git runs with `GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0` and `core.fsmonitor=false`, and is killed by its process
    handle on timeout.

## Worked example: dotLLM itself

`run.ps1` runs `ChunkKvLab select` three times, each request without and then with the budget. The setup:
- The solution is the dotLLM worktree `chunk-cache` at `fe6b7fea`, dirty=0, scanned with **Configuration=Release**, which
  built and loaded fine.
- Scan: 28 projects, 0 skipped, 2,603 files, of which 85 are generated; 2,518 authored files after `RelativizeScan` (root
  unchanged, 0 excluded).
- Chunking: symbol-512, giving 39,612 chunks and 7,995,530 tokens.
- Graph: per-project compilations, 374,392 edges.
- Only the tokenizer of Qwen3-4B-Instruct-2507 Q4_K_M (HF snapshot `ae44f08e`) is used; no weights are run.
- Time: scan 16–17 s, chunking 24–25 s, graph 28–31 s; each selection takes 0.24–0.33 s. Logs:
  `symbol-2hops-20k.log`, `symbol-2hops-20k-no-tests.log`, `paths-since-20k.log`.

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
| Caller | 2 | 296 / 71,368 | 21 / 6,950 |
| **total** | | **373 / 88,551 in 45 files** | **71 / 19,856 in 13 files** |

- **Hops 0 and 1 fit easily** (44 chunks, 11.9 K tokens).
- **Hop 2 is 7.5 times larger**: 330 chunks and 76.7 K tokens. Most of it is callers of `Update`'s callers, chiefly tests
  and the E7 lab command.
- **The budget keeps the hop-2 chunks with the most edges into hop 1.** The first hop-1 entries are `ChunkRef`
  (16 edges), the `Chunk` record (13) and an internal helper of `ChunkIndex` (13).
- **The first trimmed chunk** is `ChunkIndex.cs:460-477` (312 tokens, 8+3 edges).

### Without tests and benchmarks

`--exclude tests/**,benchmarks/**`:

| reason | hop | candidates (chunks / tokens) | selected under 20K (chunks / tokens) |
|---|---:|---:|---:|
| Definition + body | 0 | 3 / 1,173 | 3 / 1,173 |
| Callee | 1 | 20 / 2,776 | 20 / 2,776 |
| Caller | 2 | 116 / 26,511 | 61 / 15,617 |
| Callee | 2 | 1 / 31 | 0 / 0 |
| **total** | | **140 / 30,491 in 19 files** | **84 / 19,566 in 16 files** |

**Every hop-1 caller of `ChunkIndex.Update` is in a test or in the E7 lab command, so excluding them removes all hop-1
callers.** The hop-2 callers that remain are reached through `Update`'s callees: other users of `ChunkRef`, `Chunk` and
`ChunkKey`. This shows that `Exclude` also cuts the walk; the alternative, walking through excluded files without
selecting them, would have reached the callers of the test helpers.

### Paths plus changed files

`--paths src/DotLLM.ChunkReuse/Tooling/,src/DotLLM.ChunkReuse/Store/ChunkRef.cs --since HEAD~3 --budget 20000`. Here
`HEAD~3` is the merge of the scanner fix round.

| reason | candidates (chunks / tokens) | selected under 20K (chunks / tokens) |
|---|---:|---:|
| Path | 91 / 12,878 | 91 / 12,878 |
| Changed | 57 / 13,607 | 26 / 7,108 |
| **total** | **148 / 26,485 in 9 files** | **117 / 19,986 in 9 files** |

The `Tooling/` chunks are both path and changed; they count once, as Path. The first trimmed chunk is a changed test chunk
(130 tokens).

## Tests and mutation evidence

- **Tests:** 73 test cases in `ContextSelectorTests` and `GitCliInfoTests`.
  - The plan's five: `Select_Glob_ReturnsMatchingFiles`, `Select_SymbolNeighbourhood_IncludesDefinitionAndCallersWithinHops`,
    `Select_ChangedSince_UsesGitDiff` (fake `IGitInfo`), `Select_OverBudget_TrimsLowestPriorityFirst` and
    `Select_Deterministic` (which also checks independence from file and chunk order).
  - **Git argument injection:** `--output=…`, `-p`, `--exec=…`, `-`, a NUL or newline inside the ref, and a leading space
    are all rejected before git runs, and no file is written. Real temporary repositories cover these, plus refs holding
    `;`, `&`, `$()`, quotes or a space followed by an option: git reports each as "not a commit" and writes no file.
  - **Real git:** modified, untracked and ignored files; a file name with spaces and `ü`; tags; `HEAD~1` with a delete; a
    subdirectory as the working directory; not a repository; a missing directory.
  - **Paths outside the root:** globs never match them, and rooted or `..` globs are rejected. `ChangedSince` maps
    `../shared/Info.cs` when the corpus has it and lists the other changed files as unmatched. A relative path from
    `IGitInfo` and a missing or relative root are rejected.
  - **Symbol not found:** the error names the symbol; suggestions are given for a wrong case or a wrong container; a file
    the graph lacks gives the same error naming the file; malformed names are argument errors.
  - **Globs with Windows separators:** `src\App\*.cs`, `.\src\App\`, `./src//App/./*.cs`, case on Windows, plus a matcher
    theory of 19 cases and 11 rejection cases.
  - **Empty selection:** an empty result with the unmatched patterns, and an empty git diff.
  - **A budget smaller than the first chunk:** budgets of 0, 1 and first−1 select nothing, with all candidates trimmed;
    strictness is checked as well.
  - **Determinism:** with the files and the graph's chunks reversed, the full signature (ids, reasons, priorities, hops,
    weights, details, trimmed order) is identical.
- **ChunkReuse suite:** 446 tests pass and 1 is skipped, after merging the scanner fix round `229fc630`.
- **Mutation testing:** done live in the worktree, which I was alone in. Each file was restored byte for byte, checked by
  SHA-256 and `git status`, and the pristine tests passed afterwards. **All 30 compiled mutants were killed.**
  - Round 1 (28 mutants): 21 killed and 2 survived:
    - M14, the weight tie-break: no fixture had neighbours of equal priority with different weights;
    - M16, `EdgeKinds` filtering: `EdgeKinds = []` returned early, so filtering was never exercised.

    The tests were strengthened: T now calls `Add` twice and must rank first in hop 2, and `EdgeKinds = [Use]` and `[Call]`
    cases were added. Both mutants were then killed in round 2. Five mutants were written as `if (false)` or with dead
    code and did not compile, because the repository treats warnings as errors.
  - Round 2 (8 mutants): the five non-compiling ones rewritten as runtime-false conditions, M14, M16, and the
    reverse-direction kinds mutant (M16b). All were killed.
  - Round 3: M29 (changed above path again) was killed.
  - The logs are `.superpowers/sdd/2026-11-01-phase-s/task-6-mutants.log`.

## Caveats

- **Symbol lookup is syntax only**, parsed without preprocessor symbols. A declaration inside an inactive `#if` region is
  not found, and overloads cannot be told apart by parameter types (`Select(int)` and `Select(string)` both match
  `Select(…)`).
- **`ChangedSince` works at file granularity**, as `git diff --name-only` does. Selecting only the changed chunks would need
  the diff hunks or a comparison of the old and new chunking (the `ChunkIndex` diff).
- **The budget counts chunk tokens only.** Separators or a prompt template are the caller's job.
- **Hop expansion follows the reference graph**, so its quality depends on the graph: per-project compilations bind 99.97 %
  of calls on dotLLM (see `experiments/solution-scan/README.md`). A heavily used type pulls in many users at hop 2.
- **Only symbol-512 was run on dotLLM.** Fixed chunks work the same way, but a declaration then spans arbitrary chunks.
