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

## Step 5: dotLLM itself (superseded by the fix-round rerun below; these first-run headlines are not to be quoted)

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

## Fix round (review `review-task5-report.md`)

**Status: DONE.** No blockers were open; every should-fix is addressed. Two mutants survive and are documented: F11 needs
targeting packs that are not in the offline cache, and F15 is a redundant check.

### dotLLM commits (`feature/chunk-scan`)

- `1eff5dfa`: the review fixes, S1–S9 and the nits.
- `5d5333ad`: `CallSite.Length`. Nested invocations share a start offset, which crashed the first rerun of the site
  comparison.

### Fixes

- **S8: the scanner has its own assembly.**
  - `src/DotLLM.ChunkReuse.Solution` (namespace `DotLLM.ChunkReuse.SolutionScan`) holds Workspaces.MSBuild,
    CSharp.Workspaces and an explicit `Microsoft.VisualStudio.SolutionPersistence` 1.0.52 reference, all with central
    versions.
  - `DotLLM.ChunkReuse` is back to only `Microsoft.CodeAnalysis.CSharp`.
  - The test project and ChunkKvLab reference the new assembly, and `dotLLM.slnx` lists it.
- **S1: generated-file detection is syntax-based** (`GeneratedFiles.IsGenerated(path, tree)`).
  - A marker counts only in the comments before the first token, and the attribute only as real attribute syntax.
  - `SymbolChunker.cs` and `CorpusTests.cs` are now authored.
  - The 3rd file the old text check flagged is identified:
    `~/.nuget/packages/microsoft.net.test.sdk/17.13.0/build/netcoreapp3.1/Microsoft.NET.Test.Sdk.Program.cs`. It is a
    Test.Sdk compile item outside the solution directory, so it gets a `../` path.
  - `SymbolChunker.IsGenerated` is unchanged, because frozen corpus hashes depend on it.
  - Tests: 12 theory cases, plus fixture files `Heuristics.cs` (authored, with the markers in literals) and `Tooling.cs` (a
    real `[GeneratedCode]` attribute).
- **S2: scope rows in the README and scan-info.**

  | scope | bind (per-project / BCL-only) | to an authored file (per-project / BCL-only) |
  |---|---:|---:|
  | all 28 projects | 99.97 % / 84.37 % | 54.51 % / 54.26 % |
  | without tests | 99.92 % / 96.80 % | 60.96 % / 61.10 % |
  | `Corpus.FromDirectory` scope | 99.92 % / 96.66 % | 62.25 % / 62.41 % |

- **S3: the Cli reverse case was a denominator effect.** Per project has 441 more Cli sites, from `#if` regions. Site by
  site, 0 sites bind to an authored file under BCL-only but not under per-project, and 0 bind to a different declaration.
  The README now says there is no evidence that BCL-only binds wrongly.
- **S4: diagnostics are attributed by the quoted project path.**
  - The path is taken from `processing the file '<path>'`, or from a single quoted project path, normalised and compared
    case-insensitively on Windows.
  - Unattributed failures go to `ScanResult.Diagnostics` and onto every scanned project.
  - Fixture: `UsesBroken` references `Broken`. The loader repeats Broken's failure with an empty path (`''`); that repeat is
    flagged on every project, and `UsesBroken` is scanned.
  - A unit test with synthetic messages covers case, separators, unquoted paths, non-project paths, two paths, an unknown
    path and an empty path.
- **S5: one file under different spellings.**
  - Paths take their on-disk casing on Windows.
  - `RoslynGraphBuilder.PathComparer` is used for the ownership guard and for location mapping.
  - Fixture: on Windows, App links `..\shared\buildinfo.cs` in lower case. There is a test for the Lib → BuildInfo edge
    across spellings, and a test that the builder rejects the same file claimed twice under two spellings.
- **S6: multi-targeted projects.**
  - The scanned target is chosen deterministically: highest .NET 5+, then .NET Core, .NET Standard, .NET Framework,
    platform-neutral first, then by name. This is documented and unit-tested.
  - `SkippedProject.Files` lists the files that only the other targets compile (fixture: `Lib/Polyfill.cs`), and the
    message names them.
  - `ExtraTargetFramework` is documented as informational.
- **S7:** the fixture now has a `Greeter.Greet(1)` overload failure. It counts as an unresolved invocation and gives no
  edge, which kills C3. `CallResolution.Sites` gives the target of each site; delegate `Invoke` binding is documented.
- **S9:** a caveat table in the README (`global.json` and several SDKs, no SDK, .NET Framework projects, missing
  `<Import>`, unmatched project references, non-Windows, offline CI). Plan Task 5 Step 3 is edited (the MSBuildLocator
  deviation, and the separate assembly).
- **Nits:**
  - `ScannedProject.ProjectReferences` and `TargetFramework`.
  - Cached `AuthoredFiles` and `Compilations`.
  - A cancellation test.
  - A shared file is owned by the project whose directory holds it (fixture: `Lib/LibInfo.cs`).
  - A `.shproj` message.
  - The usage typo.
  - README wording: "99.67 % or more in every project, 99.97 % overall", and Imports labelled "not measured".

### Tests and mutants

- 23 scanner tests (counting theory cases); all 289 ChunkReuse tests pass.
- Mutants, fix round: 17 run, 15 killed (table in the README).
  - F11 (TFM picked by ordinal name at the call site) survives: the fixture's targets cannot tell the two orders apart
    offline. The comparer itself is unit-tested.
  - F15 (no early cancellation check) survives: the check is redundant, because `OpenSolutionAsync` observes the token.

### Rerun on dotLLM (`5d5333ad`, dirty=0)

- 28 projects, 0 skipped.
- 2,586 files: 85 generated (84 under `obj/` + 1 Test.Sdk `Program.cs`) and 2,501 authored.
- Graph edges: 370,209 per project against 368,483 BCL-only (+0.47 %).
- Scan time 20–27 s.

### Process note

One full ChunkReuse test run failed once, while my own background `run.ps1` (ChunkKvLab) held locks on the DLLs that the
build copies. I stopped that task through its task ID (TaskStop), not by process name. After a clean rebuild the test passed
in three runs in a row.

## Re-review round (`review-task5-rereview.md`)

**Status: DONE.**

### dotLLM commit

`229fc630` on `feature/chunk-scan`. Cherry-pick it onto `feature/chunk-cache`. It needs `1eff5dfa` and `5d5333ad`, which
the coordinator reports are already merged there.

### Fixes

- **R1, plan.** Task 5's file path is now `src/DotLLM.ChunkReuse.Solution/SolutionScanner.cs`. Task 9's package list adds
  `DotLLM.ChunkReuse.Solution`. Task 6 is untouched; the coordinator is changing it, and I committed only my two plan lines.
- **R2, Linux and macOS.** CI runs these tests on `ubuntu-latest`. That is **unverified here and must be green before
  merge**.
  - I read the test code for Windows assumptions. The case-variant link and the case-insensitive assertions are Windows-only;
    paths come from `Path.Combine`/`GetTempPath`; the csproj links use `\`, which MSBuild normalises.
  - The README now has caveats for macOS (APFS is case-insensitive, but the scanner compares ordinally off Windows) and for
    Windows per-directory case sensitivity.
- **R3, the F11 survivor.** It is killed by the fixture `Std` (`netstandard2.0;netstandard2.1`; the scanner picks 2.1). The
  README's wrong reason is corrected.
- **R4, Debug configuration.**
  - The 442 extra sites (441 in Cli, 1 in Cuda) are `#if DEBUG` code, because the scanner evaluates projects in Debug. The
    README now says this and quotes Cli 26.29 % against 30.63 % under the current metric.
  - New `SolutionScanOptions(Configuration = "Debug")`, and `scan-info --configuration`. The default stays Debug (MSBuild's
    default, and what produced the recorded numbers). Release is recommended for `chunkcache build`.
  - Test: `DEBUG`/`RELEASE` preprocessor symbols, and `obj/Release` files.
- **Nits.**
  - `///` and `/** */` documentation-comment headers now count as generated-file markers.
  - `[GeneratedCode]` on a single member no longer marks the file; on a type, delegate or assembly it does.
  - Theory cases for `#nullable` first, `#pragma` first, a BOM, a CRLF header and an assembly attribute.
  - A path with an apostrophe in a "processing the file … with message:" message now attributes. 8.3 short names are
    documented as a caveat.
  - `SkippedProject.Files` excludes files that another project scans (fixture: `Shared/Legacy.cs`).
  - `IsPackable=false` on `DotLLM.ChunkReuse.Solution`.
  - The README describes platform-neutral TFMs as a tiebreak, and documents `FromName`.
  - `RoslynGraphBuilder` has a doc note on chunk-path spelling.
  - The first-run headline in this report is marked superseded.

### Tests and mutants

- 30 scanner tests, counting theory cases; all 296 ChunkReuse tests pass.
- Mutants this round: 6 run (F11, G5, G6, A1, X1, K1), all killed. G6 was rerun after its first form disabled the whole
  comment filter rather than only the doc-comment kind.
- No dotLLM rerun: the change does not alter the Debug scan output for dotLLM (see the README).