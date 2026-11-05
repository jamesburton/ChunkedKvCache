# PR 8 body draft: Server: chunk_cache auth, API keys and the /v1/chunk-cache control endpoints

> DRAFT, not pushed, not opened. Branch `pr/chunkcache-auth-endpoints` (local, worktree `C:\Development\dotLLM\.claude\worktrees\pr08`),
> one commit `a55da893` on `origin/dev` `8a17e42a` (includes #1639). Needs James's explicit per-PR go before push / PR; route the
> push and merge through dotllm-93's session. Open against `dev`.

## Title

Server: chunk_cache auth, API keys and the `/v1/chunk-cache` control endpoints

## Body

Refs #1542. Follows #1622 (parser), #1636 (span locator), #1639 (endpoint wiring).

### Summary

Adds who may use `chunk_cache` and which store namespace they get, plus the control routes.
- **Namespaces are server-assigned.** `--chunk-cache-api-keys <file>` maps API keys to namespaces (`ChunkCacheKeys`, with
  `--chunk-cache-allow-short-keys` for keys under 32 chars). Without a keys file only loopback callers use the surface. An
  unauthenticated remote caller's annotated request is still served normally, but its chunks are never looked up (and
  `report: "per_chunk"` degrades to the summary).
- **`ChunkCacheAuth`** decides the caller per request (`ForInference` for chat/messages, a stricter path for the control routes,
  Origin / Host checks against DNS rebinding on loopback); error bodies never echo a key.
- **Control endpoints** (`ChunkCacheEndpoint`, DTOs in `ChunkCacheControlDtos`): `GET /v1/chunk-cache` (capabilities) and
  `POST /v1/chunk-cache/explain`. Local callers only (loopback, matching Host, no Origin header) unless API keys are configured.
  Rate-limit hook so the limiter sees the surface.
- **Docs:** `docs/CHUNK_CACHE.md`, `docs/SERVER.md`.

### Scope

`git diff --stat origin/dev`: 23 files, +2,344 / -85. Not in this PR: the index, CLI-backed tests (`ChunkIndex.DefaultPath` lines in
`ChunkCacheEndpointTests` move to PR 10), prewarm/evict routes and the background writer (later PRs).

### Testing

- Windows: `Server` + `ChunkCache` + `ModelProfile` unit tests 1116 passed / 0 failed / 13 skipped.
- Linux Docker (non-root, CI filter): 1090 passed / 0 failed / 17 skipped.
- Mutants (auth, keys, exchange, endpoints, rate limiter): 26/26 and 17/17 killed on a fresh archive copy.
- One test setup changed vs the milestone: `ReportPerChunk_UnauthenticatedGetsSummary` sends the anonymous request with a different system
  prompt, because the default paged path reuses prefixes across requests (#1596) and a prefix-served chunk is `prefix`, not `hit`.

Known follow-up (separate): contract-folder `fixtures.sha256` / `capabilities.json` re-sync.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
