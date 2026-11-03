# Library: namespace in `ChunkKey` (key scheme `chunk-key/v4`) (draft)

> **Status: DRAFT, not filed.** Our side files nothing and pushes nothing. Umbrella: `00-umbrella.md`, PR row 2 (library
> PR, Lane L Tasks 1-5; this draft is the Task 2 part and may be folded into the row-2 issue). Branch: `feature/chunk-cache`
> (local only; the library PR is cut fresh from `dev` later). Plan: Phase I Task 2 (spec §14 L8, §10).

**Suggested title:** `chunk-cache store: namespace in ChunkKey (per-API-key store partitions, key scheme v4)`

## Body

Spec §10: as soon as a server has an API key or more than one client, namespace isolation is on by default: one namespace
per key, salted into `ChunkKey`, so one tenant's requests can neither hit nor probe another tenant's entries. This adds the
library half (`DotLLM.ChunkReuse`); the server wires it per request in the I1b store PR.

What it adds:

- **`ChunkKey.Create(..., ChunkPositioning positioning, string @namespace = ChunkNamespace.Default)`.** The namespace is
  hashed, length-prefixed, right after the scheme string. Key scheme `chunk-key/v3` → **`chunk-key/v4`**. The default
  namespace `""` is hashed too (a zero length), never skipped, so no v4 key equals a v3 key.
- **`public static class ChunkNamespace`**: `Default = ""`; `ForApiKey(apiKey)` = `"k-"` + the first 16 lowercase hex of
  SHA-256 over the key's UTF-8 bytes (a digest, never the key; stable; never equals `Default`; an empty key is refused).
  `IsValid` / `Validate` / `MaxLength`: a namespace must match `^(|k-[0-9a-f]{16}|[a-z0-9._-]{1,64})$` and must not be
  the reserved `default` (`ChunkNamespace.ReservedDefaultName`, the default namespace's tag in index file names; ruling
  from the Task 4/4b review, S4), enforced by
  `ChunkKey.Create` and by `Assemble` up front. The namespace is hashed with a strict (throwing) UTF-8 encoder, so two
  lone-surrogate strings cannot collapse to the same U+FFFD bytes.
- **`StoredContextAssembler.KeyOf(config, ids, @namespace = Default)`** and **`Assemble(..., query, @namespace =
  Default)`**: one namespace's entries are never hits, rejects or evictions in another. A null namespace is refused before
  any store read.
- **Indexes:** the index producer identity is `keyOf([])`, so it now includes the namespace; an index saved under one
  namespace loads empty, with a `LoadNote`, under another.

**Compatibility.** Every existing key changes (default namespace included). Stores written under `chunk-key/v3` are rebuilt,
not migrated: `chunkcache build` re-encodes under the v4 keys, and `chunkcache evict` then collects the v3 files as orphans.
The `.ckv` format (version 2) is unchanged. The API is unreleased.

Not in this change: the ledger's namespace column (Task 3, L2), per-request namespaces in the server and `evict --mode
namespace` (Task 16), and a CLI `--namespace` option (the CLI keeps the default namespace).

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; `Closes #N` closed by hand.
- [ ] `DOTLLM_SKIP_VULKAN=1 dotnet test tests/DotLLM.Tests.Unit --filter FullyQualifiedName~ChunkReuse` passes.
- [ ] `Key_DefaultNamespace_GoldenV4` pins the v4 default key and the v4 key of one named namespace; both were derived by an
  independent Python re-implementation of the encoding that reproduces the v3 goldens; the v3 golden no longer matches.
- [ ] `Key_DiffersByNamespace`, `ForApiKey_IsStable_AndNeverEqualsDefault` (golden `k-e0dbaa0c6455768b` for
  `sk-test-123`), `Index_SavedUnderOtherNamespace_LoadsEmptyWithNote`, `Assemble_OtherNamespace_AllMisses`,
  `Namespace_LoneSurrogates_NeverShareAKey`, `Namespace_Valid_IsAccepted`, `Namespace_Invalid_IsRefusedEverywhere` and
  `Namespace_Null_IsNotValid` pass.
- [ ] Every correctness test shown to fail against a mutant (below).

## Mutant evidence

Each mutant was applied in a `git archive` copy of `bea84032` plus the Task 2 diff (now `446e79d7`), the ChunkReuse
filter was run on the CPU (`DOTLLM_SKIP_VULKAN=1`), and the file was restored byte for byte. **15 applied, 15 killed**
(baseline 584 passed / 22 skipped / 0 failed). Driver `phase-i-task-2-mutate.py`, log `phase-i-task-2-mutants.log`
(`.superpowers/sdd/2026-11-01-phase-s/`).

| mutant | killed by |
|---|---|
| N1 namespace not hashed | `Key_DefaultNamespace_GoldenV4`, `Key_DiffersByNamespace`, `Index_SavedUnderOtherNamespace_LoadsEmptyWithNote`, `Assemble_OtherNamespace_AllMisses`, `StoredAssembly_DefaultCtor_KeysOnCpu` |
| N2 default namespace skipped (null-skip), scheme v4 | `Key_DefaultNamespace_GoldenV4`, `StoredAssembly_DefaultCtor_KeysOnCpu` |
| N2b null-skip and scheme left at v3 (default keys collapse to v3) | the two above, `Store_FormatV1File_IsMiss` |
| N3 scheme string not bumped | `Key_DefaultNamespace_GoldenV4`, `StoredAssembly_DefaultCtor_KeysOnCpu` |
| N4 namespace without length prefix | same two |
| N5 namespace hashed after the tokens | same two |
| N6 `Assemble` ignores its namespace | `Assemble_OtherNamespace_AllMisses` |
| N7 `KeyOf` drops its namespace | `Assemble_OtherNamespace_AllMisses` |
| N8 `ForApiKey` returns the full 64-hex digest | `ForApiKey_IsStable_AndNeverEqualsDefault` |
| N9 `ForApiKey` drops the `k-` prefix | same |
| N10 `ForApiKey` hashes UTF-16 | same |
| N11 `ForApiKey` accepts an empty key | same |
| N12 `ForApiKey` returns the key itself | same |
| N13 `ChunkKey.Create` treats null as the default | `Key_DiffersByNamespace` |
| N14 `Assemble` / `KeyOf` treat null as the default | `Assemble_OtherNamespace_AllMisses` |

Review fix round (`a152e504`; driver `phase-i-task-2-fix-mutate.py`, log `phase-i-task-2-fix-mutants.log`): **9 of 10
killed, 1 equivalent.**

| mutant | result |
|---|---|
| F1 `ChunkKey.Create` skips the rule | killed: `Namespace_Invalid_IsRefusedEverywhere`, `Assemble_OtherNamespace_AllMisses`. `Namespace_LoneSurrogates_NeverShareAKey` still passes here: the strict encoder alone refuses lone surrogates |
| F2 replacing UTF-8 encoder for the namespace | **equivalent**: the rule admits ASCII only, so the encoder never sees a surrogate |
| F3 F1 + F2 | killed: `Namespace_LoneSurrogates_NeverShareAKey`, `Namespace_Invalid_…`, `Assemble_OtherNamespace_…` |
| F4 upper case accepted / F5 no length bound / F6 `/` and `\` accepted / F7 any characters accepted / F8 `Validate` checks only null | killed: `Namespace_Invalid_IsRefusedEverywhere` (F4, F6, F7 and F8 also by `Assemble_OtherNamespace_…`) |
| F9 `Assemble` checks only null up front | killed: `Assemble_OtherNamespace_AllMisses` (ParamName `namespace` before `destination`) |
| F10 null counted as valid | killed: `Namespace_Null_IsNotValid` |
