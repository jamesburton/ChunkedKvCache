# Task 5 report: Solution scanner (Roslyn workspace)

**Status: DONE_WITH_CONCERNS**

The concerns are small and listed at the end.

## Commits

dotLLM, worktree `C:\Development\dotLLM\.claude\worktrees\chunk-scan`, branch `feature/chunk-scan` from `63cebfbd`, not pushed:

- `8b9d7b07` SolutionScanner (MSBuildWorkspace) and per-project compilations for RoslynGraphBuilder (+ fixture, tests, central package versions)
- `b824e577` SolutionScannerTests: rejection cases check the builder's own messages (mutants G2/G3 survived the bare Throws)
- `b2acb3b6` CallResolution (invocation binding share), ProjectCompilation.BclOnly, ChunkKvLab scan-info

ChunkedkvCache: `experiments/solution-scan/{README.md,run.ps1,dotllm-symbol.log,dotllm-fixed.log}` and this report. See the
commit below.

## What was built

- **`SolutionScanner.LoadAsync(path, ct) -> ScanResult(Files, Skipped)`**, in namespace `DotLLM.ChunkReuse.CodeCorpus`.
  - Accepts `.sln`, `.slnx` or a project file.
  - `Files`: every C# document of the scanned projects. Paths are relative to the solution directory with `/`, text is LF,
    each file appears once and belongs to the first project by path.
  - `Generated` / `IsGenerated` / `AuthoredFiles`: files under `obj`/`bin`, or flagged by `SymbolChunker.IsGenerated`.
  - `Projects` (`ScannedProject`): one compilation per project, as `ProjectCompilation`.
  - `Skipped` (`SkippedProject(ProjectPath, Reason, Message)`), with these reasons:
    - `load-failed`: a workspace Failure, or listed in the solution but not loaded.
    - `unsupported-language`.
    - `extra-target-framework`.
  - `Diagnostics`: loader messages that name no project.
  - A warning when a project has no core library (not restored).
- **`RoslynGraphBuilder.Build(IReadOnlyList<ProjectCompilation>, chunks)`.** Each file is bound in the compilation of the
  project that owns it. Locations map to corpus paths through the tree's file path, so references into other projects resolve.
  Ownership is validated: a file owned twice, a tree that is not in its compilation, or a chunk file with no owner all throw.
  The BCL-only overloads behave as before; all 273 ChunkReuse tests pass.
- **`CallResolution.Measure`** counts invocation sites, sites that bind, and sites that bind to a measured file.
  **`ProjectCompilation.BclOnly(files)`** builds the BCL-only set-up for comparison.
- **Lab command `ChunkKvLab scan-info --model --solution [--chunker] [--chunk]`.**
- **Packages**, added through central versions in `Directory.Packages.props`, same 5.9.0 as `Microsoft.CodeAnalysis.CSharp`:
  - `Microsoft.CodeAnalysis.CSharp.Workspaces`
  - `Microsoft.CodeAnalysis.Workspaces.MSBuild`
- **`Microsoft.Build.Locator` is not used.** The plan called for it. Workspaces.MSBuild 5.x runs design-time builds in an
  out-of-process BuildHost (`BuildHost-netcore`), which finds the SDK by itself. Registering MSBuild in-process would add a
  dependency that does nothing. The SDK and MSBuild on this box caused no problems.
- **Fixture `tests/DotLLM.Tests.Unit/ChunkReuse/Fixtures/MiniSolution`.**
  - It is `Compile Remove`d from the test project and copied to the output as `None` items. I checked that the test DLL has
    no fixture types.
  - Its own `Directory.Build.props`, `Directory.Build.targets` and `Directory.Packages.props` stop the repo's from applying.
  - It is not in `dotLLM.slnx`.
  - The tests copy it to a temp directory, make one file CRLF, and run `dotnet restore App/App.csproj` once per class (about
    3 s).

## Tests

`SolutionScannerTests` has 7 tests, all passing. The fixture contents are described in the README.

- `Scan_FixtureSolution_ReturnsAllCSharpFiles`
- `Scan_ProjectFailsToLoad_IsReportedInSkipped`: missing SDK, missing file, VB project, extra target framework.
- `Scan_SingleProject_LoadsItAndItsReferences`
- `Scan_GeneratedFiles_AreFlagged`
- `Graph_WithProjectReferences_ResolvesCrossProjectCall`: `Greet` is declared only under Lib's own define. The per-project
  graph has the Call edge, with exact tokens. BCL-only has the Use edge on `Greeter` but no Call edge.
- `CallResolution_ProjectCompilations_BindTheCallBclOnlyCannot`
- `Graph_FromCompilations_RejectsAFileOwnedTwice`

All 273 ChunkReuse unit tests pass.

## Mutation testing

Mutants were applied in my own worktree, which I was alone in, and restored byte for byte. Each restore was checked with a
hash and with `git status`. **14 of 15 were killed**; the table is in the README.

- Two mutants (duplicate ownership, tree-in-compilation check) at first **survived**. The test passed because a different
  `ArgumentException` was thrown. I fixed the test to check the builder's own messages, and both are now killed.
- **One survives**: counting candidate symbols as bound in `CallResolution`. The fixture has no ambiguous call. The metric
  definition (`Symbol` only) matches the graph builder.

## Step 5: dotLLM itself

Measured at worktree `b2acb3b6`, dirty=0.

- **Projects:** 27 scanned, **0 skipped**, no workspace diagnostics.
- **Files:** 2,583 C# files: 84 generated, **2,499 authored** (7.9 M tokens).
- **Scan time:** 27–31 s.
- **Resolved-call share: 100.0 % per project against 84.5 % BCL-only** (153.7 K invocation sites).
  - The lowest BCL-only shares are Tray.Tests 46.6 %, Tray 58.5 %, Cli 63.6 %, Tests.Integration 75 % and Tests.Unit 77.7 %.
- **Effect on the graph is small:**
  - Sites that bind to an authored file: 54.7 % against 54.4 %.
  - Call edges +634.
  - Edges in total 369,017 against 367,354 (+0.45 %).
  - Import edges mostly differ by construction: a per-project compilation sees only the namespace declarations its project
    can actually see.

The details and caveats are in `experiments/solution-scan/README.md`.

## Concerns

1. **Missing `<Import>` passes silently.** A project with a missing `<Import>` loads with no diagnostic (the workspace ignores
   missing imports) and is scanned. I found this while building the fixture. A missing SDK, a missing project file and a
   non-C# project are all reported.
2. **New dependency weight.** `DotLLM.ChunkReuse` now references Workspaces.MSBuild. It brings in the BuildHost
   content folders (`BuildHost-net472`, `BuildHost-netcore`), and the BuildHost folders are copied into every consumer's
   output, including the unit-test project. If the dotLLM lead wants the library lean, the scanner could move to its own
   assembly or into the CLI (Task 7).
3. **CI.** The scanner tests need `dotnet restore` of the fixture, which has a netstandard2.0 target, so NuGet must have
   `NETStandard.Library` 2.0.3. They also spawn a BuildHost process. I verified this on Windows only.
4. **Scope differs from the older corpus.** A dotLLM scan includes test projects, because the solution lists them.
   `Corpus.FromDirectory` excludes test directories. Task 6/7 should decide whether `chunkcache build` filters them.
5. **Branch base.** `feature/chunk-scan` branches from `feature/chunk-store` and touches `Directory.Packages.props`,
   `DotLLM.ChunkReuse.csproj`, `DotLLM.Tests.Unit.csproj`, `RoslynGraphBuilder.cs` and ChunkKvLab `Program.cs`. These are
   one-line or small additions; a merge with the chunk-index branch may need a trivial conflict resolution in the csproj or
   props files.
