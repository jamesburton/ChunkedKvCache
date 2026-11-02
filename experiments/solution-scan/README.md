# Solution scanner on dotLLM (Phase S, Task 5)

dotLLM branch `feature/chunk-scan` (worktree `C:\Development\dotLLM\.claude\worktrees\chunk-scan`, from `feature/chunk-store`
`63cebfbd`, not pushed). The code:

- `src/DotLLM.ChunkReuse/Corpus/SolutionScanner.cs`
- `src/DotLLM.ChunkReuse/Graph/{ProjectCompilation,CallResolution}.cs`
- `RoslynGraphBuilder.Build(IReadOnlyList<ProjectCompilation>, chunks)`

Tests are in `tests/DotLLM.Tests.Unit/ChunkReuse/SolutionScannerTests.cs`, with a fixture solution in
`tests/DotLLM.Tests.Unit/ChunkReuse/Fixtures/MiniSolution`. The lab command is `ChunkKvLab scan-info`. Run it with
`run.ps1`. The raw logs are `dotllm-symbol.log` and `dotllm-fixed.log`, and each starts with a provenance block.

## What the scanner does

- **Loading.** `SolutionScanner.LoadAsync(sln|slnx|csproj)` opens the solution or project with Roslyn's `MSBuildWorkspace` 5.9.0.
  Design-time builds run in Roslyn's out-of-process BuildHost, which finds the .NET SDK by itself. Because of that,
  **`Microsoft.Build.Locator` is not used**: the plan said to use it, but it is only needed when MSBuild is loaded inside the
  scanner's own process.
- **What it returns.** `ScanResult(Files, Skipped)`, plus:
  - `Projects`: one compilation per project, with that project's defines, parse options and references.
  - `Generated` / `IsGenerated(path)`: files under `bin`/`obj`, or files that `SymbolChunker.IsGenerated` flags.
  - `AuthoredFiles`: the files that are not generated.
  - `Diagnostics`: loader messages that name no project.
- **File texts.** Texts are converted from CRLF to LF, and the workspace documents get the LF text before any compilation is
  built. Tree offsets therefore equal chunk offsets.
- **Shared files.** A file compiled by several projects (linked files) appears once. It belongs to the first project by path.
- **Skipped projects.** Each `SkippedProject` gets a reason:
  - `load-failed`: the workspace reported a Failure for the project, or the solution lists it but it was not loaded. The
    workspace still adds a project whose SDK is missing; the scanner reports it and does not scan it.
  - `unsupported-language`: for example a `.vbproj`.
  - `extra-target-framework`: a multi-targeted project is scanned from one target (its first Roslyn project by name); the
    other targets get this reason.
- **Unrestored projects.** If a project loads without a core library (it was not restored), the scanner adds a warning to that
  project's diagnostics.
- **Known gap: a missing `<Import>` passes silently.** A project that imports a missing `.targets` file loads with no
  diagnostic, because the workspace ignores missing imports. It is scanned like a normal project. I found this while building
  the fixture.

## dotLLM itself (worktree `b2acb3b6`, dirty=0, SDK 10.0.401, 2026-11-02)

Tokenizer: Qwen3-4B-Instruct-2507 Q4_K_M @ `ae44f08e`. No weights are run.

| item | value |
|---|---|
| projects in `dotLLM.slnx` scanned | **27** |
| skipped | **0** (every project loads on this box, including Cuda, Hip and Vulkan; no workspace diagnostics) |
| C# files | **2,583**: 84 generated (3 per project under `obj/`) and **2,499 authored**, 29.2 M chars |
| tokens (authored) | 7.91 M with symbol-512 (39,078 chunks), 7.88 M with fixed-512 (16,610 chunks) |
| scan time | 27–31 s: workspace load, LF texts and 27 compilations; the solution was restored first |
| graph build | 35–36 s, about the same for both chunkers; the BCL-only build takes 35–38 s |

The test projects are included, because the solution includes them: `DotLLM.Tests.Unit` has 1,118 authored files. The older
`Corpus.FromDirectory` excludes test directories. The MiniSolution fixture is not compiled into the test project
(`Compile Remove`), and the solution does not list it.

### Per-project compilations versus BCL-only, same 2,499 authored files

The graph edges are the same for both chunkers, as in `graph-build.md`.

| | per-project | BCL-only |
|---|---:|---:|
| invocation sites | 153,743 | 153,301 (no defines, so different `#if` regions are compiled) |
| **bind to a method** | **153,693 (100.0 %)** | **129,472 (84.5 %)** |
| bind to an authored file (possible Call edge) | 84,058 (54.7 %) | 83,450 (54.4 %) |
| graph edges | 369,017 | 367,354 |
| Call edges | 89,944 | 89,310 (all 89,310 are also in per-project) |
| Use edges | 272,073 | 271,062 (271,054 shared) |
| Import edges | 6,918 | 6,900 (only 2,525 shared, see below) |
| Definition edges | 82 | 82 |
| edges in one set only | 6,046 | 4,383 |

- **Resolved-call share: 100.0 % per project against 84.5 % BCL-only.** I did not break the roughly 24 K sites that
  BCL-only misses down by target. The per-project pattern below suggests they are calls into packages and frameworks (xUnit
  `Assert`, Spectre.Console, ASP.NET Core, OpenTelemetry, WinForms in Tray), but this is inferred, not measured. The projects
  where the BCL-only share is lowest are:
  - Tray.Tests 46.6 %
  - Tray 58.5 %
  - Cli 63.6 %
  - Tests.Integration 75.0 %
  - Tests.Unit 77.7 %
  - Server 85.0 %
- **Effect on the graph is small: +608 sites bind to an authored file, +634 Call edges and about +1.0 K Use edges (+0.45 %
  edges in total).** The graph only keeps edges whose definition is in the corpus. Package APIs cannot become edges either way,
  and calls inside the solution mostly resolved already in one big BCL-only compilation. The edges that per-project adds come
  from symbols that BCL-only cannot see: names behind `#if` defines (as in the fixture test), and members reached through
  package-typed expressions.
- **Imports differ by construction (2,525 shared).** The definition end of an Import edge is the namespace's declaration in its
  ordinal-first declaring file. A per-project compilation only sees declarations from its own project and the projects it
  references. A merged BCL-only compilation sees every declaration in the solution. So per-project imports point at the first
  declaration the importing project can actually see. I count that as more correct, not as noise.
- **Per-project binding should also be more correct, not only more complete.** This is reasoning, not measured: a single
  merged compilation joins types of the same name from different projects and ignores per-project defines, and the
  per-project set-up has neither problem. I did not count how many BCL-only edges point at a wrong declaration.
- **Recommendation for Task 6/7 (`chunkcache build`).** Use the scanner and the per-project graph by default, and keep
  BCL-only for directory corpora that have no solution. The load cost is 27–31 s for this 7.9 M-token solution, about the cost
  of the graph build itself.

## Tests and mutation evidence

There are 7 tests in `SolutionScannerTests`, and all 273 ChunkReuse unit tests pass. The fixture is copied to a temp
directory and `App` is restored there (about 3 s). It contains:

- `Lib`: multi-targeted `net10.0;netstandard2.0`. `Greet` is declared only under the `MINI_GREETING` define.
- `App`: references `Lib`, calls `Greeter.Greet`, and has a hand-written `Generated/Stamp.g.cs`.
- `Shared/BuildInfo.cs`: linked into both projects.
- `Broken`: its SDK is missing.
- `Missing`: listed in the solution, but no file exists.
- `Tool`: a Visual Basic project.
- `Lib/Greeter.cs` is rewritten to CRLF in the temp copy.

Each mutant below was applied in the worktree, built, tested and restored byte for byte; the restore was verified with a hash
and with `git status`. 14 of the 15 mutants were killed:

| mutant | killed by |
|---|---|
| a Failure diagnostic no longer skips the project | FixtureSolution, SingleProject, ProjectFailsToLoad |
| a listed project that did not load is not reported | ProjectFailsToLoad |
| `obj/`/`bin/` paths not flagged as generated | GeneratedFiles |
| `SymbolChunker.IsGenerated` not used | GeneratedFiles |
| trees keep CRLF (no `WithDocumentText`) | Graph_WithProjectReferences |
| shared file not deduplicated | 4 tests |
| last target framework scanned instead of the first | FixtureSolution, RejectsAFileOwnedTwice |
| language check removed | all (the scan fails on the VB project) |
| tree path not mapped to corpus path (old behaviour) | Graph_WithProjectReferences |
| duplicate file ownership accepted | RejectsAFileOwnedTwice (after a fix: the first version of the test passed for another reason) |
| tree-in-compilation check removed | RejectsAFileOwnedTwice (same fix) |
| every file bound in the first project's compilation | Graph_WithProjectReferences |
| `CallResolution`: "to file" ignores the measured set | CallResolution test |
| `CallResolution`: path filter ignored | CallResolution test |
| `CallResolution`: candidate symbols counted as bound | **survived** |

The surviving mutant shows that the fixture has no ambiguous or overload-failure call. The metric counts only
`GetSymbolInfo().Symbol`, as `RoslynGraphBuilder` does.

## Reproduce

`pwsh experiments/solution-scan/run.ps1` restores `dotLLM.slnx`, builds ChunkKvLab in Release, and runs
`scan-info --chunker symbol|fixed --chunk 512`. It is CPU only and peaks at about 4 minutes per chunker.
