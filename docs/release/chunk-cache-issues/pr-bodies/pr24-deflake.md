# PR 24 body draft: make two flaky chunk-reuse timing tests deterministic (#1737)

> DRAFT, not pushed, not opened. Branch `pr/chunkreuse-deflake-1737` (local, worktree `C:\Development\dotLLM\.claude\worktrees\flake-1737`), cut from `origin/dev`; `origin/dev` merged in before finishing.
> Needs James's explicit go; route through dotllm-00. Mutant script: `.superpowers/sdd/2026-11-01-phase-s/pr24-mutants.py`.

## Title

tests: make the Roslyn budget and scanner timeout tests clock-free (#1737)

## Body

Fixes #1737 (item 1; the CI job timeout in item 2 is not touched). Tests only: no production file changes.

### What flaked and why

Both tests asserted a wall-clock bound on a call whose timer and wait run on thread-pool callbacks.

- `SolutionScannerHardeningTests.Scan_OptionTimeout_...(solution: False)`: a 40 s design-time build, `Timeout = 2 s`, assert `elapsed < 20 s`. CI run 42652507415 (attempt 2) failed with
  `timeout 2 s, returned after 00:00:23.3980270`. The 2 s timer, the `WaitAsync` that observes it and the workspace teardown all queue behind whatever the other test classes occupy the pool with, so on a loaded
  runner the call returned 21 s late. The bound only held because the CI runner is usually idle.
- `RoslynBudgetTests.RunWithLargeStack_CooperativeWorkOverTheTimeout_..._Promptly`: `CancelAfter(100 ms)` plus a thread that polls its token, assert `elapsed < 8 s` (dev run 42664093162 failed at 9 s).
  The cancel timer is also a pool callback; and the bound sat BELOW the 10 s `CancelGrace`, so a timer that fires late and a join that gives up at the grace were indistinguishable from "slow".
  Measured here on a 2-core, burner-loaded box: the old test took 2 to 5 s against its 8 s bound (0.2 s when idle).

The sibling tests with the same shape (`Scan_CancelledDuringTheDesignTimeBuild_ReturnsAtOnce`, `RunWithLargeStack_WorkThatIgnoresTheToken_...`) are fixed the same way. `Scan_CancelledWhileASourceGeneratorRuns_ReturnsAtOnce` (15 s bound) has the same pattern and is NOT changed here.

### The change

- New `HangGuard` (test helper): awaits a task and fails the test if it has not returned after 2 minutes. It is a LIVENESS backstop, not a latency bound: a correct call returns whatever the load, only a regression (timeout never fires, unbounded join, token not honoured) gets near it.
- The work is held on a gate only the test releases, so the only way the call can return is the behaviour under test:
  - Roslyn cooperative test: the work parks on `ct.WaitHandle` (no sleeps); grace is one hour. Asserts a `TimeoutException` whose message is the budget one ("exceeded"), the work saw the cancellation, and the thread had ended (joined, not abandoned).
  - Roslyn token-ignoring test: the work parks on an event the test releases afterwards. Asserts a `TimeoutException` whose message says the thread was abandoned, and that the work had NOT finished when the call returned.
  - Scanner tests: the design-time build runs a small command (PowerShell on Windows, `sh` elsewhere) that writes `started.flag`, waits while `hold.flag` exists, then writes `ended.flag`. The timeout test asserts `TimeoutException` and that `ended.flag` does not exist
    (the call returned while the build was still held). The cancel test waits for `started.flag`, then cancels the token (no 2 s timer), and asserts an `OperationCanceledException` and no `ended.flag`. The hold file is deleted in `finally`.
- Production behaviour is identical (no source change, no seam needed).

### What each test still proves (and what it does not)

- Cooperative: the budget cancels cooperative work through its token, the call returns without waiting for the grace, and reports the overrun as `TimeoutException` (not the work's `OperationCanceledException`). No longer proves a "prompt" latency; that was never a property worth a wall-clock bound.
- Token-ignoring: work that never stops is abandoned after the grace and the caller still gets a `TimeoutException`, without waiting for the work.
- Scanner timeout: `SolutionScanOptions.Timeout` ends a load whose design-time build is held, with a `TimeoutException`. It does NOT prove the 2 s timer fired after the build command had started (under load it can fire during workspace start-up); the gated cancel test pins the during-build case.
- Scanner cancel: a cancelled token ends a load while the build command is provably running.

### Before / after

Same harness for both: 4 rounds x 8 parallel `dotnet test --no-build --filter` runs, 64 CPU burners on a 32-thread box.

- Before (original tests; the 2 issue tests = 3 cases per run): 96 of 96 passed, 0 failed (4 x 8 runs, 3 cases each, about 10 min). The flake did not reproduce locally under this load (CI saw 1 in about 25 min of runs); see the 2-core starvation note above for how close the Roslyn test gets.
- After (the 5 rewritten tests = 6 cases per run): 192 of 192 passed, 0 failed (4 x 8 runs, 6 cases each: 32 per case).

### Mutants (fresh `git archive` copy, restored and byte-compared afterwards)

| # | Mutant | Verdict |
|---|---|---|
| K1 | `CancelAfter` removed (the timeout never fires) | killed: cooperative test (HangGuard) |
| K2 | `Join(timeout + grace)` -> unbounded join | killed: token-ignoring test (HangGuard) |
| K3 | late or cancelled work no longer an overrun | killed: cooperative test (OCE leaks) |
| K4 | scanner ignores `Options.Timeout` | killed: both `Scan_OptionTimeout` cases |
| K5 | scanner timeout surfaces as `OperationCanceledException` | killed: both `Scan_OptionTimeout` cases |
| K6 | `Bounded` waits for the workspace call, not the token | killed: 2 cancel + 2 timeout cases |

### Verification

- Windows: `dotnet test tests/DotLLM.Tests.Unit --filter "(FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse)&Category!=GPU"`: 741 passed, 7 skipped, 0 failed (748)
- Linux Docker (non-root, 4 GB VM, filter `FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse`): 738 passed, 2 skipped, 0 failed (740)
- Analyzers: 0 errors.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
