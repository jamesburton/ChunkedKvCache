# PR 21 body draft: chunkcache `list`, complete `--help` for every verb, docs page and a help guard test

> DRAFT, not pushed, not opened. Branch `pr/chunkcache-cli-help` (local, worktree `C:\Development\dotLLM\.claude\worktrees\cli-help`), cut from `origin/dev` after #1719 merged;
> `origin/dev` merged in before finishing (already up to date at the last merge). Needs James's explicit go; route through dotllm-00.
> Cut report / evidence: `.superpowers/sdd/2026-11-01-phase-s/pr21-report.md`.

## Title

chunkcache: `list` verb, per-verb `--help` for every registered option (one registry), docs page with examples, and a guard test (#1721)

## Body

Refs #1721 (chunkcache half; the `dotllm` half is the separate in-flight CLI PR). Follows #1719.

### Summary

- **`chunkcache list --store DIR [--store DIR ...] [--server URL] [--json]`**: a read-only inventory. Per store: entries and bytes, leftover temp files, the owner-lock state,
  the server ledger's state, the registry note, and per index (chunker, model, producer): model path, source, files, chunks, tokens, distinct keys, and how many the store holds
  (`stored_keys`) or lacks (`missing_keys`). `--server` adds the server's own figures (`GET /v1/chunk-cache`: model id, producer, entries, bytes, budget). `--json` is one object, snake_case,
  with a schema `tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/schemas/list.json` that a test validates the output against.
  - **Read-only by construction:** it opens the store with `StoreLayout.Open(root, create: false)` (a missing directory is exit 1 and nothing is created), takes no owner lock and no store lock, and never saves the
    registry (a missing or corrupt registry is rebuilt in memory and reported as `registry_note`), the ledger or an index.
  - **The owner-lock state is advisory** (`StoreOwnerLock.IsHeldByAnother`, one probe, stale at once; an unprobeable lock file counts as `held`; see #1664). A writer never relies on it.
  - Index counts are read from the index files directly: `ChunkIndex.Load` needs the model's key function and answers an empty index for any other producer, so it cannot be used without a model.
- **One option registry.** `VerbDef`/`OptionSpec` (`CliHelp.cs`, `VerbDefs.cs`) register every option once; the parser's table (`VerbDef.Spec`) is derived from it and `--help` is rendered from it. The
  per-command `Spec`/`Help` blocks and the `Common.*Options` tables are gone. The registered option sets and kinds of the six existing verbs are unchanged (compared against the pre-refactor tables).
- **`--help` for every verb** now documents ALL registered options: purpose, value form, default, valid values/range with unit, whether repeatable, env var (`CHUNKCACHE_API_KEY`), exit codes (including what 3 means
  per verb), every `--json` field, and examples; plus the global `--verbose`. Options that exist today but had no text are covered (`--budget`, `--max-encode-tokens`, `--max-chunks`, `--chunk-tokens`, `--max-tokens`, `--lab`,
  `--strict`, `--strict-model-id`, `--reroot`, `--no-scan`, `--list-missing`, `--include-text`, `--order`, `--lock-timeout`, `--threads`, `--show`, ...). Options that are registered but rejected by a verb
  (`explain --model`, `prewarm --offline`, `evict --all-for-model`, ...) say so and show the default `rejected`. A usage error now prints the verb's synopsis and a pointer instead of repeating the whole help.
- **Guard tests** (`ChunkCacheCliHelpTests`): fail on a registered option with no help text, value form or default, on a verb with no example, on a `--json` field (found by reflection over the result types and
  in the schema files) that `--help` does not mention, on a help example that does not parse against the verb's own options, on a verb missing from the top-level usage, and on a docs page that lists other verbs than the tool
  has. The docs option tables are generated from the registry and a test fails when they drift (`CHUNKCACHE_WRITE_DOCS=<file>` regenerates them).
- **Docs:** `docs/CHUNK_CACHE_CLI.md` gains a command index, an environment table, option conventions, an exit-code table, a `list` section with text and JSON output, generated option tables and per-verb examples;
  `docs/CLI.md` gets a short companion-tool section linking to it.

### Review notes

- `EvictCommand.cs` changes are the removal of its `Spec`/`Help` block only (no logic); `StoreLayout.LooksLikeStore` is untouched. Another change edits that file: expect a trivial conflict in that region.
- `StatusCommand.ReadLedger` became `internal` so `list` reports the ledger the same way.
- Deviation from the issue's wording: the chunkcache reference stays in `docs/CHUNK_CACHE_CLI.md` (written for #1719) with a pointer from `docs/CLI.md`, not a second full section there.

### Known gaps

- The issue's `dotllm` items (`dotllm list`, `--json` on `ps`/`model list`/`model info`, the guard over the Spectre tree, the SERVER.md mapping table, the TRAY.md flags) are not part of this PR.
- `--verbose` is stripped before the parser runs, so it is in no option table and the guard cannot cover it; it is documented in the top-level usage and in every verb's help by hand.
- The guard checks the shape of the text (clauses, value form, default), not its quality; the `--json` field check passes on any mention of the field name in the JSON section.
- `list` reports a registry row whose index file vanished between the registry read and the index read as `state: missing` (a race; the registry normally drops such rows, so no test can reach it: mutant L18 survives by design).
- The docs generation is test-guarded, not yet a build step; examples in the docs are parsed, not executed.

### Verification

- Windows, `(ChunkReuse | Server.ChunkCache | ChunkCacheCli) & Category!=GPU`: 983 tests, 976 pass / 7 skip / 0 fail. CLI tests alone (`ChunkCacheCli`): 80, 79 pass / 1 skip (the 59 + 1 skip of #1719 plus 11 help and 9 list tests).
- Linux Docker (non-root, CI filter, 4 GB VM), same filter: 975 tests, 969 pass / 6 skip / 0 fail (the 11 help and 9 list tests ran and passed there too; owner-lock probing under `flock` semantics included).
- Test-first: the guard and list tests were written and run RED against an interim registry (every option registered with empty help, `list` stubbed): 15 of 19 failed, among them
  `build --model: no help text`, `build: no example`, and `List_OfAMissingStore...` (`internal` instead of `error`); the 4 that passed were `Guard_FailsOnAnUndocumentedOption` and `DocsExamples_Checker_RejectsABadExample` (self-checks of the checkers: the first feeds the guard a fake option with no help text, no default and no value form, and a verb with no example, and asserts each is reported) and two that are vacuous against the interim registry (`ParserSpec_IsDerivedFromTheRegistry...`, `HelpExamples_ParseAgainstTheRegisteredOptions`: no examples yet). Log: `.superpowers/sdd/2026-11-01-phase-s/pr21-red.log`.
- Mutants `pr21-mutants.py` on fresh `git archive` copies (restored and compared): 20 mutants, 19 killed (first pass: 18; L8 "help drops the Default clause" survived because the check compared the help to the same renderer's
  output; the check now reads each option's own entry and L8 is killed), 1 equivalent/defensive survivor (L18). Killed: list reports a holder as free, creates the store directory, saves the registry, takes the owner lock,
  miscounts stored keys, ignores an unreadable index or the ledger, accepts no `--store`/a single `--store`; an option's help removed, an option omitted from the help, the Default or Env clause dropped, a JSON field
  undocumented, a made-up option in an example, the parser table diverging from the registry, the docs table drifting, the usage error dumping the whole help, the verb missing from the top-level usage.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
