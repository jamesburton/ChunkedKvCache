# Umbrella: chunk-level KV reuse for agent harnesses (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. dotllm-97 / the user decide when and whether
> each issue is filed; one issue per PR, issue first. Each row below is filled in by the task named in it.

## Goal

Make chunk-level KV reuse reachable from agent harnesses (CodeSharp is the reference integration):

- a `chunk_cache` wire convention in the dotLLM server, behind `--chunk-cache` (off by default); policy `exact` by default
  and `shadow` for measuring hit rates; nothing lossy without an explicit opt-in (and none implemented in this phase);
- the store changes that make the server the only K/V writer (backend tag in the `.ckv` header, namespaced keys, a server
  ledger, short-scope locks, wire-eligible text-first chunking);
- a permissive client package (`DotLLM.ChunkCache.Client`, MIT, pure HTTP and DTOs);
- the `chunkcache` CLI with `--json` and a thin MCP server;
- a release path. Later gated phases: applied reuse (I5) and direct-to-device loading (D).

Flag off: request and response bytes are identical to today's for any body, annotated or not. Exact counters
(`usage.prompt_tokens_details.cached_tokens`, `timings.cache_n`) stay exact.

## Links

- Spec (rev 3, approved): `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md` (this repo)
- Plan: `docs/superpowers/plans/2026-11-02-phase-i-integration.md` (this repo)
- Wire contract fixtures every PR tests against: `docs/contracts/chunk-cache-v1/` (this repo; copied into each test
  project and checked against `fixtures.sha256`)
- Release plan (Task 21): `docs/release/chunk-cache-release-plan.md` (not yet written)

## PR list, in dependency order (Task 21)

Every PR targets `dev`, updates `docs/SERVER.md` (or the owning doc), documents and tests each new flag, follows the
System.Text.Json source-generator rules in dotLLM `CLAUDE.md`, and records mutant evidence in its body. `Closes #N` does
not auto-close on `dev`; close by hand.

| # | PR | Lane / plan tasks | Issue draft | Depends on | Status |
|---|---|---|---|---|---|
| 1 | Client package `DotLLM.ChunkCache.Client` (MIT; may ship first) | C: Tasks 6, 7, 8 | #1544 (types, `06-client-types.md`); chat client: _Task 8_ | none (no store task) | branch `feature/chunk-cache-client` (types done, chat client in progress) |
| 2 | Library: `DotLLM.ChunkReuse` store, index, scanner, selector; backend tag, namespace in `ChunkKey`, ledger, locks, `lines-512` | L: Tasks 1-5 | _Tasks 1-5_ | none | not started |
| 3 | Snapshot lineage (`exact` / `approx` tags) | S: Task 12 | `12-snapshot-lineage.md` (not filed) | none | done on `feature/chunk-cache-lineage` (`918bb68d`, off `dev` `857c55b9`); awaiting review |
| 4 | Server wire (I1a): parsing, span location, `exact` / `shadow`, response metadata, capabilities / explain / auth | S: Tasks 9, 10, 11, 13, 14 | #1543 (behaviour pin, `09-server-behaviour-pin.md`, titled 'Server: chunk_cache wire convention, flag off by default'); _Tasks 10-14_ | 3 | Task 9 done on `feature/chunk-cache-server` |
| 5 | Server store (I1b): sole-writer encode, admission, disk budget, prewarm / evict / forget | S: Tasks 15, 16 | _Tasks 15-16_ | 2, 4 | not started |
| 6 | CLI (`--json`, deny-list, server-backed writes) and MCP tool | T: Tasks 17, 18 | _Tasks 17-18_ | 2, 5 (endpoint contract), 1 | not started |
| 7 | Release wiring (`release.yml`: two package-id variables, `PackAsTool` for the CLI) | Task 21 | _Task 21_ | 1, 6 | not started |
| - | Vulkan wiring PRs (separate list, `NN-vulkan-*.md`; the tiled kernel is dotllm-97's PR #1541) | Task 22 | _Task 22_ | per PR | not started |

## Acceptance (umbrella)

- Fixtures in `docs/contracts/chunk-cache-v1/` pass in the server and client test projects; `expected.json` is exercised
  data-driven.
- `exact` and `shadow` leave generated tokens and `cached_tokens` identical to the unannotated request, blocking and
  streaming, including after a `shadow` request on a warm slot.
- Two writers on one store root never interleave (second gets `chunk_store_unavailable` / a non-zero exit).
- No lossy default: `balanced`, `fast`, `auto` parse and degrade to `exact` with `chunk_policy_unavailable` until Phase I5.
- Every PR shows at least one mutant that its tests fail against.

## Mutant evidence

Per-PR sections live in the individual issue drafts. Wire-contract fixtures: see
`.superpowers/sdd/2026-11-01-phase-s/phase-i-task-0-report.md` (hash byte, offset, UTF-16-vs-UTF-8 start).

## Filed issues (jamesburton/dotLLM, filed by dotllm-97)

- #1542 umbrella (this file)
- #1543 server behaviour pin / lane S lead (`09`)
- #1544 client types (`06`)
- #1546 client chat client (`08`)
- #1545 empty-body 400 on OpenAI array content (found by Task 9; not part of this feature)
- #1540 tiled per-query-position attention; PR #1541 (dotllm-97's)

Branch / commit / PR text uses `Refs #N`; `Closes #N` does not autoclose on dev.
