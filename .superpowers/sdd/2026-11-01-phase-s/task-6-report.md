# Task 6 report: Selection tools (`ContextSelector`)

**Status: DONE_WITH_CONCERNS.** The concerns are small and listed at the end.

## Commits

dotLLM, worktree `C:\Development\dotLLM\.claude\worktrees\chunk-cache`, branch `feature/chunk-cache`, not pushed:

- `771b9cd4`: `ContextSelector`, `SelectionRequest` and `SelectionResult`, `PathGlob`, `SymbolLocator`, and `IGitInfo` /
  `GitCliInfo`, all in `src/DotLLM.ChunkReuse/Tooling/`, with `ContextSelectorTests`.
- `69eb5772`: merge of `feature/chunk-scan` `229fc630`, the final scanner fix round, as the controller asked. The merge was
  clean. Afterwards the tests and ChunkKvLab built with 0 errors, and the ChunkReuse suite passed 446 tests, with 1 skipped.
- `baab4be4`: tests strengthened after two mutants survived (the weight tie-break and the edge-kind filter).
- `287c3b55`: lab command `ChunkKvLab select`.
- `fe6b7fea`: explicit paths (800) now outrank changed files (700). The lab prints unmatched changed files.

ChunkedkvCache (my paths only):

- `experiments/selection-tools/` (`README.md`, `run.ps1`, three logs)
- this report
- `task-6-mutants.log`

Before the work, the merged worktree built and its ChunkReuse tests passed (366, with 1 skipped). `dotLLM.slnx` already
listed `DotLLM.ChunkReuse.Solution`, so nothing had to be added.

## Final signature (per the controller ruling)

```csharp
SelectionResult ContextSelector.Select(SelectionRequest request, IReadOnlyList<SourceFile> files, ReferenceGraph graph,
                                       IGitInfo? git = null, string? rootDirectory = null)
// SelectionResult : IReadOnlyList<SelectedChunk>; SelectedChunk(ChunkRef Chunk, SelectionReason Reason, int Priority, string Detail)
//   { Reasons, Hop, Weight, Tokens }; plus Trimmed, SelectedTokens, CandidateTokens, SymbolDefinitions, UnmatchedPatterns,
//   UnmatchedChangedFiles, Notes, InDocumentOrder()
```

- **Location.** The selector is in `DotLLM.ChunkReuse` (namespace `DotLLM.ChunkReuse.Tooling`) with no reference to the
  Solution assembly. I had first started it in the Solution assembly and moved it when the ruling arrived.
- **No chunker or token-counter parameter.** The ruling's "or equivalent" covers this: the graph's chunks carry their token
  ids, so the counts come from there, and the graph is the chunk universe.
- **`rootDirectory`** replaces `ScanResult.RootDirectory` and is needed only for `ChangedSince`.
- **The caller passes the selectable files**, e.g. the authored files after `RelativizeScan`. The scan's `Generated` set
  therefore does not reach the selector, and I dropped an `IncludeGenerated` flag. A graph chunk whose file is not in
  `files` is an `ArgumentException`.
- **Contracts honoured:**
  - `ChunkRef` is compared by `Id` (location), never by record equality.
  - Paths are compared with `RoslynGraphBuilder.PathComparer` (case-insensitive on Windows), as `ChunkIndex` does.
  - The worked example goes through `ChunkIndex.RelativizeScan`.
  - The selector never evicts and never takes the store lock: it reads nothing from the store.

## Behaviour (details in the README)

- **Criteria form a union:**
  - `Paths`: globs, with a leading `!` to negate.
  - `Symbol` with `Hops`: the definition chunks, then a breadth-first walk both ways over Call, Use and Definition edges.
    `EdgeKinds` is configurable.
  - `ChangedSince`.
  - `Exclude` removes files from every criterion and also cuts the walk.
- **Rank and trim:** priority first (definition 1000, body 900, path 800, changed 700, neighbour 600 − hop), then weight
  (edges to the previous hop), then path, then offset. Trimming is strict: the selection is the longest prefix of the
  ranking that fits, so the lowest ranked go first and a lower priority never displaces a higher one.
- **Git:** arguments go through `ArgumentList` with no shell. Refs that start with `-`, are blank or padded, or hold control
  characters are rejected before git runs. The ref is resolved with
  `rev-parse --verify --quiet --end-of-options <ref>^{commit}`, and only the SHA reaches `diff --name-only -z … <sha> --`.
  Untracked files come from `ls-files --others --exclude-standard`, and paths are made absolute against the top level.

## Tests

`ContextSelectorTests` and `GitCliInfoTests` have 73 test cases.

- **Red run:** 73 of 73 failed against `NotImplementedException` stubs.
- **Green:** 73 of 73 pass. The full ChunkReuse filter passes 446, with 1 skipped (the pre-existing TODO test).
- **The plan's five tests** are all present.
- **The extra cases you asked for:**
  - Git argument injection, against a fake `IGitInfo` and against real temporary git repositories.
  - Paths outside the root.
  - Symbol not found, with a clear message and suggestions.
  - Glob edge cases with Windows separators.
  - Empty selection.
  - A budget smaller than the first chunk.
- **Also tested:** determinism under reordered inputs, a type symbol (definition and body chunks), a chunk matched by
  several criteria, request validation, document order, and path-above-changed under a budget.

## Mutation evidence

Mutants ran live in the worktree, where I was alone. Each was restored byte for byte, checked with SHA-256 and `git status`,
and the pristine tests passed after every round. **All 30 distinct compiled mutants were killed.** Log:
`task-6-mutants.log`.

- **Round 1:** 28 mutants. 21 were killed and 2 survived:
  - M14, the weight tie-break: no fixture had equal-priority neighbours with different weights.
  - M16, the edge-kind filter: `EdgeKinds = []` returned early, so filtering was never exercised.

  Five more did not compile: written as `if (false)` or with dead code, they break the repository's warnings-as-errors.
- **Round 2:** after the tests were strengthened (T calls `Add` twice and must rank first in hop 2; `EdgeKinds = [Use]` and
  `[Call]` cases added), 8 mutants: the five non-compiling ones rewritten as runtime-false conditions, M14, M16 and a
  reverse-direction kinds mutant (M16b). All 8 were killed.
- **Round 3:** M29 (changed ranked above path again) was killed.

## Worked example: dotLLM itself

- **Setup:**
  - Solution: the dotLLM worktree at `fe6b7fea`, dirty=0, scanned with **Configuration=Release**, which built and loaded
    without problems.
  - Scan: 28 projects, 0 skipped, 2,518 authored files.
  - Chunking: symbol-512, giving 39,612 chunks and 7.99 M tokens.
  - Graph: 374,392 edges.
  - Only the Qwen3-4B tokenizer is used; no weights are run. CPU only.
- **Time:** about 70 s for scan, chunking and graph; **0.24–0.33 s per selection**.
- **The neighbourhood of `ChunkIndex.Update` within 2 hops:**

  | budget | chunks | tokens | files |
  |---|---:|---:|---:|
  | none | 373 | 88,551 | 45 |
  | 20 K | 71 | 19,856 | 13 |

  - Under 20 K the selection keeps the definition and body, all of hop 1 (40 chunks, 10.7 K tokens), and the 28 hop-2 chunks
    with the most edges into hop 1.
- **Without tests and benchmarks** (`--exclude tests/**,benchmarks/**`):

  | budget | chunks | tokens | files |
  |---|---:|---:|---:|
  | none | 140 | 30.5 K | 19 |
  | 20 K | 84 | 19.6 K | 16 |

  Every hop-1 caller of `Update` is a test or the E7 lab command, so excluding them removes all hop-1 callers.
- **Paths plus `--since HEAD~3`:** 148 candidates (26.5 K tokens). Under 20 K, all 91 path chunks are kept and 26 of the 57
  changed chunks.

## Concerns

1. **Design change made after a measurement.** The first priority order put changed (800) above path (700). On the dotLLM
   paths + since example it trimmed every requested `Tooling/` chunk in favour of files a merge had swept into the git
   range. I swapped the two (path 800, changed 700), documented the reason and pinned it with a test (M29). Task 7 may want
   the order to be configurable.
2. **Strict trimming** means one large chunk ranked early can leave budget unused: in the main example, 144 tokens were left
   and the next chunk was 312. This is deliberate ("lowest priority first"); greedy gap-filling could be an option in
   Task 7.
3. **Symbol lookup is syntax only**, without preprocessor symbols. Declarations under inactive `#if` regions are not found,
   and parameter lists are ignored, so all overloads match. `ChangedSince` works per file, not per changed hunk.
4. **Git tests spawn real `git` in temporary directories.** They need git on PATH, and the not-a-repository test assumes
   `%TEMP%` is not inside a repository. They were verified on Windows only.
5. **The lab `select` command checks that `RelativizeScan` left the root unchanged.** The per-project graph is keyed by scan
   paths, and on dotLLM the root was unchanged. Task 7 must keep the scan paths and the graph paths in the same coordinates
   when the root widens.
6. **Line endings:** my new files are LF in the working tree; git converts them to CRLF on checkout, as the warnings show.
   The content is unchanged.

---

## Fix round (review `review-task6-report.md`)

**Status: DONE.** All six should-fixes and the nits are addressed.

The box rebooted mid-round. The uncommitted work survived intact; I rebuilt, retested and committed it.

### dotLLM commits (`feature/chunk-cache`, not pushed)

- `2948d9c4`: the fixes.
- `1f87c375`: a hub test for the per-hop cap, added after mutants F13 and F14 survived.

### Should-fixes

- **S1: links.**
  - `GitCliInfo` builds the top level from the working directory plus `rev-parse --show-cdup`, so changed paths keep the
    caller's spelling through a junction, symlink or `subst` drive. Before, `--show-toplevel` resolved the link.
  - `ContextSelector` also maps a resolved path against the link-resolved root (`ResolveLinks`), for other `IGitInfo`
    implementations.
  - Tests use real junctions (symlinks off Windows; skipped if a link cannot be created) for both mechanisms.
- **S2: git version.**
  - `--end-of-options` is passed only for git 2.30 or later. The version comes from `GitVersion` (`git version`, parsed by
    `ParseVersion`) and is applied by `RevParseArguments`.
  - Older or unrecognised git still works safely, because refs starting with `-` are rejected first.
  - README: git 2.30 or later is recommended.
- **S3: environment.** Every inherited `GIT_*` variable is removed (`SanitizeEnvironment`). A non-parallel test sets
  `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE` and `GIT_CEILING_DIRECTORIES` to another repository; there is also a unit
  test on a dictionary.
- **S4: Exclude.** Tested in the path loop and in the changed-file loop. Excluded changed files are listed in a note.
- **S5: merge base.**
  - New `SelectionRequest.ChangedSinceMergeBase` and `IGitInfo.ChangedFiles(ref, sinceMergeBase)`: `merge-base <sha> HEAD`,
    then a diff against the working tree, plus untracked files.
  - Unrelated histories give a "no merge base" `GitException`.
  - Lab option: `--since-merge-base 1`.
  - On dotLLM against `dev`, which is 14 commits ahead: two-dot gives 1,864 chunks / 353.6 K tokens in 94 files plus 48
    unmatched files; the merge base gives 1,543 / 304.2 K in 89 files plus 30 unmatched. Two-dot sweeps in 321 chunks and
    18 non-corpus files that only `dev` changed.
- **S6: README.**
  - The hop-2 composition is reworded: it is callers of hop-1 callers *and* users of hop-1 callees; the no-tests run reaches
    118 hop-2 callers only through callees; the logs do not split the full run.
  - "Edges to or from hop 1".
  - Timing: 0.17–0.51 s per selection, with the first request of each process including JIT.
  - Hop 2: 7.6 times hop 0+1 in chunks, 6.6 times in tokens.
  - The paths + since example is now pinned to `69eb5772`. All five Tooling files are in that range after the fix round,
    and the README says so.

### Nits

- **Lookup and globs:**
  - Glob literals (`[..]`, `{a,b}`) are documented and tested.
  - `./` and empty segments are dropped in paths as well as in patterns.
  - Positional record properties are found.
  - Indexers, operators, conversion operators and finalizers are documented as unsupported, and keyword names such as
    `this` are rejected with an explanation.
  - `\uXXXX` identifiers and submodules are documented.
- **New tests:**
  - two patterns matching one file;
  - git missing;
  - timeout;
  - ordinal order under sv-SE, tr-TR and en-US, with paths such as `B.cs` / `a.b.cs` / `a_b.cs` / `Ä.cs`.
- **Hub cap:** `MaxNeighboursPerHop`, off by default.
  - It keeps the heaviest neighbours (weight, path, offset), notes what it dropped, and dropped neighbours never return at a
    later hop.
  - dotLLM with `--max-per-hop 25`: 53 chunks / 15.7 K tokens, with "kept 25 of 40" at hop 1 and "kept 25 of 330" at hop 2.
- **Lab:** `List()` intent clarified, plus the `--since-merge-base` and `--max-per-hop` options.

### Tests and mutants

- **Red run:** 24 of 100 failed against stubs.
- **Green:** `ContextSelectorTests` and the GitCliInfo tests now have 101 test cases; the ChunkReuse suite passes 474, with
  1 skipped.
- **Mutants:**
  - Round 4: 22 mutants, 20 killed. F13 (dropped neighbours returning) and F14 (the cap keeping the lightest) survived and
    were killed in round 5 after the hub fixture was added.
  - **All 52 distinct compiled mutants of the task are killed.** Every restore was checked, and the pristine run passed
    after each round.

### Worked example rerun

- At `1f87c375`, dirty=0, Release, git 2.53: six requests.
- The corpus grew a little, because the new test file is part of the solution: 2,519 authored files, 39,651 chunks,
  8,003,073 tokens, 374,804 edges.
- The 2-hop neighbourhood of `ChunkIndex.Update`: 378 chunks / 90,480 tokens in 45 files, or 71 chunks / 19,856 tokens in
  13 files under 20 K. The budgeted selection is unchanged.

### Remaining concerns

- Linux is still unverified.
- Within the changed set, the budget takes files in path order, because changed files carry no relevance ranking. The
  README says so and suggests combining `ChangedSince` with `Symbol` or `Paths`.
