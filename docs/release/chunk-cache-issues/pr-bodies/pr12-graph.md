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
- Roslyn on hostile input: every parse goes through the `RoslynParsing` depth guard. `SymbolLocator.Find` lacked it (a deeply nested file overflowed the stack
  of the test host); fixed test-first with `SymbolLocatorHostileInputTests`.

### Verification

- Windows (ChunkReuse namespace): 532 passed, 1 skipped, 0 failed. Linux Docker (non-root, CI filter): 533 tests, 531 passed, 2 skipped, 0 failed.
- Mutation testing (61 purpose-written mutants on a fresh archive of the head): 51 killed; 9 survivors judged equivalent, each with its reason in the cut report
  (two, B2 and B4, are defensive guards I could not reach with an observable edge).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
