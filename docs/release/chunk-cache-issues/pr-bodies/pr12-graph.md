# PR 12 body draft: ChunkReuse.CSharp: reference graph, symbol locator, git info and context selection

> DRAFT, not pushed, not opened. Branch `pr/chunkreuse-graph` (local, worktree `C:\Development\dotLLM\.claude\worktrees\pr12`), head `ba1d18a3`
> (includes dev `5121d61f` = #1648 + #1652). Needs James's explicit go; route through dotllm-00. Cut report: `.superpowers/sdd/2026-11-01-phase-s/pr12-cut-report.md`.

## Title

ChunkReuse.CSharp: reference graph, symbol locator, git info and context selection

## Body

Refs #1542. Follows #1646 (`.CSharp` chunker + corpus) and #1648 (index).

### Summary

Selection tooling over the C# chunks, in `DotLLM.ChunkReuse.CSharp`:

- **`Graph/*`** (`RoslynGraphBuilder`, `ReferenceGraph`, edges): a Roslyn-built chunk-to-chunk reference graph (definition, call, use, import edges), mapped from
  source offsets to chunk-local tokens, with a count of chunks whose offset/token mapping did not line up.
- **`Tooling/SymbolLocator`**: finds declarations by qualified name (case-sensitive, suffix match) with suggestions on a miss.
- **`Tooling/GitInfo`** (`IGitInfo`): changed files since a ref or merge base, through the `git` CLI.
- **`Tooling/ContextSelector`** (+ `SelectionTypes`): picks chunks by path globs, changed-since and a symbol neighbourhood (hops, edge kinds, per-hop cap),
  ranks them by reason priority and trims to a token budget.

`GraphSelector` is not included (it depends on research-only base classes).

### Threat / safety note

- `GitInfo` runs `git` as a subprocess: option-like or malformed refs are rejected before git runs, `--end-of-options` is used where git supports it,
  inherited `GIT_*` variables are ignored, external diff and textconv are disabled, nothing is written.
- `ContextSelector` resolves corpus paths against one root (symlinks and junctions resolved), rejects relative paths from `IGitInfo`, and `PathGlob`
  never matches a path with a `..` segment.
- Roslyn on hostile input: the bracket-depth cap guards the PARSE only. Binding (graph build, locator, corpus compilation) recurses per
  syntax level and bracket-free nesting (generic angles, `.` chains, ternaries, unary operators, `else if` chains) passes the bracket
  cap. So: parsing and binding run on a 256 MiB-stack thread, a parsed tree deeper than `RoslynParsing.MaxSyntaxDepth` (2048, measured
  without recursion) is not bound (the graph builder and `SymbolLocator` skip the file with a trace warning; the corpus compilation
  leaves it out as an empty tree, so its symbols do not resolve), and `InsufficientExecutionStackException` from Roslyn is caught per
  file. Regression tests cover each shape, in all four entry points. Behaviour change vs #1646: a file deeper than the cap is no
  longer in `Corpus.Compilation` (it was only left out above the bracket cap before).
- `GitCliInfo`: git stdout/stderr are capped (64 Mi chars; over it git is killed and `GitException` thrown), and start failures
  (missing executable, vanished directory) surface as `GitException`.

### Verification

- Windows (ChunkReuse namespace): 558 passed, 1 skipped, 0 failed. Linux Docker (non-root, CI filter): 559 tests, 557 passed, 2 skipped, 0 failed.
- Mutation testing (61 purpose-written mutants plus 7 for the hostile-input guards, fresh archives, copies checked pristine afterwards):
  the guard mutants are killed (three of them by hanging or crashing the test host, which counts as a kill); 9 of the first 61 survive and
  are judged equivalent, each with its reason in the cut report. B2 and B4 are defensive guards that a review probe of ~95 name forms could
  not reach: they are kept with a comment and are NOT claimed as tested.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
