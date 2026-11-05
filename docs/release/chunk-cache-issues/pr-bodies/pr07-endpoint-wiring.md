# PR 7 body draft: Server: wire `chunk_cache` into the chat and messages endpoints (`exact` / `shadow`)

> DRAFT, not pushed, not opened. Branch `pr/chunkcache-endpoint-wiring` (local, worktree
> `C:\Development\dotLLM\.claude\worktrees\pr07`), one commit `05d4482e` on `origin/dev` `f53c55ed` (includes #1622 parser and
> #1636 span locator). Needs James's per-PR go-ahead before push / PR; route through dotllm-93's session. Open against `dev`.
> Closes nothing by itself: **close #1632 by hand** once merged.

## Title

Server: wire `chunk_cache` into the chat and messages endpoints (`exact` / `shadow` report, read-only store lookup)

## Body

Refs #1632, #1542. Follows #1622 (parser) and #1636 (span locator).

### Summary

With `--chunk-cache` on and an annotated body, `/v1/chat/completions` and `/v1/messages` now parse the annotations, locate
them in the prompt exactly as rendered, verify their token ids and look them up in a **read-only** `--chunk-store`. Generation
is untouched: `exact` (default) and `shadow` produce byte-identical output to the unannotated request, with the same
`cached_tokens`. The response gains a `chunk_cache` report (blocking body, final stream chunk, Anthropic `message_delta`) and
`timings.chunk_n` / `chunk_recomputed_n` (0). `balanced` / `fast` / `auto` are served `exact` with a reason (strict: 400
`chunk_policy_unavailable`). With the flag off nothing changes.

- **prefix and hit are separate counts.** A chunk wholly inside the restored exact prefix is `prefix`; a store lookup hit is
  `hit` (decision recorded on #1632). `annotated = prefix + hit + miss + ignored`.
- **Profile system prompt.** Both endpoints pass the profile-prompt offset to the locator (engine indices are counted before
  `ProfileSystemPrompt.Apply`); new endpoint tests cover both surfaces with and without a profile.
- **Bounded work (#1632).** The overlap check keeps accepted ranges sorted and looks at the two neighbours (O(log n) per span,
  was a scan of every earlier range). `--chunk-cache-max-chunks` is now 1 to 65536 (was "no upper bound"); docs updated.
- **Lone surrogate.** Over HTTP an Anthropic text block holding a lone surrogate is decoded to U+FFFD and served (200, span
  `chunk_span_invalid`); the converter exception only occurs for in-process requests. Pinned by a test, no extra guard.
- **Metrics.** `ChunkCacheMetrics` counters under `/metrics`; `docs/TELEMETRY.md` row.
- **Cost model.** `chunk-cost-model.json` (per backend) feeds `full_prefill_estimate`.
- **Docs.** `docs/CHUNK_CACHE.md`, `docs/SERVER.md`.

### Scope

`git diff --stat origin/dev` : 34 files, +3,165 / -63. `Server.csproj` gains the `DotLLM.ChunkReuse` reference (merged in #1577/#1588).
Not in this PR: auth, keys, control endpoints (PR 8); CLI-backed tests (`ShadowKey_ChunkWithThinkTag_HitsStoreEntryFromCli`,
`ServerIdentity_EqualsCliModelHandle`) move to PR 15 with the CLI; the contract fixtures `response-anthropic-delta.json` +
`fixtures.sha256` are re-pinned (S5 milestone).

### Testing

- Windows: `Server` + `ChunkCache` unit tests 1094 passed / 0 failed / 13 skipped.
- Linux Docker (non-root, CI filter): 1068 passed / 0 failed / 17 skipped.
- Mutants (parser, locator and the new overlap/cap logic; baseline 212/212): PR 5 set 40/40 killed, PR 6 set 24/24 killed, 3 new killed; one equivalent survivor (`<` vs `<=` in the overlap binary search, an equal-start range is still the left neighbour).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
