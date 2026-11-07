# PR 16 body draft: ChunkReuse store hardening and bounded Roslyn work (#1664)

> DRAFT, not pushed, not opened. Branch `pr/chunkreuse-store-hardening` (local, worktree `C:\Development\dotLLM\.claude\worktrees\pr16`), head `c5ab3d7c`
> (includes dev `495411f2`, i.e. #1665 and #1671). Needs James's explicit go; route through dotllm-00.

## Title

ChunkReuse: store hardening (private modes, access-denied, self-deadlock, real-path roots) and bounded Roslyn work

## Body

Closes #1664 (except the items listed under "Not in this PR"). Follows #1648 (index, locks, ledger) and #1665 (graph).

### Summary

**Store (round 1, `DotLLM.ChunkReuse/Store`)**

- New `StorePaths`: store roots are created `0700` and lock files `0600` on POSIX (existing directories keep their mode); roots are resolved to
  real paths through links and junctions. There is one `IsSharingViolation` (Windows 32/33, Linux 11 EAGAIN, macOS 35) instead of per-site copies.
- `OpenLockFile` no longer retries access-denied: `UnauthorizedAccessException` is thrown at once (it was reported as "busy" after the timeout).
- `LockingChunkStore.Put/Evict` throw `InvalidOperationException` when the flow already holds the store lock (it used to self-deadlock).
- The lock-order check and `EnsureHeldFor` compare real paths, not strings.
- `StoreOwnerLock.TryAcquire` keeps a 300 ms grace so a probe cannot make a server refuse. `IsHeldByAnother` is documented as advisory only:
  the CLI must hold `TryAcquire` for its whole run.
- Nits: `PathGlob` comment, the Save smoke test renamed to say what it checks.

**Roslyn (round 2, `DotLLM.ChunkReuse.CSharp`)**

- Files over 2 Mi chars are not given to Roslyn (they take the line-chunk fallback, are left out of the compilation and are not searched).
- Each file gets a 30 s parse/bind budget (cancellation token, then an elapsed-time check, then the thread is abandoned after a 10 s grace).
  A file over budget is treated like a too-deep one. Applies to the chunker, graph builder, call resolution and `SymbolLocator`.
- Both `git` reader tasks are now observed (no unobserved task exceptions).

### Behaviour changes (intended)

- `LockFile_AccessDenied_IsRetriedWithinTheTimeout_ThenBusy` was rewritten: the contract is reversed on purpose (access denied is an error, not busy).
- A file over 2 Mi chars or over the budget is no longer in `Corpus.Compilation`.

### Not in this PR (stays in #1664)

- `fsync` of the directory after a rename on POSIX. It needs libc interop; the effect is only that a crash can lose a re-encoding, never a chunk.
- Windows ACL hardening beyond documenting the default (inherited ACL of the parent).

### Verification

- Windows, `DotLLM.Tests.Unit.ChunkReuse`: 594 pass / 3 skip / 0 fail (head `c5ab3d7c`).
- Linux Docker (`linux-ci.sh`, non-root user, `mcr.microsoft.com/dotnet/sdk:10.0`): 597 tests, 595 pass / 2 skip / 0 fail (head `c5ab3d7c`).
- New tests were written first and failed: `StoreHardeningTests` (round 1), `RoslynBudgetTests` (round 2).
- Mutants on a fresh `git archive` copy: round 1 M1-M13 all killed (M7-M9 in Docker copies); round 2 H1-H14 all killed except H4, which is
  equivalent (a zero budget is also caught by the elapsed check). H5 and H11 needed new tests.
- Real-shape check: 30000 chained `await` parses in 0.1 s (Windows), so that shape does not reach the budget at parse time; the budget path is
  covered by the zero/short-budget tests, not by a naturally slow input. Binding-time hostile shapes were not found in this pass.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
