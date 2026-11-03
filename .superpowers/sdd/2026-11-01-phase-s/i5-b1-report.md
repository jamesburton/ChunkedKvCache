# Phase I5 Task B1 report: reuse planner (`ReuseLayout`) and placement with holes (`ChunkAssembler.AssembleAt`)

**Status: DONE_WITH_CONCERNS.** The library, the tests and the mutants are complete and green. Concerns: the plan's GPU step (Step 5) was
not run (CPU-only brief), and F16 is covered only by emulation, because the CPU has no F16 KV cache (see "F16 direction").

- **Worktree / branch:** `C:\Development\dotLLM\.claude\worktrees\chunk-cache`, `feature/chunk-cache`, on `76c15ed6` (after the dev
  merge).
- Nothing pushed; no issue or PR filed. The merge into `feature/chunk-cache-apply` (plan Step 6) is left to the controller, because B0
  owns that branch.

## Commits

| repo | commit | what |
|---|---|---|
| dotLLM | `6bc0f393` | `src/DotLLM.ChunkReuse/Applied/ReuseLayout.cs` (new); `ChunkAssembler.cs` (`AssembleAt` ×4; `Assemble` moved onto the same validated core); `tests/.../ChunkReuse/ReuseLayoutTests.cs`, `ChunkAssemblerAtTests.cs` (new) |
| ChunkedkvCache | (this commit) | this report; `i5-b1-mutants.log`, `i5-b1-mutate.py`, `i5-b1-red.log`; issue draft `docs/release/chunk-cache-issues/i5-b1-planner.md` |

## What was built

**`ReuseLayout.Plan(promptLength, restoredRows, hits, promptIds, budget, minPlacedTokens = 256)`** (namespace
`DotLLM.ChunkReuse.Applied`). It returns a `ReuseLayout` with the following fields:
- `RegionStart`, `RegionEnd`, `Placements`, `Selection`, `PlacedRows`, `ChunkRowsSelected` and `HoleRows`, as in the plan.
- Additions beyond the plan's interface:
  - `Reason`: one of `no_hits`, `too_little_reuse`, `prompt_ids_changed`.
  - `Holes`: the gap token runs.
  - `IsReuse`.
  - `FirstApproxRow`: the lineage handoff, equal to the first placed position.
  - `ChunkPlacement.ShiftDelta`: equal to the target position.
  - `DefaultMinPlacedTokens`.

Planning rules:
- Hits are sorted by start position. A hit is dropped when any of these holds:
  - it is empty or out of range;
  - it starts below `restoredRows` (inside or straddling the restored prefix);
  - it overlaps an earlier kept hit;
  - it ends at the prompt end (the tail must keep at least one token). The plan allowed "dropped or trimmed"; I chose to drop it, so
    an entry is always placed whole.
- Holes are every region position that is not placed. All of them are selected for recompute and none count against the budget.
- Chunk rows: `round(budget × placed)`, rounding half away from zero. They are chosen by `ChunkStartsSelector` over a `ChunkedContext`
  built from the placed chunks, with seed 0.
  - A **one-token stand-in chunk 0** is prepended. The lab treats chunk 0 as exact and ranks it last. In a prompt, though, the first
    placed chunk follows the template header and glue, so it is stale. With the stand-in, every placed chunk gets an equal prefix
    share (67 / 67 / 66 in the test).
- Programming errors throw: budget not finite or outside [0, 1], negative values, null hits. Data mismatches return "no reuse" with a
  reason.

**`ChunkAssembler.AssembleAt`** has four overloads: host `ChunkKvEntry` or `ResidentChunkKvEntry`, each as one chunk or an ordered
list. Each takes an optional `promptTokens`.
- Positions must be ascending and disjoint, and the first must be ≥ `CurrentLength`.
- Keys are shifted by the target position.
- Holes and `[CurrentLength, first)` are left untouched.
- `CurrentLength` ends as last + n.
- Atomic: the destination, fingerprint, backend tag, K/V shape, the prompt's tokens at each position, the positions themselves and
  the capacity are all checked before the first write.
- On a write failure the cache rolls back to its start length.
- `Assemble` now runs on the same core with running offsets. Its behaviour and messages are unchanged; the full suite confirms this.

## Tests (CPU, synthetic dense qwen3, F32)

**Red.**
- With the tests written first, the build failed with `CS0234` / `CS0246` (`Applied`, `ReuseLayout`, `ReuseSpan` missing).
- Against `NotImplementedException` stubs, the run gave **49 failed / 0 passed** (`i5-b1-red.log`).
- The 50th test (F16, below) was added after the controller's direction change, i.e. after the red phase. It carries its own fixture
  guards, and mutants M1, M2, M6 and M13 kill it.

**Green.** `ReuseLayoutTests` has 28 cases and `ChunkAssemblerAtTests` has 22: **50 / 50 passed**.

**Full CPU suite** (`FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU`): **6,984 passed, 56 skipped, 0 failed** (8 m 19 s).

Every test the plan names exists:
- `Plan_HolesAreAllSelected`, `Plan_SelectionAscendingWithinRegion`, `Plan_TailAlwaysAtLeastOneToken`, `HitStraddlingRestoredPrefix_NotPlaced`.
- `Plan_OverlappingHits_SecondDropped`, `Plan_BudgetCountsChunkRowsOnly`, `Plan_TooLittleReuse_NoRegion`, `Plan_ChunkStartsAreEqualPrefixesPerChunk`.
- `AssembleAt_LeavesHole_LengthIsEnd`, `AssembleAt_KeysEqualEncodeAtPosition`, `AssembleAt_BelowCurrentLength_Refused`, `AssembleAt_WrongFingerprint_NothingWritten`.
- `HolesThenRecompute_EqualsFullPrefill_WhenEverythingSelected`.

The brief's properties, and the tests that cover them:
- **100 % recompute at the chunks' offsets reproduces plain prefill, pinned to the CPU F32 oracle.** Both the cache rows (every layer)
  and the first-token logits are **bit-identical** to a plain prefill, for restored prefixes 0, 7 and 12. At 12 the prefix cuts chunk
  A, so A is not placed.
- **Gaps handled.** With budget 0 (holes only):
  - every row below `FirstApproxRow` is bit-exact at every layer;
  - every hole's layer-0 K/V equals the plain prefill's exactly. Holes are dirtied beforehand with another prompt, so an unwritten
    hole cannot pass by accident.
  - Chunk rows at layer 0 fall within the RoPE bound.
  - A fixture guard checks that chunk B's layer-2 keys do differ from the plain prefill (> 1e-3).
- **Shifted chunk equals the model's own keys** at the target position, within 3e-5 of the head norm. Measured 1.16e-6 against a
  bound of 1.44e-4. Guards cover the unshifted keys and an off-by-one shift.
- **Failure atomicity.** Every refused call leaves the K/V buffers byte-identical (checked over the whole allocation) and the length
  unchanged. The refusals tested:
  - position below the current length, or negative;
  - wrong fingerprint or backend tag;
  - tokens that differ from the prompt;
  - K/V shape off by ±1 float, or a missing layer;
  - a resident cache shorter than its entry, or a disposed entry;
  - past capacity;
  - overlapping or descending positions, or a count mismatch.
  - An injected write failure at three different points rolls back to the start length.
- **Never reads outside entries.** The exact-shape check (±1 float) and the resident-length check both refuse before any row is read.

## F16 direction (controller message, folded in)

- **The library code is storage-agnostic.** `ReuseLayout` touches no cache. `AssembleAt` moves rows only through `IChunkBackend`:
  host F32 rows in and out, and `IPositionedHostKvCache` on Vulkan, which stores F32 or F16. I added no F32 assumption. The only F32
  gates are the backends' existing `RequireCache` checks: CPU accepts an exact `SimpleKvCache`; Vulkan refuses `VulkanKvStorage.F16`
  in `VulkanChunkBackend.CheckCacheSupported`.
- **Bit-exactness is used only where a test pins the CPU F32 oracle**, and those tests say so in their docs. Narrower storage is judged
  by tolerance against a floor.
- **The CPU has no F16 KV cache.** It has F32 `SimpleKvCache` and quantised Q8_0 / Q4_0 / TurboQuant caches without positioned row
  IO. So a real F32/F16 parametrisation on the tiny model is not possible on the CPU.
- In its place, `AssembleAt_F16Storage_WithinRounding_BelowReuseFloor` uses an **F16-rounding backend**. It wraps `CpuChunkBackend` and
  rounds every placed, copied or shifted row through `Half`, as an F16 `VulkanKvCache` does on `WriteRows`. The test checks that:
  - placed rows are within 2⁻¹⁰ of the F32 placement, and > 0 so the fixture can discriminate;
  - a 100 % recompute erases the rounding completely (bit-exact again);
  - at a 20 % budget, F16 storage moves the first-token logits by **8.8e-4**, against a reuse error of **1.55**. The test asserts ≤ 10 %
    of the reuse error, i.e. the storage error sits far below the reuse floor.
- **F16 gaps, for B4 or the Vulkan owner:**
  1. `VulkanChunkBackend.CheckCacheSupported` refuses F16. Applied reuse on the default dense Vulkan KV (#1151 / #1549) needs that gate
     lifted. Per the brief, the device shift and tiled qpos already handle F16. The GPU test should then judge against the G0 / G2b
     floors, not bits.
  2. `VulkanChunkBackend.CreateCache` always creates F32 encode caches. Resident entries copied by `CopyRowsFrom` must share the
     destination's element format (`CopyRowsFrom` refuses otherwise), so F16 destinations need F16 resident entries.
  3. `ChunkKvEntry` and the store are host F32 (the store format). An F16 store format is a separate decision: key plus header
     version.
  4. Q8_0 (#1550) needs a quantised row path; `IPositionedHostKvCache` deals in F32 rows. That is later work.

## Mutants

Driver `i5-b1-mutate.py`; log `i5-b1-mutants.log`. Each mutant ran in a `git archive 6bc0f393` copy (scratchpad `i5b1\mut`) against
114 assembly / planner tests, with a 114 / 114 baseline. The live worktree was never mutated.

| id | mutant | result | killed by (examples) |
|---|---|---|---|
| M1 | hole not selected | killed | `HolesThenRecompute_*` ×3, `Seeded_NoChunkBudget_*`, `Plan_HolesAreAllSelected`, … |
| M2 | selection sorted descending | killed | `Plan_SelectionAscendingWithinRegion`, `HolesThenRecompute_*`, … |
| M3 | host shift by placement index instead of position | killed | `AssembleAt_KeysEqualEncodeAtPosition`, `AssembleAt_LeavesHole_*`, `Assemble_*` (13) |
| M4 | tail allowed to be empty | killed | `Plan_TailAlwaysAtLeastOneToken` |
| M5 | straddling hit placed (explicit check only) | **survived: equivalent** | the guard is redundant (`end` starts at `restoredRows`) |
| M5b | straddling hit placed (both guards removed) | killed | `HitStraddlingRestoredPrefix_NotPlaced`, `HolesThenRecompute_*(restored: 12)` |
| M6 | length not advanced | killed | `AssembleAt_LeavesHole_LengthIsEnd` and 10 others |
| M7 | position below current length accepted | killed | `AssembleAt_BelowCurrentLength_Refused` |
| M8 | overlapping positions accepted | killed | `AssembleAt_Many_OverlappingOrDescending_Refused` |
| M9 | prompt-token check skipped (`if (true)`) | invalid (CS0162 build error) | replaced by M9b |
| M9b | prompt-token check skipped (non-constant) | killed | `AssembleAt_TokensDifferFromPrompt_NothingWritten` |
| M10 | no rollback on write failure | killed | `AssembleAt_WriteFailure_*(4, 8)`, existing `Assemble_FailureOnSecondChunk_*` |
| M11 | token check after the first write | killed | `AssembleAt_TokensDifferFromPrompt_NothingWritten` |
| M12 | first placed chunk treated as exact (no stand-in) | killed | `Plan_FirstPlacedChunkIsStale_GetsItsShare`, `Plan_ChunkStartsAreEqualPrefixesPerChunk` |
| M13 | budget over the whole region | killed | `Plan_BudgetCountsChunkRowsOnly` and 7 others |
| M14 | `FirstApproxRow` = `RegionStart` | killed | `Plan_FirstApproxRow_*`, `Seeded_NoChunkBudget_*` |
| M15 | `ShiftDelta` off by one | killed | `Plan_ShiftDeltaIsTargetPosition` |
| M16 | overlapping hits kept | killed | `Plan_OverlappingHits_SecondDropped` |
| M17 | resident shift by index | killed | `AssembleAt_Resident_EqualsHostEntry`, `CpuResidentAssembly_EqualsHostAssembly` |
| M18 | prompt-ids length mismatch ignored | killed | `Plan_PromptIdsLengthMismatch_NoReuse` |
| M19 | resident cache-length check removed | killed | `ResidentAssembly_RefusesShortSourceAndSelfDestination` |
| M20 | host shape check removed | killed | `AssembleAt_EntryShapeMismatch_RefusedBeforeReading(±1)` |
| M21 | minimum ignored (`if (false)`) | invalid (CS0162) | replaced by M21b |
| M21b | minimum ignored (non-constant) | killed | `Plan_TooLittleReuse_NoRegion`, `Plan_DefaultMinimumIs256` |
| M22 | holes start at 0 (rows below the region not protected) | killed | `Plan_HolesAreAllSelected` and 7 others |

All six mutants the plan names (M1, M2, M3, M4, M5b, M6) are killed. Overall: 22 valid mutants killed, 1 equivalent, 2 invalid ones
replaced.

## Deviations

1. **Plan Step 5 (GPU, `AssembleAt_Vulkan_EqualsCpu`) was not done.** The brief was CPU-only; the GPU slot is the user's. No
   GPU-gated test was written, to avoid unrun code. It is better written together with the F16 gate change (gap 1), because F16 is now
   the target.
2. **Plan Step 6 (merge into `feature/chunk-cache-apply`) was not done.** That branch is B0's (controller).
3. **Interface additions:**
   - `Reason`, `Holes`, `IsReuse`, `FirstApproxRow`, `ShiftDelta`.
   - The list overloads of `AssembleAt`.
   - The optional `promptTokens` check. This is the seeder's planned token re-check (B3), moved into the atomic validation so a
     mismatch writes nothing.
4. A hit ending at the prompt end is **dropped, not trimmed**.
5. **Issue draft name:** the brief asked for `i5-b1-planner.md`; the plan said `NN-library-reuse-layout.md`. I followed the brief.
6. **Code location:** `src/DotLLM.ChunkReuse/Applied/` in the single `DotLLM.ChunkReuse` assembly. `feature/chunk-cache` has no
   assembly split. For the upstream split, see question 2.

## Questions for rulings

1. **Stand-in chunk 0.** Every placed chunk is treated as stale, including one placed at position 0 with nothing restored. That case
   is rare, because templates start with a header, and it costs a few budget rows on exact data. Is this acceptable?
2. **Layering.** `ReuseLayout` needs `ChunkStartsSelector`, `RankedSelector` and `IRecomputeSelector`, which are in the PR split's
   deferred / `.Research` group. They are pure C# with no heavy dependencies. Proposal: I5-1 moves these two selector files into
   core together with `ReuseLayout`. The alternative is to put `ReuseLayout` into `.Research`, but then the server would depend on
   `.Research`.
3. **F16 gate.** Should B4 lift `VulkanChunkBackend`'s F16 refusal and add F16 resident encode caches (gaps 1–2)? Or is that a
   separate Vulkan-owner PR ahead of B4?
4. **Trim instead of drop** for a final chunk that ends at the prompt end? That would mean placing n−1 rows of an entry and needs an
   `AssembleAt` row count. Not needed for chat prompts, which always end with the generation-prompt tokens.
