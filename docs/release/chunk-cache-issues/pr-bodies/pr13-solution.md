# PR 13 body draft: ChunkReuse.Solution: MSBuildWorkspace solution scanner

> DRAFT, not pushed, not opened. Branch `pr/chunkreuse-solution` (local, worktree `C:\Development\dotLLM\.claude\worktrees\pr13`), head `9c49e915`, off dev `f54e36c5` (= #1703 merged),
> with `origin/dev` `b0ed174f` (#1705, device selection in CLI/Server/Vulkan, no ChunkReuse file) merged in AFTER the test runs below (which were on `a3cccac8`; the merge touched no ChunkReuse file). Needs James's explicit go; route through dotllm-00. Cut report:
> `.superpowers/sdd/2026-11-01-phase-s/pr13-cut-report.md`.

## Title

ChunkReuse.Solution: MSBuildWorkspace solution scanner, with limits on what a scanned project can make it read, parse or wait for

## Body

Refs #1542. Follows #1646 (`.CSharp` chunker + corpus) and #1665 (graph + selection tools).

### Summary

New project `src/DotLLM.ChunkReuse.Solution` (`IsPackable=false`, like the other ChunkReuse projects). `SolutionScanner.LoadAsync(path)` opens a `.sln`, `.slnx` or project
with Roslyn's `MSBuildWorkspace` (design-time builds run in Roslyn's out-of-process BuildHost) and returns:

- every C# document of the scanned projects as a `SourceFile` (paths relative to the solution directory, CRLF to LF, generated files flagged, on-disk casing on Windows);
- one `ProjectCompilation` per scanned project (its own defines, references and project references), which feeds `RoslynGraphBuilder` from #1665 so call and use edges resolve across projects;
- the projects it did not scan and why (load failed, not C#, further target frameworks of a multi-targeted project), attributed from the loader's diagnostics by quoted project path.

Shared files: three package versions in `Directory.Packages.props` (`Microsoft.CodeAnalysis.CSharp.Workspaces` and `.Workspaces.MSBuild` 5.9.0, `Microsoft.VisualStudio.SolutionPersistence` 1.0.52),
the `dotLLM.slnx` entry, the unit-test project reference, and the `MiniSolution` fixture items (data, `Compile Remove`d from the test project; the fixture ships its own
`Directory.Build.props/targets` and `Directory.Packages.props` so the repo's do not apply). One new `InternalsVisibleTo` (`DotLLM.ChunkReuse.CSharp` to `DotLLM.ChunkReuse.Solution`) so the scanner can use the corpus limits in `RoslynParsing`.
Nothing in the engine or server references the new project. The CLI that calls it is PR 15.

### Threat / safety note

**Loading a solution executes it.** A design-time build evaluates and runs the projects' MSBuild: imported `Directory.Build.props/targets`, custom targets and tasks (`Exec`, inline tasks),
SDK resolvers (a `global.json` `msbuild-sdks` entry fetches and runs an SDK package). That runs as the current user in the build host, and no setting of `MSBuildWorkspace` prevents it.
Worse, `Analyzer` references (analyzers, source generators) are loaded INTO THE CALLING PROCESS when a compilation is made. Both were observed with a scratch solution (an `Exec` that wrote a marker file; an
analyzer assembly whose module initializer and generator ran in the scanner's own process). So the scanner is for solutions you would build; the remark on `SolutionScanner` now says so.
Opening this to untrusted input would need the whole load moved into a sandboxed process (or analyzers stripped, which changes what compiles): not attempted here, listed under "Not covered".

What the scanner does bound is what a project's *content* can make it do after that, found by driving the real workspace with hostile projects. Each fix has a test that failed first:

- **Stack overflow from a deeply nested file (process death).** The workspace parses documents on a thread-pool thread; 100,000 nested parentheses in a scanned `.cs` file killed the host ("Stack overflow", reproduced in the test host).
  A file past the corpus limits (`RoslynParsing.MaxNestingDepth` brackets, `MaxFileChars` characters) is now blanked in the workspace before anything parses it: its text stays in `Files` (a corpus chunks it by lines), its tree is empty,
  and a warning is added to the owning project's diagnostics. Detail: this uses a text *loader* (`WithDocumentTextLoader`); `WithDocumentText` parses the document's original text first to re-parse incrementally, which is the very parse being avoided.
- **A `Compile` item that is not a `.cs` file was read and returned as source.** A project listing a key or config file (inside or outside the root) got its bytes into `Files`, so into chunks. Non-`.cs` items are now removed from the
  workspace before they are read, with a warning on the project. Files outside the root that ARE `.cs` (linked shared sources, `../Shared`) are still returned, as designed; paths say so (`../` or absolute).
- **Cancellation and time were not honoured.** The workspace ignores its token while a design-time build step runs (a target that sleeps 40 s made a call cancelled at 2 s return after 42 s, and after the step finished it
  threw). `LoadAsync` now waits on the workspace calls with the token (`Task.WaitAsync`), so it returns at the token, and disposing the workspace on the way out takes its build host down. New `SolutionScanOptions.Timeout`
  (default `RoslynParsing.DefaultCorpusBudget`, 10 min; `Timeout.InfiniteTimeSpan` for none) ends the call with `TimeoutException`; the same holds while a source generator runs inside the compilation. A step that does not stop
  keeps running (its child process may outlive the call by its own length) until the build host is gone.

### Verification

- Windows `FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse`: 648 passed, 6 skipped, 0 failed (654 tests; the scanner accounts for 49 of them: 30 from the prep branch, 19 new, theory rows counted).
- Linux Docker (`linux-ci.sh`, non-root, `--cpus 4`, same filter): 654 tests, 652 passed, 2 skipped, 0 failed. The MSBuild workspace loads, restores and design-time builds the fixtures under Linux, and the whole scanner suite, hostile cases included, passes there.
- Failed first: against the unhardened scanner the deep-file test killed the test host (stack overflow), the oversized-file and non-`.cs` tests failed on their asserts, the cancel and timeout tests failed after the 40 s step ended
  (41.8 s for a 2 s token; no `TimeoutException`).
- Mutants (`pr13-mutants.py`, 43 on fresh `git archive` copies, copies checked pristine afterwards): 41 killed, 2 survive with reasons. The first run left 9 survivors; the tests added for 7 of them
  (generator-time cancellation, nested-project file owner, a built referenced project, the loader's message for an unknown project extension, target-framework tiebreaks) killed them on a re-run (one more mutant did not compile the first time and was re-run too).
  - H14 (the `ContinueWith` that observes an abandoned workspace call's failure): no scenario was found in which that call faults (cancel while a step sleeps, ends normally or cancelled), so no test can fail it. It is defensive; NOT claimed as tested.
  - C17 (relative quoted text in a loader message resolves against the process directory instead of being ignored): matters only when the cwd is the project's own directory and a message quotes the bare file name; a test needs `Directory.SetCurrentDirectory`, which is process-wide and races the parallel suite. Not tested.

### Not covered / for the reviewer

- Untrusted solutions (above): code execution through MSBuild and analyzers is inherent.
- No cap on the NUMBER of documents or their total size (only per file), and none on how many projects a solution lists; a `Compile Include` glob over a huge tree is bounded only by the timeout.
- Symlinks and junctions: a `.cs` file reached through a link inside or outside the root is read as is (MSBuild follows links); there is no root containment, by the same design that allows `../Shared`.
- The BuildHost and any child process a build step started are not killed with their process tree on cancel.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
