# PR 15 body draft: chunkcache CLI

> DRAFT, not pushed, not opened. Branch `feature/chunk-cache-cli-task17` (local, worktree `C:\Development\dotLLM\.claude\worktrees\task17`), head after the dev merge (see `git log`),
> built on dev with #1703, #1708 (Vulkan) and #1709 (Solution scanner) merged. If pushed it needs a PR-shaped branch name (e.g. `pr/chunkcache-cli`). Needs James's explicit go; route through dotllm-00.
> Cut report / evidence: `.superpowers/sdd/2026-11-01-phase-s/task17-report.md`.

## Title

chunkcache CLI: build / select / status / evict / prewarm / explain with --json, server-backed writes and the store owner lock

## Body

Refs #1542. Follows #1648 (index), #1676/#1703 (store hardening), #1709 (Solution scanner).

### Summary

`tools/DotLLM.ChunkCache` (a dotnet tool project, `IsPackable=false`) without `compare` and `recompute` (research, stay on the fork):

- **Verbs:** `build`, `select`, `status`, `evict`, plus new `prewarm` and `explain`. Every verb takes `--json` and prints exactly one JSON object on stdout (snake_case, schemas under
  `tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/schemas/`); diagnostics go to stderr; under `--json` an error is `{"error": {"code", "message", "exit_code"}}` with a non-zero exit.
- **Two writers, stated:** `--server URL` queues work through the server (prewarm endpoint: chunk TEXT goes out, never an entry, the CLI never writes the ledger); `--offline` encodes
  on this CPU into `--store` while holding `StoreOwnerLock.TryAcquire` for the WHOLE run (`store_owned`, exit 1, when a server or another writer owns the store; `IsHeldByAnother` is never a
  gate, see #1664). No stated writer is exit 2.
- **Secrets deny-list:** `ChunkDenyList.Default` is applied to the scanned tree; denied files are never chunked, indexed, encoded or sent (`denied_files` counts them). `prewarm --texts` refuses a
  `source.path` that is denied, rooted, has a drive, NUL or `..`; the CLI never opens a file named in JSON input.
- **Wire eligibility:** `wire_ineligible_chunks` = off the allow-listed chunkers, token-id slices, or a failing `VerifyRoundTrip`; chunkers off the allow-list need `--lab`.
- **`select --server`:** `stored` comes from one `explain` request per batch (manifest spans pinned by UTF-8 byte range and wire hash).
- **`evict`:** modes `orphans | path | namespace | all`, dry run unless `--apply`; an applying offline pass holds the owner lock; old mode names are rejected with a hint.
- **`--max-encode-tokens`** (tokens) beside `--max-chunks` (chunks).

### Threat / safety note

- The API key is read from `CHUNKCACHE_API_KEY` ONLY (no argument exists). It is replaced by `***` in every stderr line and JSON error (a server that echoes it in an error body cannot leak it),
  a key with control characters is refused without being echoed, and a warning is printed when it would travel over plain http to a non-loopback host.
- **Review fix (found in this cut, failing test first):** the default `HttpClient` follows redirects and keeps custom headers, so a 302 from the named server carried `X-API-Key` to the redirect
  target. The CLI now uses a handler with `AllowAutoRedirect = false`; a 3xx is reported as an error. Test `ApiKey_IsNotForwardedByARedirect_ToAnotherServer` runs two real loopback listeners.
- `--server` accepts http/https only; user info, query and fragment are dropped from the base URL.

### Known gaps (documented, not hidden)

- `--model` is still required with `--server` (the server has no tokenizer endpoint); the CLI checks that the local GGUF computes the server's producer and refuses otherwise.
- The CLI has no namespace option, so a server with namespaced keys is refused by the producer check.
- Prewarm and evict server endpoints are not on dev yet: those verbs are tested against a contract-fixture fake handler only; capabilities and `explain` are also tested against the real dev endpoints.
- The Step 5 demo re-run (CPU server, `--chunk-store`) is not done; it needs `cpu`/`cpu-bench` free and a server built from the research branch.
- `Compare_QueryWithThinkTag_UsesChunkTokenization` lives with `compare` on the fork.

### Verification

- Windows, `ChunkReuse` + `Server.ChunkCache` + `ChunkCacheCli` (`Category!=GPU`), after merging dev: 959 tests, 953 pass / 6 skip / 0 fail. CLI tests alone: 56 pass.
- Linux Docker (non-root, CI filter) same filter: 951 tests, 945 pass / 6 skip / 0 fail. (An earlier Linux run found a Windows-only assertion in `Build_StoreWriteFailure_ExitsOne`; it now branches by OS.)
- Tests were written after the implementation (not test-first); the red run was made on a scratch copy of the baseline with interface stubs: 22 of 23 new tests failed (`Select_HashEqualsWireHash` passed at
  baseline and is kept as a guard). The redirect test was written first and failed before its fix.
- Mutants `task17-mutants.py` on fresh `git archive` copies (restored byte for byte and compared): 38 mutants, 36 killed on the first pass; T36 and T37 survived and got tests (then killed);
  T39 (redirects followed) killed. No equivalent survivors. The Solution scanner mutants are in #1709.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
