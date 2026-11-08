# PR 17 body draft: ChunkReuse hardening, part 2 (#1664 remainder)

> DRAFT, not pushed, not opened. Branch `pr/chunkreuse-hardening-2` (local, worktree `C:\Development\dotLLM\.claude\worktrees\pr17`), head `e2315337`, off dev `aebd4103`
> (= #1676 merged). Needs James's explicit go; route through dotllm-00.

## Title

ChunkReuse: corpus-wide Roslyn binding budget, owner-only shard and temp files, CanonicalRoot applies `..` after links

## Body

Refs #1664. Follows #1676. Takes the review items dotllm-00 prioritised.

### Summary

- **Corpus binding budget (`CallResolution.Sites`, `RoslynGraphBuilder`).** Binding ran on the large-stack thread with only the per-file token. A binder
  path that does not poll the token held the caller forever, and the per-file budgets did not add up to any total. Both now run under a corpus-wide
  budget (`RoslynParsing.DefaultCorpusBudget`, 10 min): the token is linked to each file's, and over the budget the call throws `TimeoutException` (a partial
  graph would silently change results) and abandons the thread after the grace, as `Parse` does. A per-file overrun still only drops that file.
  Also fixed: a zero per-file budget now cancels at once (`CancelAfter(Zero)` on a linked source fires on a timer).
- **Owner-only files and directories.** Shard subdirectories and the temp files that become chunk, index, ledger and registry files were created with the
  default umask, so a pre-existing group-readable root leaked their contents. New `StorePaths.CreateNewFile` creates them `0600` on POSIX; shard directories
  go through `CreateStoreDirectory` (`0700`). An existing root keeps its mode.
- **`CanonicalRoot`** applied `..` lexically (`Path.GetFullPath`) before resolving links; `link/../x` now means the parent of the link's target, as the OS does.

### Measured, and what it means for the review items

- **Roslyn does not poll the cancellation token inside exponential lambda overload resolution.** Nested `M(x => M(x => ...))` over two overloads: depth 18 binds in 12 s,
  each level doubles it. With a 300 ms per-file budget a depth-22 file still bound for about 2.5 minutes. So the per-file token cannot stop that shape; the corpus
  budget, which abandons the thread, is the real bound. The abandoned thread keeps running until its bind finishes (in the tests: depth 20, about a minute, in the background).
  The requested "cancel mid-bind, fails without `ct`" test therefore cannot be written for this shape; no shape that polls inside one `GetSymbolInfo` was found
  (3000-term chain, 400-deep nested calls, 20000 statements and 14 nested overloads all bind in under 4 s). Left open in #1664.
- **Item 8 (`CreateDirectory` 0700 also applies to new parents) does not occur on .NET:** `Directory.CreateDirectory(path, mode)` leaves missing parents at the default mode
  (the test passed against dev's unchanged code). `CreateStoreDirectory` now creates parents explicitly anyway, and the test stays as a guard.

### Verification

- Windows `DotLLM.Tests.Unit.ChunkReuse`: 599 pass / 6 skip / 0 fail (head before the last test-only commit; the last commit adds the index file to a Linux-only test).
- Linux Docker (non-root, `linux-ci.sh`), same filter: 605 tests, 603 pass / 2 skip / 0 fail.
- New tests failed first: against dev's source in Docker, 3 of the 5 `StoreModesTests` failed (shard/chunk modes, ledger/registry modes, CanonicalRoot through a link); the other two
  (dots without a link, parents keep the default mode) are controls that pass either way.
- Mutants J1-J13 on a fresh `git archive` copy (`pr17-mutants.py`, log `.superpowers/sdd/2026-11-01-phase-s/pr17-mutants.log`; copy checked pristine afterwards):
  killed J1, J2 (no outer timeout), J5 (zero budget, call resolution), J7-J8, J10-J13 (modes). Survived, all equivalent:
  - J3, J4 (per-file catch swallows the corpus cancellation): the next file's `ThrowIfCancellationRequested`, or `RunWithLargeStack`'s post-check, still throws `TimeoutException`.
  - J6 (zero budget in the graph builder falls back to a timer): the timer fires long before a file with more than a few nodes is bound; only a one-node file could differ.
  - J9 (`..` handled in the loop vs by the final `GetFullPath`): the path is already link-resolved when `..` is reached, so both give the same result. The link test passes against both; it fails against dev's
    old code, which is the bug.

### Still open in #1664

Directory `fsync` after rename on POSIX; abandoned-thread CPU after the grace; budgets that discard a completed parse (`clock.Elapsed > timeout`, non-deterministic at the boundary);
the git-readers test relies on finalizers and can pass vacuously; the mid-bind cancellation test (no shape found that polls inside one bind).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
