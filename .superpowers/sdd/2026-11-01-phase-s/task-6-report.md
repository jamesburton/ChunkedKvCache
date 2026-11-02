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
