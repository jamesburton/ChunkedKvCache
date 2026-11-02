# Phase I (chunk-cache integration for agent harnesses) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chunk-level KV reuse reachable from agent harnesses: a `chunk_cache` wire convention in the dotLLM server
(behind a flag, `exact` by default, `shadow` for measurement), the store changes that let the server be the only writer,
a permissive .NET client package, the `chunkcache` CLI with `--json` and a thin MCP server, a CodeSharp handoff, and a
release path, with later gated phases for applied reuse (I5) and direct-to-device loading (D).

**Architecture:** Four lanes in separate dotLLM worktrees. Lane L (library, `feature/chunk-cache`) changes the store:
backend tag in the header, namespaced keys, a server ledger, short-scope locks, wire-eligible chunking. Lane C (client,
own branch off `dev`) is a dependency-light `DotLLM.ChunkCache.Client` (MEAI decorator plus HTTP body handler, index-backed
chunk source, control-plane client). Lane S (server, own branch off `dev`, owned upstream by the dotLLM sessions) parses
annotations, locates spans in the rendered prompt, tags snapshot lineage, runs `exact` / `shadow`, and adds
`/v1/chunk-cache/*`. Lane T (tooling, `feature/chunk-cache`) revises the CLI so every K/V write goes through the server,
and wraps it in MCP. A golden fixture set in this repo (Task 0) is the shared wire contract all lanes test against.

**Tech Stack:** C# / .NET 10, ASP.NET Core minimal APIs (dotLLM server), `Microsoft.Extensions.AI.Abstractions` (client),
official MCP C# SDK (`modelcontextprotocol/csharp-sdk`; `ModelContextProtocol.Core` by default, chosen in Task 18
Step 0), xUnit with `[SkippableFact]` GPU gating, dotLLM CPU
and Vulkan backends, GitHub Actions `release.yml` / `ci.yml` (documented, not changed upstream).

**Spec:** `docs/superpowers/specs/2026-11-02-chunk-cache-integration.md` (rev 3, `c6f95e3`, approved by the user). Section
numbers below (§5.3, L4, I1a, ...) refer to it. Contracts consumed: `experiments/store/README.md` (store, key, assembler,
`GgufIdentity`), `.superpowers/sdd/2026-11-01-phase-s/task-4-report.md` (`ChunkIndex`, `ChunkRef`), `task-6-report.md`
(`ContextSelector`), `.superpowers/sdd/2026-11-01-phase-g/task-1-report.md` and `task-3-report.md` (`IChunkBackend`,
`ChunkKvEntry.Backend`), dotLLM `docs/SERVER.md`, `docs/PACKAGING.md`.

## Global Constraints

- **Preconditions.** Phase S Task 7 (CLI, uncommitted in `chunk-cache` at plan time) is committed and reviewed before any
  Lane L or T task starts. E4c (`experiments/E4c-text-first-chunks/`) runs independently; only Task 19 waits for it.
- **Worktrees and branches** (never switch branches in the shared `C:\Development\dotLLM` checkout):
  - Lane L and T: `C:\Development\dotLLM\.claude\worktrees\chunk-cache`, branch `feature/chunk-cache`.
  - Vulkan backend and tiled kernel: `chunk-vulkan` worktree, branches `feature/chunk-reuse-vulkan` (`bac190ab`) and
    `feature/chunk-reuse-vulkan-tiled` (`7bef8f38`, carries unmerged PR #1541). Only Task 20 and Phase D use the tiled one;
    nothing merges the tiled branch into `feature/chunk-cache`.
  - Lane C: new worktree `chunk-client`, branch `feature/chunk-cache-client` from `origin/dev`.
  - Lane S: new worktree `chunk-server`, branch `feature/chunk-cache-server` from `origin/dev`.
- **Lane S ownership (resolved with dotllm-97, 2026-11-02).** We draft and implement small PRs to `dev` from feature
  branches off `dev`; one issue per PR, issue **first**. dotllm-97 / the user file the issues and review / merge; **our side
  files nothing** and pushes nothing without the user's explicit approval per PR (spec approval is not that approval).
- **Issue drafts are a deliverable of every dotLLM-facing task** (Lanes L, C, S, T, Task 22): a file
  `docs/release/chunk-cache-issues/<NN>-<slug>.md` in this repo with title, body, acceptance criteria and the PR's mutant
  evidence section; `00-umbrella.md` (written in Task 0) links them all in PR order.
- **dotLLM PR acceptance criteria (every dotLLM-facing task):** PR targets `dev`, never `main`; `docs/SERVER.md` (or the
  owning doc) updated in the same PR; every new server / CLI flag documented and covered by a test; System.Text.Json
  source-generated DTOs follow dotLLM `CLAUDE.md` (no init-property initializers: nullable property plus a resolved
  default), and each new `JsonSerializerContext` gets a `JsonContextDefaultsTests`-style guard; correctness tests shown to
  fail against a mutant, recorded in the PR body; `Closes #N` does not auto-close on `dev` (closed by hand); rebase on `dev`
  often.
- **Feature flag.** Every server behaviour sits behind `--chunk-cache` (off by default). Flag off: request and response
  bytes are identical to today's for any body, annotated or not.
- **No lossy default.** Lane S implements only `exact` and `shadow`. `balanced`, `fast` and `auto` parse, then degrade to
  `exact` with reason `chunk_policy_unavailable` until Phase I5. The default stays `exact` after #1540 too.
- **Exact counters stay exact.** `usage.prompt_tokens_details.cached_tokens` and `timings.cache_n` count exact rows only.
- **Server is the only K/V writer (L1).** The CLI writes only with `--offline` while holding the store lock.
- **CPU and Vulkan entries never mix.** The backend is in the key (existing) and in the `.ckv` header (Task 1); a mismatch is
  a miss, never a conversion.
- **Licences.** `DotLLM.ChunkCache.Client` is MIT, in the dotLLM repo with its own `PackageLicenseExpression` override
  (decided by James; dotllm-97 will confirm the MIT-in-GPL-repo / NOTICE / trusted-publishing question with him). It is pure
  HTTP plus DTOs with no project reference to any GPL dotLLM project (wire DTOs are duplicated in the client, not shared with
  the server), and references no
  `DotLLM.*` engine assembly; everything else inherits dotLLM's `GPL-3.0-only`.
- **CPU vs GPU.** Tasks are marked **[CPU]** or **[GPU-lock]**. CPU tests run with `DOTLLM_SKIP_VULKAN=1`. GPU work uses the
  dotLLM GPU lock (`scripts/gpu-lock.sh`, stale after 90 min), queues FIFO behind other agents, is coordinated through the
  user before launch, and runs on the local iGPU only (T5500 needs the user's approval each time). A device-lost kills the
  process: disable the case statically, never catch-and-skip.
- **TDD and mutation evidence per task.** Tests first and seen failing; each correctness test must fail against a wrong
  implementation, shown by mutants run in a `git archive` scratch copy (never the live worktree while jobs run), listed in the
  task report. GPU tests use `[SkippableFact]`, `Skip.IfNot(VulkanDevice.IsAvailable())`, `Trait Category=GPU`.
- **Independent review per task** (fresh reviewer, spec and quality), fix rounds until clean; ledger in
  `.superpowers/sdd/2026-11-02-phase-i/progress.md`, reports `task-N-report.md` beside it.
- **Wire constants (verbatim from the spec):** convention `v: 1`; hash `"sha256:" + lowercase hex` of the UTF-8 bytes of the
  decoded JSON string; manifest offsets are UTF-8 bytes, end exclusive; `id` ≤ 256 chars, never used for lookup;
  `min_chunk_tokens` default 32; positioning `isolated` only; `report` default `summary` (counts only).
- **Error mapping (§5.8):** strict errors are `400 invalid_request_error` with a `code`; `chunk_store_unavailable` is `503
  api_error`. No 422.
- **Deny-list (§10), default:** `.env*`, `*.pem`, `*.key`, `*.pfx`, `id_*`, `secrets.json`,
  `appsettings.*.Development.json`, `.git/**`.
- **Provenance per measured run:** commit, dirty=0, model revision, backend, driver, GPU-lock holder; ≥ 3 repeats.

## Review Focus

- **Unreadable ledger or index during `orphans` eviction** must fail closed (no deletions, an error naming the file), never
  treat server-written entries as orphans. Test in Task 3.
- **Non-ASCII and CRLF text through a real serializer** (`\u00e9` escapes, a surrogate-pair emoji before a span, CRLF file
  read): the hash is over decoded text, UTF-16→UTF-8 offsets are exact, and CRLF text misses an LF-indexed entry rather than
  hitting wrongly. Tests in Tasks 8 and 10 (shared fixture `nonascii-crlf.json`).
- **`exact` neutrality on a warm slot:** an `exact` request after a `shadow` request on the same slot, blocking and
  streaming, returns the same tokens and the same `cached_tokens` as the unannotated request. Test in Task 13.
- **Crash or full disk mid-encode or mid-ledger-save:** no loadable corrupt entry; a ledger row without a file is dropped on
  load; a file without a ledger row or index reference is the only kind of orphan. Test in Task 15.
- **Two writers on one store root** (two servers, or a server plus `chunkcache --offline`): the second gets
  `chunk_store_unavailable` / a non-zero exit within the lock timeout, never interleaved writes. Tests in Tasks 4 and 17.

---

## Order, parallelism and gates

| lane | tasks (serial within a lane unless noted) | worktree | runs |
|---|---|---|---|
| contract | 0 | this repo | first; feeds every lane |
| L library | 1 → 2 → 3 → 4; 5 → 5b may run beside 2–4 in a temporary worktree `chunk-wire` off `feature/chunk-cache` (merge conflict expected only in the index JSON context); 5b precedes Tasks 13, 15 and 17 | `chunk-cache` | CPU (Task 1 has one GPU-lock step) |
| C client | 6 (its review fixes run in parallel with everything else) → (7 ∥ 8); no dependency on any store task (L or I1b), so it may ship first (user-approved) | `chunk-client` | CPU; fully parallel with L and S |
| S server (we implement, dotllm-97 / user file and merge) | 9 (done, `38c0314b`) → 10 → 11 → 13 → 14; 12 parallel with 10–11 in worktree `chunk-server-lineage` (separate files: `DotLLM.Engine/PromptCache/*`); 15 → 16 after Lane L Task 4 is merged into the server branch | `chunk-server` | CPU (Task 15 has one GPU-lock step) |
| T tooling | 17 → 18, after Tasks 4, 5, 6 and the Task 16 endpoint contract | `chunk-cache` | CPU |
| gated | 19 (E4c), 20 (tiled kernel, GPU), 21 (release doc), 23 (E10, GPU, after the tiled kernel supports the dtypes) | various | see each |
| PR split | 22 (Vulkan wiring PRs), any time after Task 20; docs plus local branches only | `chunk-vulkan` + new worktrees off `dev` | CPU (re-verification GPU steps under the lock) |

**Gates (stop and report to the user):**
- **G-I0: passed 2026-11-02.** Decisions answered (see "Decisions (answered 2026-11-02)"); Lane S ownership resolved with
  dotllm-97.
- **G-I1, after Tasks 6–14:** I1a wire and client contract done; the user decides on issues / PRs for Lane S and the client.
- **G-I2, after Tasks 15–18:** I1b store and I3 tooling done; the CodeSharp handoff (Appendix A) may be sent with approval.
- **G-E4c:** Task 19 runs only on E4c's outcome. **G-tiled:** Task 20 needs the G2b result and a GPU slot via the user.
- **G-REL:** Task 21 produces the release doc; the user does the account setup; nothing is pushed by us.
- **G-D, G-I5:** later phases at the end of this plan, each with its own gate.

---

### Task 0: Wire contract fixtures [CPU]

**Files:**
- Create (here): `docs/contracts/chunk-cache-v1/` with `README.md`, `fixtures.sha256`, and the JSON fixtures below
- Create (here): `docs/contracts/chunk-cache-v1/check.py` (recomputes every hash and offset in the fixtures)

**Interfaces:**
- Produces: fixtures each lane copies into its test project (`tests/DotLLM.Tests.Unit/ChunkCache/Fixtures/v1/` in dotLLM,
  the client's test project likewise) and checks against `fixtures.sha256`:
  `inline.json`, `manifest.json` (both §5.1 examples with real hashes), `conflict.json` (both placements),
  `nonascii-crlf.json` (escaped `\u00e9`, a surrogate pair before the span, one CRLF part), `bad-span.json` (offset inside a
  multi-byte character, overlap, out-of-range part, non-text part), `hash-mismatch.json`, `response-blocking.json`,
  `response-stream-final.json`, `response-anthropic-delta.json`, `response-shadow.json` (§5.9 partition holds),
  `capabilities.json` (§5.9), and `expected.json` mapping each request fixture to its warnings / strict error code.

- [ ] **Step 1:** Write `check.py` asserting: every `hash` equals `sha256:` of the UTF-8 of the decoded span text; every `at`
  is on UTF-8 boundaries (except in `bad-span.json`); `prompt = prefix_reused + prefix_reused_approx + chunk_reused +
  prefilled` and `chunk_recomputed ≤ chunk_reused` in every response fixture.
- [ ] **Step 2:** Run `python -I docs/contracts/chunk-cache-v1/check.py` against an empty folder; expected FAIL (no fixtures).
- [ ] **Step 3:** Write the fixtures and `README.md` (one line per fixture: what it pins, spec section).
- [ ] **Step 4:** Rerun; expected `OK n fixtures`; write `fixtures.sha256`; mutate one hash byte and one offset to show the
  checker fails.
- [ ] **Step 5:** Write `docs/release/chunk-cache-issues/00-umbrella.md` (goal, link to the spec, the PR list in Task 21's
  order, each to be filled by its task); commit (`docs/contracts/`, `docs/release/`).

### Task 1: Merge the chunk branches; backend tag in the `.ckv` header (L4) [CPU + one GPU-lock step]

**Files:**
- Merge into `feature/chunk-cache`: `feature/chunk-kv-reuse` (`c4579f55`: `TextFirstFixedChunker`, E4b) and
  `feature/chunk-reuse-vulkan` (`bac190ab`: `IChunkBackend`, `ChunkKvEntry.Backend`, `ResidentChunkKvEntry`)
- Modify (dotLLM): `src/DotLLM.ChunkReuse/Store/FileChunkStore.cs` (format version 2), `Store/StoredContextAssembler.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkStoreTests.cs`, `StoredAssemblyTests.cs`

**Interfaces:**
- Consumes: `ChunkKvEntry(..., string Backend = "cpu")`, `IChunkBackend.Tag`, `ChunkKey.Create(..., backend, dtype, tokens,
  positioning)`.
- Produces: `.ckv` format version 2 whose header carries the backend tag (length-prefixed UTF-8); version-1 files are misses.
  `StoredContextAssembler(ChunkFingerprint, string tokenizerId, IChunkBackend backend)` and `ForModel(config, modelId, quant,
  tokenizerId, IChunkBackend backend)`; the old overloads mean `CpuChunkBackend`. Lookups key on `backend.Tag`; an entry whose
  `Backend` differs from `backend.Tag` is rejected and re-encoded.

- [ ] **Step 1:** Merge both branches, resolve (`Program.cs` hand merge expected, per the Phase G Task 1 report), build, run
  `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit --filter "FullyQualifiedName~ChunkReuse"`; record counts and the
  merge commit in the report.
- [ ] **Step 2: Write failing tests:** un-skip `TODO_StoreHeader_PersistsBackendTag` as
  `StoreHeader_PersistsBackendTag` (put a `"vulkan"` entry, read it with a new store instance, `Backend == "vulkan"`);
  `Store_FormatV1File_IsMiss` (golden v1 bytes); `Store_HeaderBackendTampered_IsMiss`; `StoredAssembly_EntryBackendDiffers_IsRejectedAndReencoded`;
  `StoredAssembly_DefaultCtor_KeysOnCpu` (golden key unchanged for CPU).
- [ ] **Step 3:** Run the filter; expected FAIL.
- [ ] **Step 4:** Implement the header field and the backend-aware assembler.
- [ ] **Step 5:** Rerun; PASS; mutants: header writes but never checks the tag; assembler keys on `"cpu"` regardless; v1
  accepted.
- [ ] **Step 6 [GPU-lock]:** Add and run `StoredAssembly_Vulkan_CpuEntryNeverHits` (GPU-gated: a store filled by the CPU
  backend gives 0 hits on the Vulkan backend for the same chunks, and the reverse). Coordinate the slot through the user.
- [ ] **Step 7:** Commit.

### Task 2: Namespace in `ChunkKey` (L8) [CPU]

**Files:**
- Modify (dotLLM): `src/DotLLM.ChunkReuse/Store/ChunkKey.cs`, `StoredContextAssembler.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkStoreTests.cs`

**Interfaces:**
- Produces: `ChunkKey.Create(..., ChunkPositioning positioning, string @namespace = ChunkNamespace.Default)`, key scheme
  `chunk-key/v4`; `public static class ChunkNamespace { public const string Default = ""; public static string ForApiKey(string
  apiKey); }` (`ForApiKey` = `"k-"` + first 16 hex of SHA-256 of the key). `StoredContextAssembler.Assemble(..., string
  @namespace = ChunkNamespace.Default)`. The index producer identity (`keyOf([])`) therefore includes the namespace.

- [ ] **Step 1: Write failing tests:** `Key_DiffersByNamespace`; `Key_DefaultNamespace_GoldenV4` (new golden hex; v3 golden
  no longer matches); `ForApiKey_IsStable_AndNeverEqualsDefault`; `Assemble_OtherNamespace_AllMisses`;
  `Index_SavedUnderOtherNamespace_LoadsEmptyWithNote`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement; bump the scheme string; document in `experiments/store/README.md` that v3 stores are rebuilt.
- [ ] **Step 4:** Rerun; PASS; mutants: namespace not hashed; default namespace hashed as null-skip collapsing to v3.
- [ ] **Step 5:** Commit both repos.

### Task 3: Server ledger and ownership-aware orphans (L2) [CPU]

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Store/ServerLedger.cs`
- Modify (dotLLM): `src/DotLLM.ChunkReuse/Store/ChunkIndex.cs` (`ReferencedKeysUnder`, `StoreWideOrphans`)
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ServerLedgerTests.cs`

**Interfaces:**
- Produces:
  ```csharp
  public sealed record LedgerRow(string KeyHex, string Namespace, string? SourcePath, long Bytes,
                                 DateTimeOffset FirstSeen, DateTimeOffset LastUsed);
  public sealed class ServerLedger
  {
      public static string DefaultPath(string storeRoot);          // <storeRoot>/ledger-server.json
      public static ServerLedger Load(string storeRoot);           // missing = empty; unreadable throws LedgerUnreadableException
      public void Record(ChunkKey key, string ns, string? sourcePath, long bytes, DateTimeOffset now);
      public void Touch(ChunkKey key, DateTimeOffset now);
      public bool Remove(ChunkKey key);
      public IReadOnlyCollection<LedgerRow> Rows { get; }
      public IEnumerable<LedgerRow> LeastRecentlyUsed();           // ascending LastUsed, then KeyHex
      public IEnumerable<LedgerRow> UnderPath(string glob);         // PathGlob semantics, ChunkIndex.PathComparer
      public IEnumerable<LedgerRow> InNamespace(string ns);
      public void Save();                                           // temp file + rename, under the store lock (Task 4)
  }
  ```
  `ChunkIndex.ReferencedKeysUnder(storeRoot, exceptPath)` adds ledger keys; `StoreWideOrphans` = store keys minus index keys
  minus ledger keys, and throws `LedgerUnreadableException` when the ledger exists but cannot be read.

- [ ] **Step 1: Write failing tests:** `StoreWideOrphans_KeepsLedgerKeys`; `StoreWideOrphans_UnreadableLedger_ThrowsAndDeletesNothing`
  (Review Focus); `Ledger_RoundTrip`; `Ledger_RowWithoutStoreFile_DroppedOnLoad`; `Ledger_LruOrder_Deterministic`;
  `Ledger_UnderPath_UsesGlobAndPathComparer`; `Ledger_SaveIsAtomic` (truncated temp left behind does not replace the file).
- [ ] **Step 2:** Run `--filter ServerLedgerTests`; expected FAIL.
- [ ] **Step 3:** Implement with a source-generated `JsonSerializerContext`, as `ChunkIndex` does.
- [ ] **Step 4:** Rerun; PASS; mutants: orphans ignore the ledger; unreadable ledger treated as empty; LRU by FirstSeen.
- [ ] **Step 5:** Commit.

### Task 4: Lock model (L3) [CPU]

**Files:**
- Modify (dotLLM): `src/DotLLM.ChunkReuse/Store/ChunkIndex.cs`, `FileChunkStore.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/StoreLockTests.cs`

**Interfaces:**
- Produces: `ChunkIndex.AcquireIndexLock(string storeRoot, string chunkerName, TimeSpan timeout) -> IDisposable`
  (`index-<chunker>.lock`); `AcquireStoreLock` (existing) is now documented and used for short scopes only: one `Put` batch,
  one ledger or index save, one eviction pass. `ChunkStoreLockTimeoutException` (derives from `ChunkStoreBusyException`) on
  timeout. The remarks at `ChunkIndex.cs:284-289` change to the new contract.

- [ ] **Step 1: Write failing tests:** `IndexOnlyUpdate_DoesNotNeedStoreLock` (store lock held by another handle; index update
  plus save succeed); `SameChunkerIndexUpdates_Serialise` (second acquirer times out); `DifferentChunkers_DoNotBlock`;
  `EvictionPass_HoldsStoreLock_PutTimesOut`; `StoreLock_ReleasedOnDispose_EvenAfterException`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement (exclusive `FileShare.None` lock files, as `AcquireStoreLock`).
- [ ] **Step 4:** Rerun; PASS; mutants: index lock is the store lock; lock not released on exception; shared lock mode.
- [ ] **Step 5:** Commit.

### Task 5: Wire-eligible chunking (L6) [CPU; may run beside Tasks 2–4]

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Corpus/WireChunking.cs`
- Modify (dotLLM): `Corpus/Chunk.cs`, `Corpus/SymbolChunker.cs`, `Store/ChunkRef.cs` (+ its JSON context)
- Rename (dotLLM): `Corpus/TextFirstFixedChunker.cs` → `Corpus/LinesChunker.cs` (class `LinesChunker`, `Name =>
  $"lines-{MaxChunkTokens}"`), its tests, and the lab's `e4 --chunker fixed-text` → `--chunker lines`. The class arrived as
  `TextFirstFixedChunker` / `fixed-text-512` from `feature/chunk-kv-reuse` (`8560d36a`) via Task 1; E4c's artifacts keep the
  old label and its README gets a one-line note that `fixed-text-512` = `lines-512`.
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/WireChunkingTests.cs`

**Interfaces:**
- Produces: `Chunk.WireEligible` and `ChunkRef.WireEligible` (`bool`, default `true`, serialised; old index files load as
  `true` only for `symbol-*` chunks that are not token slices, else re-chunked). `SymbolChunker` sets `false` on the token-slice
  pieces of an over-long single line.
  ```csharp
  public static class WireChunking
  {
      public static IReadOnlySet<string> Eligible { get; }          // {"symbol-512"}
      public static IReadOnlySet<string> PendingE4c { get; }        // {"lines-512"}; moves to Eligible in Task 19
      public static bool IsWireChunker(string chunkerName);         // Eligible.Contains
      public static string Hash(string text);                       // "sha256:" + lowercase hex of UTF-8
      public static RoundTripReport VerifyRoundTrip(IReadOnlyList<Chunk> chunks, ITokenizer tokenizer);
  }
  public sealed record RoundTripReport(int Checked, int Failed, IReadOnlyList<string> FailedIds);
  ```
  `VerifyRoundTrip` checks `ChunkTokenization.Encode(text) == ids` per chunk (Task 5b); failures are marked not wire-eligible by `build` (Task 17).

- [ ] **Step 1: Write failing tests:** `SymbolChunker_OverlongLineSlices_NotWireEligible`; `SymbolChunker_NormalChunks_WireEligible`;
  `VerifyRoundTrip_IdSlicedFixedChunk_FailsAtMultibyteCut` (`FixedSizeChunker` on a fixture whose cut falls inside `é`);
  `VerifyRoundTrip_Lines512_AllPass`; `Hash_MatchesFixtures` (Task 0 `inline.json`, `nonascii-crlf.json`);
  `Lines512_IsPendingNotEligible`; `ChunkRef_Json_RoundTripsWireEligible`; `LinesChunker_Name_IsLines512` and
  `ChunkRef_KindOf_Lines_IsFixed` (`ChunkRef.KindOf` throws on unknown prefixes today, so `lines-*` must map to
  `ChunkKind.Fixed`).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: slices left eligible; hash over UTF-16; round trip compares lengths only.
- [ ] **Step 5:** Merge into `feature/chunk-cache` if run in `chunk-wire`; rerun the ChunkReuse suite; commit.

### Task 5b: Chunk encoding matches the chat path (ruling 21) [CPU]

Task 9 found that `EncodeRaw` **parses** special-token spellings (F9) while the chat path does not (F7: the template marks
them with U+FDD0, #1339, and encode strips the mark). So a chunk containing `<think>` or `<|im_start|>` gets different ids
from the chunkers than from a chat request. Ruling 21: chunk text is tokenised as `EncodeRaw(MarkUntrustedSpecials(text))`
everywhere: chunkers, `ChunkEncoder`, `VerifyRoundTrip`, the server wire and encode paths (Tasks 13, 15), and CLI / prewarm
(Task 17).

**Files:**
- Create (dotLLM): `src/DotLLM.ChunkReuse/Corpus/ChunkTokenization.cs`
- Modify (dotLLM): `Corpus/SymbolChunker.cs` (the `EncodeRaw` calls at `:180,209,239`), `Corpus/LinesChunker.cs`,
  `Corpus/WireChunking.cs` (`VerifyRoundTrip`), `ChunkEncoder.cs` if it tokenises text; if `MarkUntrustedSpecials` is not
  public (`JinjaChatTemplate.cs:99,190`), reach it through the existing `InternalsVisibleTo` (C1) rather than copying it
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkTokenizationTests.cs`

**Interfaces:**
- Produces: `public static class ChunkTokenization { public static int[] Encode(ITokenizer tokenizer, string chunkText); }`
  = `EncodeRaw(MarkUntrustedSpecials(chunkText))`; the only way library code turns chunk text into ids.

- [ ] **Step 1: Write failing tests:** `ChunkWithThinkTag_StoreAndChatPathIdsEqual` (golden, Qwen3 tokenizer fixture: ids from
  `ChunkTokenization.Encode` equal the ids the chat path produces for the same text inside a rendered user message);
  `PlainChunk_IdsUnchanged` (no special spellings: identical to the old `EncodeRaw`, so existing entries stay valid);
  `SymbolChunker_UsesChunkTokenization`; `LinesChunker_UsesChunkTokenization`; `VerifyRoundTrip_SpecialSpellingChunk_Passes`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement; route every library tokenisation of chunk text through `ChunkTokenization.Encode`.
- [ ] **Step 4:** Rerun; PASS; mutants: unmarked `EncodeRaw`; marking applied twice; one chunker left on `EncodeRaw`.
- [ ] **Step 5:** **Versioning note.** Token ids are in `ChunkKey`, so a chunk whose ids change gets a new key by itself (a
  miss, never a wrong hit), and `KvOutputVersion` is unchanged (K/V for given ids is unchanged). Stored indexes, however,
  hold the old `KeyHex` for such chunks: if this task lands after Task 2's `chunk-key/v4` has been used for a persisted store,
  bump the index format version so old indexes re-chunk; if before, v4 covers it and no extra bump is needed. Record which
  in the report; commit; write the issue draft.

### Task 6: Client core: types, hashing, control-plane client [CPU; separate package, blocks nothing in Lane S]

Pure HTTP plus DTOs: the wire DTOs are the client's own copies (checked against Task 0 fixtures), with no project reference
to any GPL dotLLM project.

**Files:**
- Create (dotLLM, `chunk-client`): `src/DotLLM.ChunkCache.Client/DotLLM.ChunkCache.Client.csproj` (net8.0 + net10.0,
  `PackageLicenseExpression` MIT override, references only `Microsoft.Extensions.AI.Abstractions` and BCL),
  `Contracts.cs` (§8.2 records), `ChunkHash.cs`, `ChunkCacheHttpClient.cs`, `Wire/ChunkCacheJsonContext.cs`
- Test: `tests/DotLLM.ChunkCache.Client.Tests/` (own project, no `DotLLM.*` engine reference)

**Interfaces:**
- Produces: §8.2 verbatim: `ChunkSpan`, `ChunkSourceInfo`, `IChunkSource`, `ChunkedText`, `LineRange`, `IInvalidationSignal`,
  `ChunkInvalidation`, `InvalidationKind`, `IRecomputePolicy`, `ChunkRequestContext`, `ChunkRequestOptions` (defaults
  `Policy = "exact"`, `OnMiss = "prefill"`, `Report = "summary"`), `IChunkCacheClient`; plus `ExactPolicy : IRecomputePolicy`
  (always returns defaults), `ChunkHash.Of(string text) -> string`, `ChunkCacheCapabilities` (§5.9 fields),
  `SelectRequest/Result`, `PrewarmRequest/Result`, `StatusRequest/Result`, `EvictRequest/Result`, `ExplainResult` (§7.2
  schemas, snake_case JSON). `ChunkCacheHttpClient(HttpClient http, Uri baseUrl, string? apiKey) : IChunkCacheClient`:
  `GetCapabilitiesAsync` returns `null` on 404 and on a body without `versions` containing 1. The server has no select /
  status endpoints (they are local index operations), so `ChunkCacheHttpClient` takes an `IChunkIndexQueries` for them:
  `interface IChunkIndexQueries { ValueTask<SelectResult> SelectAsync(SelectRequest r, CancellationToken ct);
  ValueTask<StatusResult> StatusAsync(StatusRequest r, CancellationToken ct); }`, implemented by
  `CliChunkIndexQueries(string executable = "chunkcache", IProcessRunner? runner = null)`, which runs
  `<exe> select|status --json ...` and parses stdout (the §7.2 output schemas that Task 17 prints).

- [ ] **Step 1: Write failing tests:** `Hash_MatchesFixtures`; `Capabilities_404_IsNull`; `Capabilities_ParsesFixture`;
  `Capabilities_UnknownVersionOnly_IsNull`; `Prewarm_SendsTextNeverHashesOnly`; `ExactPolicy_AlwaysExact`;
  `Package_HasNoDotLlmEngineReference` (reflects over referenced assemblies); `ApiKey_SentAsXApiKey`;
  `CliQueries_PassesArgsAndParsesJson` and `CliQueries_NonZeroExit_ThrowsWithStderr` (fake `IProcessRunner`).
- [ ] **Step 2:** Run `dotnet test tests/DotLLM.ChunkCache.Client.Tests`; expected FAIL.
- [ ] **Step 3:** Implement (fake `HttpMessageHandler` in tests).
- [ ] **Step 4:** Rerun; PASS; mutants: 404 treated as capable; hash uppercase; key header missing.
- [ ] **Step 5:** Commit.

### Task 7: Index-backed chunk source [CPU; parallel with Task 8]

**Files:**
- Create (`chunk-client`): `src/DotLLM.ChunkCache.Client/IndexChunkSource.cs`, `IndexFile.cs` (read-only view of
  `index-<chunker>.json`)
- Create (here): `docs/contracts/chunk-cache-v1/index-format.md` (the index JSON fields the client reads, frozen)
- Test: `tests/DotLLM.ChunkCache.Client.Tests/IndexChunkSourceTests.cs` (fixture index JSON checked in, copied from a
  `ChunkIndex.Save` output already on `feature/chunk-cache`; the client lane depends on no Lane L or I1b task. A missing
  `wireEligible` field reads as eligible, so indexes written before Task 5 work.)

**Interfaces:**
- Produces: `IndexChunkSource(string storeRoot, string chunkerName, string sourceRoot, PathDenyList denyList) : IChunkSource`.
  `ReadAsync` reads the file, strips a BOM, normalises CRLF to LF (the store indexes LF), compares the file SHA-256 with the
  index row; if equal, returns `ChunkedText` whose spans are the index's `WireEligible` chunks wholly inside `window`
  (rounded out to chunk boundaries when the window cuts one, notes otherwise); if not equal, returns the text with no spans and
  the note `"stale vs index"`. Deny-listed paths return text with `NoStore = true` on every span and no spans annotated.
  `PathDenyList.Default` holds the Global Constraints list; `PathDenyList.IsDenied(string relativePath)`.
  The client needs no tokenizer: chunk boundaries come from the index.

- [ ] **Step 1: Write failing tests:** `UnchangedFile_SpansEqualIndexChunks`; `CrlfFile_IsNormalised_SpansStillHit`;
  `EditedFile_NoSpans_StaleNote`; `Window_CutsChunk_RoundedOutOrNoted`; `WireIneligibleChunk_NotAnnotated`;
  `DeniedPath_NoSpans` (each default deny pattern); `SpanHash_EqualsHashOfSpanText`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement; write `index-format.md` from the fields used.
- [ ] **Step 4:** Rerun; PASS; mutants: no LF normalisation; partial chunks annotated; deny-list skipped.
- [ ] **Step 5:** Commit both repos.

### Task 8: Annotating pipeline: registry, decorator, body handler [CPU; parallel with Task 7]

**Files:**
- Create (`chunk-client`): `src/DotLLM.ChunkCache.Client/ChunkSpanRegistry.cs`, `ChunkManifestScope.cs`,
  `ChunkAnnotatingChatClient.cs`, `ChunkCacheBodyHandler.cs`, `ChunkCacheReport.cs`, `SseChunkCacheScanner.cs`
- Test: `tests/DotLLM.ChunkCache.Client.Tests/PipelineTests.cs`

**Interfaces:**
- Consumes: Task 6 contracts and `ChunkHash`.
- Produces (§8.3): `ChunkSpanRegistry : IChunkSpanRegistry` (keyed by part text, bounded LRU 4,096 entries);
  `ChunkAnnotatingChatClient(IChatClient inner, IChunkSpanRegistry registry, IRecomputePolicy policy)`;
  `ChunkManifestScope.Begin(...)` over `AsyncLocal`; `ChunkCacheBodyHandler(ChunkCacheCapabilities? caps)`;
  `ChunkCacheReport.TryGet(ChatResponse, out JsonObject report)` reading `ChatResponse.AdditionalProperties["chunk_cache"]`.
  The handler writes placement B only, locates parts by re-hashing **decoded** part texts of the serialised body, drops any
  span whose hash no longer matches, converts UTF-16 to UTF-8 offsets, and leaves the body byte-identical when `caps` is null
  or no span survives. Streaming: the report is read from the final SSE chunk without buffering the stream.

- [ ] **Step 1: Write failing tests:** `Manifest_MatchesRegisteredSpans` (fixture `manifest.json`); `EscapedNonAscii_StillLocated`
  and `SurrogatePairBeforeSpan_Utf8OffsetsExact` (fixture `nonascii-crlf.json`, Review Focus); `MutatedPart_NoAnnotation`;
  `AppendedSuffix_KeepsSpan`; `StringContent_IsPartZero`; `NoCapabilities_BodyByteIdentical`; `Streaming_ReportFromFinalChunk_NoBuffering`
  (a stream whose first chunk is readable before the last is written); `Retry_ResendsSameManifest` (a retrying handler between
  decorator and body handler, which also answers spec open question 1 for a plain `HttpClient` stack);
  `Overhead_Under5ms` (100 spans, 200 KB body; median of 20).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: hash over wire bytes; UTF-16 offsets sent; mismatch keeps span; SSE fully buffered.
- [ ] **Step 5:** Commit.

### Task 9: Server pins: templates, special tokens, unknown fields (S1) [CPU] — DONE

**Status:** done on dotLLM `feature/chunk-cache-server` `38c0314b` (`ServerPinTests`, `docs/CHUNK_CACHE.md` pinned-behaviour
section); report `.superpowers/sdd/2026-11-01-phase-s/phase-i-task-9-report.md`; findings became rulings 19–22 in
`docs/contracts/chunk-cache-v1/README.md`, folded into Tasks 5b, 10, 11, 13, 15 and 17 below. The steps are kept as the record.

**Files:**
- Test (dotLLM, `chunk-server`): `tests/DotLLM.Tests.Unit/Server/ChunkCache/ServerPinTests.cs`
- Create (dotLLM): `docs/CHUNK_CACHE.md` (server-side doc; this task writes the "pinned behaviour" section)

**Interfaces:**
- Produces: characterisation facts that Tasks 10–11 rely on, each pinned by a passing test on unmodified `dev`:
  how `GgufChatTemplateFactory` templates for Qwen3 and Llama-3.1 flatten multi-part `content` (separator, trim); whether
  the plain content path parses special-token strings (e.g. `<|im_start|>` inside user text); that `chunk_cache` (top level)
  and `chunk` (on a text part) are ignored on `/v1/chat/completions` and `/v1/messages`.

- [ ] **Step 1:** Write the pin tests with the expected values left as the spec's assumptions (parts joined with no separator;
  special-token strings not parsed; fields ignored); use template text from the GGUF metadata of the HF-cache models
  (`bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF`, a Llama-3.1-8B Instruct GGUF) saved as test fixtures.
- [ ] **Step 2:** Run `--filter ServerPinTests`; record which assumptions fail.
- [ ] **Step 3:** Correct each failing expectation to the observed behaviour; write each fact and its consequence for §5.3
  items 5–6 into `docs/CHUNK_CACHE.md`; tell the controller of any fact that changes Tasks 10–11 (a ruling goes in the ledger).
- [ ] **Step 4:** Rerun; PASS; no mutants (characterisation only; the report says so).
- [ ] **Step 5:** Commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence); this one is the Lane S lead issue ("Server: chunk_cache wire convention, flag off by default").

### Task 10: Wire parsing and validation behind `--chunk-cache` (S2) [CPU]

**Files:**
- Create (dotLLM): `src/DotLLM.Server/ChunkCache/ChunkCacheWire.cs` (DTOs), `ChunkAnnotationParser.cs`,
  `ChunkCacheCodes.cs`, `ChunkCacheOptions.cs`
- Modify (dotLLM): `Models/ChatCompletionRequest.cs`, `Models/AnthropicMessagesModels.cs` (raw `chunk_cache` /
  `chunk` as `JsonElement?`), `ServerJsonContext.cs`, `ServerOptions.cs` (`--chunk-cache`, `--chunk-cache-max-chunks` 4096)
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/ChunkAnnotationParserTests.cs`

**Interfaces:**
- Produces:
  ```csharp
  public enum ChunkPolicy { Exact, Shadow, Balanced, Fast, Auto }
  public sealed record ChunkSpanRef(int Message, int Part, int StartByte, int EndByte, string Id, string Hash,
                                    string? Chunker, bool Volatile, bool NoStore, string Text);
  public sealed record ChunkWarning(string Code, int Count);
  public sealed record ParsedChunkRequest(ChunkPolicy Requested, IReadOnlyList<ChunkSpanRef> Spans, string? QueryText,
      bool Strict, string Report, string Namespace, IReadOnlyList<ChunkWarning> Warnings, ChunkCacheError? Error);
  public sealed record ChunkCacheError(int Status, string Type, string Code, string Message);
  public static class ChunkAnnotationParser
  {
      public static ParsedChunkRequest? Parse(ChatCompletionRequest request, ChunkCacheOptions options, string ns);
      public static ParsedChunkRequest? Parse(MessagesRequest request, ChunkCacheOptions options, string ns);
  }   // null = no annotations or flag off
  ```
  **Surfaces (ruling 19).** OpenAI `/v1/chat/completions`: spans address **string** `content` only, through the manifest
  (`chunk_cache.chunks[]`, `at = {message, part: 0, start, end}`); array-of-parts content stays the existing 400 even with
  the flag on (general array support is a separate later issue). Anthropic `/v1/messages`: inline `chunk` on text blocks and
  the manifest. `ChunkSpanRef.Part` is the wire part index; the parser also produces
  `EngineSpan(int EngineMessage, int StartChar, int EndChar)` by mapping through `AnthropicConverter`: text blocks of one
  message are joined with `'
'` (offsets shift by the preceding blocks plus separators), and `tool_result` blocks are split
  into their own engine `tool` messages; a span in a block the converter does not carry as text is `chunk_span_invalid`.
  `ChunkCacheCodes` holds the §5.8 code strings. Validation: version, hash recomputed over the decoded text, spans on UTF-8
  boundaries / in range / non-overlapping / text parts only, manifest conflict, too many, `chunk_not_wire_eligible`
  (`WireChunking.IsWireChunker` semantics, copied as a server constant list until the server references `DotLLM.ChunkReuse` in
  Task 15). Non-strict: warning and the span is dropped. Strict: `Error` set with the §5.8 status. `balanced` / `fast` /
  `auto` parse to their enum values; Task 13 degrades them.

- [ ] **Step 1: Write failing tests:** one data-driven test over Task 0's `expected.json` (every fixture → warnings or strict
  code and status); `FlagOff_ReturnsNull_EvenWithAnnotations`; `HashOverDecodedString` (escaped `\u00e9` fixture);
  `IdLongerThan256_Rejected`; `TooMany_Warns_StrictIs400`; `UnknownChunker_NotWireEligibleWarning`; `QueryDefaultsToLastUserMessage`;
  `OpenAi_StringContentManifest_Parsed`; `OpenAi_ArrayContent_StillThe400_FlagOnAndOff`; `OpenAi_InlineChunkField_Ignored`;
  `Anthropic_TwoTextBlocks_SecondBlockSpanShiftedByFirstPlusNewline`; `Anthropic_ToolResultBlock_MapsToOwnEngineMessage`;
  `Anthropic_MappedSpan_SubstringOfEngineMessageEqualsSpanText` (property test over random block layouts).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: offsets as chars; overlap allowed; conflict served annotated; 422 status; join
  separator dropped; tool_result offset not reset.
- [ ] **Step 5:** Commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence).

### Task 11: Span location in the rendered prompt (S2/S3) [CPU]

**Files:**
- Create (dotLLM): `src/DotLLM.Server/ChunkCache/ChunkSpanLocator.cs`
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/ChunkSpanLocatorTests.cs`

**Interfaces:**
- Consumes: Task 9 pinned facts, Task 10 `ChunkSpanRef`.
- Produces: `ChunkSpanLocator.Locate(IChatTemplate template, IReadOnlyList<ChatMessage> messages,
  IReadOnlyList<ChunkSpanRef> spans) -> LocatedSpans(IReadOnlyList<LocatedSpan> Located, IReadOnlyList<ChunkWarning> Warnings)`,
  `LocatedSpan(ChunkSpanRef Span, int RenderedStartChar, int RenderedEndChar)`. Sentinel rendering: render once unannotated
  (R) and once with each span replaced by a sentinel that cannot occur in the input (a fresh GUID per request in a private-use
  code point frame); a span is located only if its sentinel is intact and substituting the span texts back into the sentinel
  render yields R exactly; otherwise `chunk_template_altered` and the span is ignored (ruling 20). The comparison is against
  the **marked** span text (`MarkUntrustedSpecials`, which inserts U+FDD0 into special-token spellings, #1339), or U+FDD0 is
  stripped from both sides; the sentinel is a fixed private-use frame that is not a special spelling. A caller-supplied
  U+FDD0 inside a span is dropped at encode (Task 9 F10), so such a span is ignored. Facts pinned by Task 9: on Llama-3.1 the
  template trims user / assistant / system content and JSON-encodes tool content, so **tool-result spans are never reusable on
  Llama-3.1 in v1**; Qwen3 keeps content verbatim. `chunk_special_tokens` is not needed: the chat path never parses special
  spellings in caller text.

- [ ] **Step 1: Write failing tests:** `Qwen3_MidPartSpan_Located`; `Llama31_SpanAtPartEdge_TrimmedIsTemplateAltered`;
  `Llama31_SpanAfterGlueEndingNewline_Located`; `TwoSpansSamePart_BothLocated`; `SentinelInUserText_CannotCollide`;
  `RenderedOffsets_SubstringEqualsSpanText`; `SpecialSpellingSpan_LocatedViaMarkedText` (`<think>` inside a Qwen3 span);
  `CallerFdd0InSpan_Ignored`; `Llama31_ToolResultSpan_AlwaysTemplateAltered`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: skip the R comparison; compare unmarked text; offsets off by the BOS prefix.
- [ ] **Step 5:** Commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence).

### Task 12: Snapshot lineage (L7) [CPU; parallel with Tasks 10–11]

**Files:**
- Modify (dotLLM, worktree `chunk-server-lineage` off `feature/chunk-cache-server`): `src/DotLLM.Engine/PromptCache/PrefixCacheEntry.cs`,
  `PrefixCache.cs`, `PrefixTrieManager.cs` (exact members located at task start)
- Test: `tests/DotLLM.Tests.Unit/Engine/PrefixLineageTests.cs`

**Interfaces:**
- Produces: `PrefixCacheEntry.FirstApproxRow` (`int?`; `null` = all rows exact). A lookup gains `bool allowApprox`
  (default `false`): without it, a match is capped at `FirstApproxRow`. `cached_tokens` / `cache_n` count rows below
  `FirstApproxRow` only; approximate restored rows are returned separately as `ApproxRowsReused` for
  `chunk_cache.tokens.prefix_reused_approx`. Nothing in I1a creates approximate rows; the tests create them directly.

- [ ] **Step 1: Write failing tests:** `ExactLookup_StopsAtFirstApproxRow`; `ApproxAllowed_RestoresFullMatch`;
  `CachedTokens_CountExactRowsOnly`; `NoApproxRows_BehaviourUnchanged` (existing prefix tests untouched and green);
  `Eviction_PreservesLineageTag`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement additively (no change for entries without the tag); the dotLLM session reviews this diff before
  merge into the server branch (it owns the prefix cache).
- [ ] **Step 4:** Rerun plus the existing PromptCache suite; PASS; mutants: cap ignored; approx rows counted in `cache_n`.
- [ ] **Step 5:** Merge into `feature/chunk-cache-server`; commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence) (its own issue, prefix cache).

### Task 13: `exact` / `shadow` execution and response metadata (S5) [CPU]

**Files:**
- Create (dotLLM): `src/DotLLM.Server/ChunkCache/ChunkCachePipeline.cs`, `ChunkCacheReport.cs`, `ChunkCostModel.cs`,
  `chunk-cost-model.json` (embedded default)
- Modify (dotLLM): `Endpoints/ChatCompletionEndpoint.cs`, `Endpoints/MessagesEndpoint.cs`, `Models/ChatCompletionResponse.cs`,
  `Models/ChatCompletionChunk.cs`, `Endpoints/MetricsEndpoint.cs`
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/ChunkCachePipelineTests.cs`, `tests/DotLLM.Tests.Integration/ChunkCacheExactNeutralityTests.cs`

**Interfaces:**
- Consumes: Tasks 10–12; `IChunkStore.Contains` and `ChunkKey.Create` from Lane L (Tasks 1–2 merged into the server branch:
  the server project gains a reference to `DotLLM.ChunkReuse`).
- Produces: `ChunkCachePipeline.Apply(ParsedChunkRequest, LocatedSpans, ServerModelIdentity) -> ChunkCachePlan`; the
  response object of §5.9 (`policy_requested`, `policy_applied`, `reason`, `chunks{annotated,prefix,hit,miss,ignored}`,
  `tokens{...}`, `warnings`) in blocking responses, the final streaming chunk, and the Anthropic `message_delta`. `shadow` adds
  `plan` with predicted hits / misses / rows and `timings_ms.full_prefill_estimate` and `predicted_reuse` from
  `ChunkCostModel(backend) { double UsPerRowKey; double AssemblyMsPerKTokens; double PrefillTokensPerSec }` (defaults: Vulkan
  13–19 µs → 16 µs, from G2; CPU from E1). Applied policy is always `exact`; `balanced` / `fast` / `auto` report
  `chunk_policy_unavailable` as reason. `timings.chunk_n` and `chunk_recomputed_n` are present and 0. `/metrics` gains
  `dotllm_chunk_cache_chunks_total{status}` and `dotllm_chunk_cache_tokens_total{kind}`. `ServerModelIdentity` = content
  model id (`GgufIdentity.ModelId`), tokenizer id, backend tag, KV dtype; recurrent / hybrid models give
  `chunk_model_unsupported`.

- [ ] **Step 1: Write failing tests:** `Shadow_PlanCountsHitsAndMisses` (store pre-filled for half the spans via the CPU
  backend); `Report_PartitionHolds` (Task 0 response fixtures as golden shapes); `Balanced_DegradesToExact_WithReason`;
  `Exact_IsBitIdenticalToUnannotated` and `Exact_AfterShadow_SameSlot_Identical` (integration, synthetic tiny model, blocking
  and streaming, tokens and `cached_tokens` equal; Review Focus); `StreamingFinalChunk_CarriesReport`;
  `AnthropicMessageDelta_CarriesReport`; `CachedTokens_UnchangedByAnnotations`; `RecurrentModel_ModelUnsupported`;
  `Metrics_CountersIncrement`; `ShadowKey_ChunkWithThinkTag_HitsStoreEntryFromCli` (ruling 21);
  `Exact_WithApproxSnapshotOnSlot_RestoresExactRowsOnly` (approximate entry injected as in
  Task 12; output equals the unannotated request); `ShortChunk_IgnoredTooShortWarning` (`min_chunk_tokens` 32, counted with
  the server tokenizer).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement; `exact` and `shadow` tokenise the whole rendered prompt exactly as a plain request (§5.3 item 7);
  shadow keys come from `ChunkTokenization.Encode(span text)` (Task 5b), and spans come from Task 10's engine mapping.
- [ ] **Step 4:** Rerun; PASS; mutants: shadow uses segmented tokenisation; report omitted from the stream; misses counted
  in `chunk_reused`.
- [ ] **Step 5:** Commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence).

### Task 14: Capabilities, explain, auth (S6) [CPU]

**Files:**
- Create (dotLLM): `src/DotLLM.Server/Endpoints/ChunkCacheEndpoint.cs`, `src/DotLLM.Server/ChunkCache/ChunkCacheAuth.cs`
- Modify (dotLLM): `EndpointExtensions.cs`, `ServerOptions.cs` (`--chunk-cache-api-keys <file>`), `RateLimiting/RateLimitMiddleware.cs`
  (chunk-cache endpoints are metered)
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/ChunkCacheEndpointTests.cs`

**Interfaces:**
- Produces: `GET /v1/chunk-cache` (§5.9 capabilities; `selectors: ["chunk_starts"]`, `wire_chunkers: ["symbol-512"]`,
  `auto_validated: []`, store figures 0 until Task 15); `POST /v1/chunk-cache/explain` (§7.2 schema; same codes; per-chunk
  status only for an authenticated caller in its own namespace, else counts). Flag off: both 404.
  **Auth (dotLLM has no authentication today, `SERVER.md` § Security):** `ChunkCacheAuth.Resolve(HttpContext) ->
  ChunkCaller(bool Authenticated, string Namespace)`. With `--chunk-cache-api-keys` set: `X-API-Key` / `Bearer` must be in
  the file (constant-time compare), else 401 `authentication_error`; namespace = `ChunkNamespace.ForApiKey(key)`. Unset:
  loopback callers only (403 otherwise), namespace `ChunkNamespace.Default`, `Authenticated = true`. The same rule gates
  store side effects of annotated inference requests (Task 15). Approved by the user (2026-11-02). Default OFF (the whole surface sits behind `--chunk-cache`); the issue is flagged security-sensitive.

- [ ] **Step 1: Write failing tests:** `Capabilities_MatchesFixtureShape`; `FlagOff_404`; `NoKeysConfigured_NonLoopback_403`;
  `KeysConfigured_MissingKey_401`; `KeysConfigured_ValidKey_NamespaceFromKey`; `TwoKeys_CannotSeeOrEvictEachOthersEntries`
  (key → namespace isolation across explain, shadow plan counts and evict; mutants: shared namespace, key ignored);
  `EnabledWithoutKeys_LoopbackOnly`; `Explain_PerChunkOnlyForOwnNamespace`;
  `Explain_HashListBody_Rejected`; `Endpoints_AreRateLimited`; `ReportPerChunk_UnauthenticatedGetsSummary` (inference
  response with `report: per_chunk`).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: loopback check skipped; per-chunk leaked to anonymous; key compare not exact.
- [ ] **Step 5:** Commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence). **G-I1 (with Tasks 6–8): stop and report.**

### Task 15: Sole-writer encode, admission and disk budget (I1b) [CPU + one GPU-lock step]

**Files:**
- Merge Lane L Tasks 3–5 into `feature/chunk-cache-server`
- Create (dotLLM): `src/DotLLM.Server/ChunkCache/ChunkEncodeQueue.cs`, `SightingTable.cs`, `ChunkStoreService.cs`
- Modify (dotLLM): `ServerOptions.cs` (`--chunk-store <dir>`, `--chunk-store-budget <bytes>` required when `--chunk-store`
  is set, `--chunk-store-index-only`)
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/ChunkStoreServiceTests.cs`

**Interfaces:**
- Consumes: `ServerLedger`, `ChunkNamespace`, lock model, `IChunkBackend` of the loaded model, `ChunkEncoder`.
- Produces: `ChunkStoreService` (singleton; opens the store, takes ownership; a second server on the same root fails at
  startup with a clear message) with `Admit(ChunkSpanRef span, ChunkCaller caller) -> AdmissionResult(bool Queued, string?
  Reason)` implementing §5.10 exactly (not `volatile`, not `no_store`, seen in ≥ 2 requests per `(namespace, text hash)`,
  under budget, index-only rule); `SightingTable` (bounded 100,000 rows, LRU; rows carry optional `source.path`);
  `ChunkEncodeQueue` runs only while the scheduler is idle, tokenises with `ChunkTokenization.Encode` (Task 5b), encodes with the server's backend, `Put`s under the short store
  lock, records ledger rows, and runs LRU eviction of ledger rows to the budget; when eviction cannot free space, encoding stops
  and responses carry `chunk_store_unavailable` as a warning. Warnings `chunk_encode_queued` / `chunk_encode_skipped`.
  `on_miss: "encode"` is accepted in I1 as "queue now, bypassing only the seen-twice rule" (the request itself is still served
  `exact`; encode-then-assemble needs I5).

- [ ] **Step 1: Write failing tests:** `SeenOnce_NotQueued_SeenTwice_Queued`; `VolatileAndNoStore_NeverQueued`;
  `BudgetRequired_StartupFailsWithoutIt`; `OverBudget_EvictsLruLedgerRows_NeverIndexOnlyEntries`;
  `CannotFree_StopsEncoding_Warns`; `EncodesOnlyWhenIdle` (fake scheduler); `CrashMidPut_NoLoadableEntry_LedgerConsistentOnReload`
  and `DiskFull_PutFails_IsMissAndWarning` (Review Focus); `SecondServerSameRoot_FailsFast`; `IndexOnly_AdHocTextNeverStored`;
  `EntriesTaggedWithServerBackend`; `OnMissEncode_QueuesFirstSighting_ServesExact`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: seen-once admitted; eviction ignores the budget; ledger written before the file.
- [ ] **Step 5 [GPU-lock]:** `VulkanServer_CpuWrittenStore_NoHits` (GPU-gated integration: a store encoded by a CPU server
  gives `hit: 0` in `shadow` on a Vulkan server for the same request). Coordinate the slot through the user.
- [ ] **Step 6:** Commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence).

### Task 16: Prewarm, evict and forget, namespaces (I1b) [CPU]

**Files:**
- Modify (dotLLM): `Endpoints/ChunkCacheEndpoint.cs`, `ChunkCache/ChunkStoreService.cs`
- Test: `tests/DotLLM.Tests.Unit/Server/ChunkCache/ChunkCacheWriteEndpointTests.cs`

**Interfaces:**
- Produces: `POST /v1/chunk-cache/prewarm` (§7.2: text only; bypasses only the seen-twice rule; deny-list applied when
  `source.path` is given; returns `requested, already_stored, queued, queued_tokens, refused, refused_reasons`) and
  `POST /v1/chunk-cache/evict` (`mode: orphans | path | namespace | all`, `dry_run` default `true`; `path` removes K/V,
  ledger rows, the index references the server owns and sighting rows with that provenance; `namespace` / `all` remove all
  four kinds for the caller's namespace, `all` across namespaces only for a key listed as admin in the keys file). Capabilities
  now report `store.entries`, `bytes`, `budget_bytes`, `dtype`.

- [ ] **Step 1: Write failing tests:** `Prewarm_TextOnly_QueuesWithoutSightings`; `Prewarm_DeniedPath_Refused`;
  `Evict_DryRunDefault_DeletesNothing`; `Evict_Orphans_KeepsLedgerAndIndexKeys`; `Evict_Path_ForgetsAllFourKinds`;
  `Evict_Namespace_CannotTouchOtherNamespace`; `Evict_UnreadableLedger_FailsClosed`; `Capabilities_ReportsStoreFigures`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: dry run ignored; cross-namespace evict; sightings kept on forget.
- [ ] **Step 5:** Commit; write the issue draft `docs/release/chunk-cache-issues/NN-<slug>.md` (title, body, acceptance criteria from the Global Constraints, mutant evidence).

### Task 17: CLI revision: `--json`, deny-list, wire eligibility, server-backed writes (L1, I3) [CPU]

**Files:**
- Merge `feature/chunk-cache-client` into `feature/chunk-cache` (the CLI uses `ChunkCacheHttpClient`)
- Modify (dotLLM): `tools/DotLLM.ChunkCache/{BuildCommand,SelectCommand,StatusCommand,EvictCommand,CliArgs,Common}.cs`;
  create `PrewarmCommand.cs`, `ExplainCommand.cs`, `JsonOutput.cs`
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkCacheCliTests.cs`

**Interfaces:**
- Consumes: Tasks 3–6, Task 16 endpoint contract (tests use a fake `HttpMessageHandler` with Task 0-style fixtures; no
  running server needed).
- Produces: every verb accepts `--json` and prints exactly the §7.2 output object (snake_case) on stdout, diagnostics on stderr.
  `build` deny-lists paths, marks `VerifyRoundTrip` failures and token-slice pieces wire-ineligible
  (`wire_ineligible_chunks`), refuses non-wire chunkers unless `--lab`, and with `--encode` calls `prewarm` on `--server`.
  `evict` and `prewarm` require `--server`; `--offline` lets `build --encode` and `evict` write directly while holding the
  store lock, and fails if a server ledger shows a live owner (lock held). `select` returns `hash` = `WireChunking.Hash` of the
  LF text and, when `--server` is given, `stored` from posting the selected texts as one `explain` request (text only; no
  hash lookup exists; body `{"request": ...}` per ruling 15, the texts in an OpenAI string-content message per ruling 19).
  All chunk text is tokenised with `ChunkTokenization.Encode` (Task 5b). `explain` posts a request file.
  `compare` stays lab-only, not in MCP.

- [ ] **Step 1: Write failing tests:** `EachVerb_Json_MatchesSchema` (schemas from §7.2 as JSON Schema files under
  `tests/.../Fixtures/v1/schemas/`); `Build_DeniedFiles_CountedNotChunked`; `Build_Lines512_IsPendingE4c_RefusedWithoutLab`;
  `Build_Encode_CallsPrewarm_NeverPut`; `Evict_WithoutServerOrOffline_Exit2`; `Offline_SecondWriter_ExitsNonZeroWithinTimeout`
  (Review Focus); `Select_HashEqualsWireHash`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun; PASS; mutants: build `--encode` writes locally; deny-list skipped; JSON field renamed.
- [ ] **Step 5:** Re-run the Phase S demo (`experiments/chunkcache-demo/README.md`) with `--json` and a CPU server under
  `--chunk-store`; record build time, wire-ineligible counts, store size; commit both repos.

### Task 18: Thin MCP server (`chunkcache mcp`) [CPU]

**Files:**
- Create (dotLLM): `tools/DotLLM.ChunkCache/McpCommand.cs`, `McpTools.cs`
- Modify (dotLLM): `tools/DotLLM.ChunkCache/DotLLM.ChunkCache.csproj` (the MCP SDK package chosen in Step 0, pinned in
  `Directory.Packages.props`)
- Create (here): `docs/release/mcp-sdk-choice.md` (Step 0 findings)
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/ChunkCacheMcpTests.cs`

**Interfaces:**
- Produces: `chunkcache mcp [--store DIR] [--server URL]` runs a stdio MCP server with tools `chunkcache_build`,
  `chunkcache_select`, `chunkcache_status`, `chunkcache_evict`, `chunkcache_prewarm`, `chunkcache_explain`, each with
  `inputSchema` and `outputSchema` from §7.2, returning `structuredContent` plus a serialised text copy. Each tool runs the
  same verb handler as `chunkcache <verb> --json`; nothing else (thin wrapper). `dry_run` defaults to `true` for evict.

- [ ] **Step 0 (spike, decide the package):** the official SDK (`modelcontextprotocol/csharp-sdk`) ships
  `ModelContextProtocol.Core` (client and low-level server APIs, minimal dependencies), `ModelContextProtocol` (Core plus
  hosting / DI and attribute-based tool discovery; depends on `Microsoft.Extensions.Hosting.Abstractions` and
  `Caching.Abstractions`) and `ModelContextProtocol.AspNetCore` (HTTP); these facts came from memory and are verified here.
  Check from the SDK docs / nuget.org and a throwaway console in the scratchpad: (1) dependency weight of each package
  (transitive list, size, AOT / trimming warnings); (2) whether Core alone registers tools programmatically with our §7.2
  JSON schemas as `inputSchema` / `outputSchema` and returns `structuredContent` over stdio; (3) client compatibility:
  Claude Code (`.mcp.json` stdio), Microsoft Agent Framework (which consumes MCP servers through this SDK; confirm in its
  docs) and the MCP Inspector, each listing and calling one tool; (4) licence of each package (Apache-2.0 / MIT; must be
  GPL-3.0-compatible) and the version (≥ 2 weeks old). **Default to `ModelContextProtocol.Core` if it suffices.** Record the
  answers and the choice in `docs/release/mcp-sdk-choice.md`.
- [ ] **Step 1: Write failing tests:** `ToolsList_HasSixTools_WithSchemas`; `EachTool_StructuredContentEqualsCliJson` (same
  args, byte-equal JSON); `Evict_DefaultsToDryRun`; `UnknownArgument_RejectedBySchema`; `ToolError_IsResultWithIsError`.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement with the chosen package's stdio transport.
- [ ] **Step 4:** Rerun; PASS; mutants: tool output re-shaped; dry-run default false.
- [ ] **Step 5:** Add a Claude Code `.mcp.json` example to `docs/CHUNK_CACHE.md`; commit. **G-I2: stop and report.**

### Task 19: `lines-512` on the wire (gate G-E4c) [CPU]

Runs only after E4c's README states its outcome (§5.11).

**Files:**
- Modify (dotLLM): `Corpus/WireChunking.cs`, server `ChunkCacheEndpoint.cs` capabilities, `chunk-cost-model.json`
  (validated table); CLI and MCP chunker enums
- Test: `WireChunkingTests`, `ChunkCacheEndpointTests`

- [ ] **Step 1:** Read the E4c README. If text-first fixed chunks match id-sliced ones within the CIs: write failing tests
  `Lines512_IsWireEligible` and `Capabilities_ListLines512`; otherwise write `Lines512_StaysPending` and update
  §2 / §5.5 wording in `docs/CHUNK_CACHE.md` ("bar unmet for every wire-eligible chunker").
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Move the name (or not) and add the enum value. **Step 4:** PASS; mutant:
  list not updated in capabilities.
- [ ] **Step 5:** `auto_validated` stays `[]` until Phase I5 runs QR on the GPU; commit; report to the user.

### Task 20: Speed checkpoint with the tiled kernel; cost-model calibration (gate G-tiled) [GPU-lock]

**Files:**
- Create (here): `experiments/I1-shadow-cost/` with `run.ps1`, `summarize.py`, `README.md`
- Modify (dotLLM server branch): `chunk-cost-model.json`

- [ ] **Step 1:** From the G2b results on `feature/chunk-reuse-vulkan-tiled` (tiled ATTN_QPOS), fit `UsPerRowKey` and
  `AssemblyMsPerKTokens` for Vulkan (2K, 8K; 5 / 10 / 20 %); write a failing test `CostModel_PredictsG2bWithin25Percent`
  over the G2b CSV rows.
- [ ] **Step 2:** Update the coefficients; rerun; PASS.
- [ ] **Step 3 [GPU-lock]:** Server on Vulkan (tiled build) with `--chunk-cache`: replay 20 E4 contexts as chat requests
  under `exact` and `shadow`; record server overhead of `exact` (target < 5 ms; §12.5), `shadow` predicted TTFT vs the lab's
  measured reuse TTFT, and hit rates; 3 repeats; provenance.
- [ ] **Step 4:** Write the README (state whether reuse with recompute beats full prefill on the tiled kernel, per cell);
  commit; record numbers in `~/.claude/STRIX_HALO.md` / `LLMs.md` as the user's CLAUDE.md requires; report to the user.

### Task 21: Release path (gate G-REL) [CPU, docs only]

**Files:**
- Create (here): `docs/release/chunk-cache-release-plan.md`; complete `docs/release/chunk-cache-issues/00-umbrella.md`
- Create (dotLLM, branch `feature/chunk-cache-release` off `dev`, not pushed): the `release.yml` diff described below

- [ ] **Step 1:** Write the PR split in dependency order: (1) client package (independent; may ship first); (2) L-library
  (`DotLLM.ChunkReuse` store, index, scanner, selector, Tasks 1–5); (3) L7 lineage; (4) server wire I1a; (5) server store
  I1b; (6) CLI + MCP tool; (7) release wiring. The Vulkan wiring PRs are Task 22. One issue per PR, issue texts from `docs/release/chunk-cache-issues/`.
- [ ] **Step 2:** Write the `release.yml` change on the release branch: today only `DOTLLM_TOOL_PACKAGE_ID` is pushed
  (`release.yml:332-353`). Add repo variables `CHUNKCACHE_TOOL_PACKAGE_ID` and `CHUNKCACHE_CLIENT_PACKAGE_ID`, push each when
  set (same skip-if-unset and `--skip-duplicate` behaviour); `tools/DotLLM.ChunkCache` gets `PackAsTool`, `ToolCommandName`
  `chunkcache` and `PackageId` from the variable. Validate with `actionlint` and a local `dotnet pack` that produces both
  nupkgs; do not push.
- [ ] **Step 3:** Write what the user sets up, in `chunk-cache-release-plan.md`:
  - ids (decided): tool `dotllm-chunkcache` (`dnx dotllm-chunkcache`, command `chunkcache`), client
    `DotLLM.ChunkCache.Client` (the user confirms `DotLLM.*` new ids are publishable);
  - set repo variables `CHUNKCACHE_TOOL_PACKAGE_ID`, `CHUNKCACHE_CLIENT_PACKAGE_ID` (`NUGET_USER` already exists);
  - confirm the two existing trusted-publishing policies (`release.yml`, `ci.yml`, owner `jamesburton`, repo `dotLLM`) cover
    new package ids under that owner, or push the first version with a glob-scoped API key;
  - optional prefix reservation;
  - **warning:** any push to `dev` creates a `0.3.0-dev.<n>` prerelease and publishes every package whose variable is set,
    so set the variables only when the PRs are merged.
  - the client licence / NOTICE question is with dotllm-97, who will confirm it with James.
- [ ] **Step 4:** Commit here; report to the user. Nothing is filed or pushed.

### Task 22: PR split for the Vulkan wiring [CPU; GPU-lock for re-verification]

Our Vulkan work (`feature/chunk-reuse-vulkan` `bac190ab`, `feature/chunk-reuse-vulkan-tiled` `7bef8f38`) becomes small
PR-ready branches off `dev`. The tiled kernel itself is dotllm-97's PR #1541; our PRs that need it wait for it to merge.

**Files:**
- Create (here): `docs/release/chunk-reuse-vulkan-pr-split.md`; `docs/release/chunk-cache-issues/NN-vulkan-*.md` (one per PR)
- Create (dotLLM, local only): one branch per PR off `origin/dev`, `feature/chunk-reuse-vk-<n>-<slug>`, in worktrees

- [ ] **Step 1:** List the commits of both branches by concern (`git log --stat origin/dev..bac190ab`, then
  `bac190ab..7bef8f38`): backend seam (`IChunkBackend`, CPU / Vulkan backends, backend tag), resident entries and device
  copy, single-pass recompute and the `SupportsQueryPositionAttention` refusal, the lab command changes, the floor command.
  Propose one PR per concern, each ≤ ~600 changed lines where possible, in dependency order, with the tests that come
  with it.
- [ ] **Step 2:** For each PR, write the issue draft (title, body, acceptance criteria per the Global Constraints, mutant
  evidence carried over from the Phase G task reports) and cherry-pick / re-split the commits onto its branch; build; run
  the CPU suite with `DOTLLM_SKIP_VULKAN=1`.
- [ ] **Step 3 [GPU-lock]:** Run the GPU-gated tests of each branch once (slot via the user); record results in the issue
  draft.
- [ ] **Step 4:** Commit the split doc here; report to the user. Each PR is filed (by dotllm-97 / the user) and pushed only
  with the user's explicit approval for that PR; rebase each branch on `dev` before review.

### Task 23: E10, reuse error × KV-quantisation error (gated) [CPU first; GPU later]

**Question:** how the reuse error (naive / recompute vs full prefill) and the KV-quantisation error (quantised vs F32 KV)
compound, on the E4 harness, and therefore which stored-row dtype (Phase D1) each KV dtype needs.

**dtypes (from dotllm-97):** `KvCacheDType` = F32 (F16 on GPU), Q8_0 (34 B / 32 elements), Q4_0 (18 B / 32), TurboQuant
(rotation + Lloyd-Max, bits via `KvCacheConfig.TurboQuantBits`). CPU `QuantizedKvCache`, Vulkan `KvQuantizeKernel` /
`KvDequantKernel`, CUDA `CudaQuantizedKvCache`. Per-query-position attention for quantised KV is **not planned** (#1541
covers F32 / F16 only); dotllm-97 will add F16 KV and 16K / 32K for the tiled kernel, and read the feasibility of Q8_0 for
qpos after our G2b numbers.

**Gates:** the CPU part needs only Task 1 (assembly into a `QuantizedKvCache` destination; today the assembler refuses
non-F32 destinations, so a narrow assembler change behind a test comes first). The GPU part for F16 waits for dotllm-97's F16
tiled kernel; for Q8_0 / Q4_0 / TurboQuant it waits until per-query-position attention supports them (not planned today).

**Files:**
- Modify (dotLLM, `feature/chunk-cache`): `ChunkAssembler.cs` / `StoredContextAssembler.cs` (quantised destination: write
  F32 rows through the cache's own quantiser), `benchmarks/ChunkKvLab/E4Command.cs` (`--kv-dtype f32|q8_0|q4_0|turbo<bits>`)
- Test: `tests/DotLLM.Tests.Unit/ChunkReuse/QuantizedAssemblyTests.cs`
- Create (here): `experiments/E10-reuse-x-kvquant/` with `run.ps1`, `summarize.py`, `README.md`

- [ ] **Step 1: Write failing tests:** `AssembleIntoQ8_0Cache_EqualsQuantisingTheF32Assembly` (bit-exact against quantising
  the F32-assembled rows with the cache's quantiser); same for Q4_0 and TurboQuant; `UnsupportedDtype_Refused`.
- [ ] **Step 2:** Run; expected FAIL. **Step 3:** Implement. **Step 4:** PASS; mutants: rows written unquantised; shift
  applied after quantisation.
- [ ] **Step 5 [CPU]:** E4 arms (naive, chunk starts, QR; 5 / 10 / 20 %) × KV dtype {F32, Q8_0, Q4_0, TurboQuant 4 / 3 bits}
  on the same validated tasks, 3 seeds, 2K. Report the four errors per cell against the F32 full prefill: KV quant alone,
  reuse alone, both, and the interaction (both − sum), with paired cluster-bootstrap CIs.
- [ ] **Step 6 [GPU-lock, gated]:** Repeat on Vulkan for F16 when the F16 tiled kernel lands, and for the quantised dtypes
  only once qpos supports them.
- [ ] **Step 7:** README: the store implication (compact stored rows must match the KV dtype: F16 rows for F16 KV, Q8_0 rows
  for Q8_0 KV; whether a Q8_0 store row feeding an F32 cache costs accuracy), which feeds Phase D1; record numbers in
  `~/.claude/LLMs.md`; commit; report to the user.

---

## Phase D: persistent cache with direct-to-device loading (later; gate G-D)

**Gate G-D:** G-I2 passed, the user approves, and the dotLLM Vulkan owner (dotllm-2d or successor) agrees on D3–D4. Its own
plan is written then; the scope below is fixed now. Source: `.superpowers/sdd/2026-11-01-phase-s/progress.md` (user
direction 2026-11-02).

| # | item | lane / owner | runs |
|---|---|---|---|
| D1 | compact stored rows F16 and Q8_0 (≈ 0.5× / 0.27× of F32), matching the cache's KV dtype as E10 (Task 23) decides, plus a payload checksum (xxHash64 per layer slab; mismatch = miss), `.ckv` format v3; dtype stays in key and header | this project, `feature/chunk-cache` | CPU |
| D2 | aligned layout: page- and sector-aligned per-layer K/V slabs in the cache's device dtype, so a slab maps without repacking | this project | CPU |
| D3 | Vulkan import of mmap'd slabs on the UMA iGPU (`VK_EXT_external_memory_host`, host-pointer import; DirectStorage-style read into host-visible memory as the fallback); our consumer behind `IChunkBackend` | request to the Vulkan owner; our seam | GPU-lock |
| D4 | readback fix: `ReadRows` runs at 145 MB/s through uncached memory (`experiments/G1-e1-vulkan/vulkan-primitive-requests.md`) | Vulkan owner | GPU-lock |
| D5 | backend tag in the header | done early in Task 1 (needed by I1) | — |
| D6 | measure TTFT cold disk vs warm page cache vs resident, per chunk count, 2K–32K | this project, `experiments/D-direct-load/` | GPU-lock |

Each item keeps the Global Constraints (TDD, mutants, review, CPU-vs-Vulkan separation, no push).

## Phase I5: applied reuse (later; gate G-I5)

**Gate G-I5:** engine assembly into the server's paged / quantised / multi-slot KV (L5, dotLLM session), #1540 merged to
`dev`, a Vulkan QR probe (Phase G Task 5), and E4c for fixed chunks. Planned separately when those hold. Scope: segmented
tokenisation for applied policies (§5.3 item 7); approximate snapshot rows (uses Task 12); `balanced` / `fast`; `auto` gates
(validated table entries only after an E4-style measurement on the model and backend; cost model from Task 20); TTFT and
accuracy metrics of §12.5. The default stays `exact`.

## Not in this plan

I7 transparent mode and the Claude Code recipe; adapters for Semantic Kernel / LangChain / Claude Code; `contextual`
positioning; by-reference chunks; `hybrid` selector; `numbered-relative` (L9's render suffix is reserved; the chunker half of
L9 already exists as `index-<chunker>.json`); recurrent models (Phase T); the E7 quality half.

## Decisions (answered 2026-11-02)

1. **Auth:** `--chunk-cache-api-keys` file, one namespace per key; loopback-only without a file; the whole surface is OFF by
   default (`--chunk-cache`). Approved by the user.
2. **Client package:** MIT, in the same dotLLM repo with its own licence setting; pure HTTP / DTOs, no GPL project
   references. Decided by James; dotllm-97 will confirm (NOTICE, trusted publishing).
3. **Lane S:** we implement PR-ready branches; dotllm-97 / the user file issues and merge; we file nothing.
4. **Wire chunker name:** `lines-512` everywhere; the existing `TextFirstFixedChunker` / `fixed-text-512` is renamed in
   Task 5.
5. **Package ids:** tool `dotllm-chunkcache`, client `DotLLM.ChunkCache.Client`.
6. **MCP:** the official MCP C# SDK; `ModelContextProtocol.Core` unless Task 18 Step 0 shows it does not suffice.
7. **Client before store:** approved; the client lane depends on no store task.

## Self-review notes

- 2026-11-02 rev 3: Task 9 done; rulings 19–21 folded into Tasks 5b (new), 10, 11, 13, 15, 17.
- Spec coverage: L1 Tasks 15, 17; L2 Task 3; L3 Task 4; L4 Task 1; L5 gate G-I5; L6 Task 5; L7 Task 12; L8 Task 2; L9 noted
  above. I1a Tasks 9–14; I1b Tasks 15–16; I2 Tasks 6–8; I3 Tasks 17–18; I4 Appendix A; I5 and I6 (Phase D) gated sections;
  I7 deferred. §12.6 dotLLM contract tests map to Tasks 9, 10, 11, 13, 1/15 (CPU entry never hits on Vulkan) and 3/16
  (orphans keep ledger entries).
- Server-surface facts checked on `dev` while planning: no authentication (`SERVER.md` § Security, hence decision 1);
  prefix cache in `DotLLM.Engine/PromptCache/`; only `DOTLLM_TOOL_PACKAGE_ID` is pushed by `release.yml`.
- `TextFirstFixedChunker` (`fixed-text-512`) already exists on `feature/chunk-kv-reuse` (`8560d36a`); Task 1 merges it and
  Task 5 renames it to `LinesChunker` / `lines-512`.
- 2026-11-02 revision: user decisions and dotllm-97's answers folded in; Tasks 22 (Vulkan PR split) and 23 (E10) added.

---

## Appendix A: CodeSharp handoff (for the CodeSharp session; not tasks for us)

> **HANDOFF: status NOT SENT.** Owner: the CodeSharp session (codesharp-d1). Send condition: G-I2 passed and the user's
> approval. CodeSharp's B3 / B9 precondition gates their reuse comparisons, not this plan.

Sent by the controller after G-I2 and with the user's approval. CodeSharp owns the design and the code; this is the brief.

**Precondition (spec §12.4):** B3 (append-only memory index) and B9 (cache-miss monitor) are built, ideally B7 (reload
detection), before any reuse comparison. `shadow` hit-rate measurement may start earlier.

**What exists for you:** `DotLLM.ChunkCache.Client` (Tasks 6–8): `ChunkAnnotatingChatClient`, `ChunkCacheBodyHandler`,
`IndexChunkSource`, `ChunkCacheHttpClient`, `ExactPolicy`; a server with `--chunk-cache` (`exact`, `shadow`); `chunkcache`
CLI and MCP; fixtures in `docs/contracts/chunk-cache-v1/`.

**Spike scope (in):** probe `GET /v1/chunk-cache` and `IPrefixCachePolicy.ChunkReuseFor(modelId)` backed by cached probe
state (re-probe on `/props` model change); the body handler next to `DotLlmMaxTokensHandler`, gated on the `dotllm` provider;
the decorator below `Retrying`, above `UniqueToolCallId`; LF-normalised chunk-aware `read_file` (option c; LF-only files
first is fine); PostToolUse invalidation; telemetry per call; `exact` / `shadow` (approximate only behind a dev setting); the
chunk-aware compaction planner behind a setting; sub-agent hand-off. **Out:** in-process hosting, transparent mode, Python,
recurrent models. Model: Qwen3-4B-Instruct-2507 Q4_K_M on Vulkan (Strix); GPU work coordinated through the user.

**Success metrics (§12.5):** `shadow` hit rate (report; ≥ 0.8 a hypothesis); plumbing loss < 5 % with every drop attributed;
`exact` neutrality identical; overhead < 5 ms; TTFT and accuracy only after I5.

**Test plan:** §12.6 (unit, contract, integration after the precondition, provider-conformance with the capability absent
and present).

**Open questions to answer in your design** (§12.7): AsyncLocal hand-off through `Retrying` / `ProviderLivenessHandler`
(Task 8 checked a plain `HttpClient` stack only); session JSON round-trip of content `AdditionalProperties`; sub-agent
history; `HookContext` file path; planner vs `CompactionFlattener` and B5's target; span-aware spill in `ToolOutputGuard`;
B3 / B9 / B7 scheduling; recorded-session corpus; OpenTelemetry names; hybrid models.
