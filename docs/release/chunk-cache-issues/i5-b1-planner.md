# ChunkReuse: reuse planner (`ReuseLayout`) and placement with holes (`ChunkAssembler.AssembleAt`) (draft)

> **Status: DRAFT, not filed.** Phase I5 plan (`docs/superpowers/plans/2026-11-03-phase-i5-applied-reuse.md`) Task B1,
> PR slice I5-1. Refs #1542 (umbrella). Nothing filed or pushed; the user decides per PR.
> Branch: `feature/chunk-cache` (worktree `C:\Development\dotLLM\.claude\worktrees\chunk-cache`), commits `6bc0f393` and fix round
> `47dab813` (review `.superpowers/sdd/2026-11-01-phase-s/review-i5-b1-report.md`). To be merged into `feature/chunk-cache-apply` (B0).

## Title

ChunkReuse: plan applied chunk reuse in a prompt (placements, holes, recompute rows) and place chunks at arbitrary positions

## Body

Applied chunk reuse (#1542, policies `balanced` / `fast`) needs two library pieces that the server seeder (I5-3) consumes. Neither
touches the engine or the server, and nothing calls them yet.

### `ReuseLayout.Plan`

Signature: `ReuseLayout.Plan(promptLength, restoredRows, hits, promptIds, budget, minPlacedTokens = 256, expectedPromptIds = default)`
(`DotLLM.ChunkReuse.Applied`). It turns the verified hit spans of a prompt into a plan.

- **Placements.** Hits are taken greedily in position order. A hit is dropped when any of these holds:
  - it is empty, starts before 0, or runs past the prompt end;
  - it lies wholly inside the restored prefix (report it as `prefix`);
  - it straddles the restored prefix (its tail is prefilled);
  - it overlaps an earlier kept hit. The earlier start wins, even when it is shorter;
  - it ends exactly at the prompt end, because at least one tail token must be prefilled to produce first-token logits.

  `ChunkPlacement.ShiftDelta` is the target position, since entries are encoded at `0..n-1`.
- **Dropped hits** are listed in `Dropped` as `(SpanIndex, reason)`, sorted by span index. The reasons are `invalid`,
  `inside_prefix`, `straddles_prefix`, `overlap` and `at_prompt_end`. When the plan as a whole refuses, each hit carries the layout's
  own reason. The server needs this for `chunks{prefix, hit, miss}`.
- **Holes.** Every region position that is not placed is a hole: glue text, misses, any non-placed token.
  - Holes are **always selected for recompute**. Assembly never writes them, and the ascending recompute writes each one before any
    later row reads it.
  - They are also exposed as runs (`Holes`).
  - A NaN-filled cache test shows that no hole and no row past a query's position is read before it is written (CPU).
- **Recompute rows.** `round(budget × placed rows)` chunk rows, ranked by `ChunkStartsSelector` (equal-length prefixes of every placed
  chunk). Holes are extra and not charged to the budget.
  - A one-token stand-in takes the lab's "exact chunk 0" role. So the first placed chunk, which follows the template header and glue
    in a prompt, is treated as stale like the others.
- **Budget semantics differ from E4 / G2b.**
  - The lab budget is a fraction of the *whole* context, including the exact chunk 0.
  - Here it is a fraction of the *placed* rows.
  - Per placed chunk, `balanced` 0.20 therefore recomputes `(N−1)/N` of the lab's prefix depth at the same nominal budget:
    - about **94 %** with symbol chunks (N ≈ 16);
    - **83–88 %** with fixed 512-token chunks (N ≈ 6–8);
    - plus every hole, which the lab never had.
  - Quality bars derived from G2b (B6: EM ratio ≥ 0.76 from 24/28 at 20 %) assume lab-equivalent depth. They must be read with this
    difference in mind.
- **Lineage handoff.** `FirstApproxRow` is the **placement-side** bound: the first placed position. Every row at or after it is
  approximate. Rows below it are only as exact as the restored prefix they attend to. So the caller passes
  `min(restored entry's FirstApproxRow, layout.FirstApproxRow)` to `PrefixCache.Store(..., firstApproxRow)` (#1575; B2 does this).
- **No reuse.** `RegionEnd == RegionStart`, with a stable `Reason`:
  - `no_hits`;
  - `too_little_reuse` (< 256 placed rows by default);
  - `prompt_length_changed`: `promptIds` has a length other than the plan's. Only the length is compared, unless the caller passes the
    planned ids;
  - `prompt_ids_changed`: `expectedPromptIds` was given and differs anywhere;
  - `prefix_covers_prompt`.

  Invalid arguments throw: a budget outside `[0, 1]` or not finite, or a negative length.
- **Re-planning.** `Plan` is pure. If a placed entry turns out to be unusable (missing at load, wrong header), the caller must
  **re-plan without that hit** so the new hole is selected and `FirstApproxRow` moves. It must not just skip the placement.

### `ChunkAssembler.AssembleAt`

It handles host `ChunkKvEntry` and device-resident `ResidentChunkKvEntry`, as one chunk or an ordered list.
- It places chunks at given positions, at or after the cache's current length, and re-rotates the keys by the target position. The
  rows in between (holes) are left untouched.
- **`promptTokens` is required on every overload.** Every chunk's token ids must equal the prompt's ids at its target position. An
  empty span is refused, and so is a same-length prompt with different ids. This is the token-identity guard that `Plan` alone does not
  give without `expectedPromptIds`.
- **Atomic.** These are all checked before the first write:
  - the prompt tokens;
  - the destination;
  - every chunk: fingerprint, backend tag, K/V shape and tokens;
  - every position: ascending, disjoint, inside capacity.

  So a refused call changes nothing, and only rows inside each entry are read. A write failure rolls the cache back to its start
  length.
- `Assemble` (running offsets, no prompt) runs on the same core, unchanged in behaviour.

### Storage-agnostic

- Rows move only through `IChunkBackend`: host F32 rows in and out, and `IPositionedHostKvCache` on Vulkan, which stores F32 or F16.
- Which caches are accepted stays the backend's decision (`RequireCache`).
- Today both backends accept F32 only: on the CPU an exact `SimpleKvCache`, on Vulkan a `VulkanKvCache` with F32 storage. F16 is a
  backend change, not a planner or assembler one (see "F16" below).

### Tests (CPU, synthetic dense `qwen3` model)

**`ReuseLayoutTests`** (31 test cases, pure) cover:
- holes all selected; selection strictly ascending inside the region; every region position placed or selected; tail ≥ 1 token;
- straddling and inside-prefix hits not placed; overlapping hit dropped; unsorted hits; invalid hits dropped;
- dropped hits with their reasons, including the layout reason when there is too little reuse;
- the budget counts placed rows only (20 % of 1,000 = 200, holes extra); rounding; budget 1 selects the whole region;
- too little reuse (255 vs 256); equal chunk-start prefixes (67 / 67 / 66); the first placed chunk is stale;
- `ShiftDelta` and `FirstApproxRow`;
- length mismatch (`prompt_length_changed`), a **same-length prompt with different ids** (`prompt_ids_changed` with
  `expectedPromptIds`), and `prefix_covers_prompt`;
- argument checks.

**`ChunkAssemblerAtTests`** (27 test cases) cover:
- **Placement.**
  - Hole rows are byte-identical after placement, and the length equals the end.
  - Placed layer-0 keys equal the model's own keys at the target position within 3e-5 of the head norm (measured 1.2e-6).
  - Every layer equals the host RoPE shift.
  - `AssembleAt` at running offsets equals `Assemble` bit for bit. The list form equals single calls, and resident equals host.
- **Refusals.** Each leaves every byte and the length unchanged:
  - empty `promptTokens` (all four overloads);
  - a same-length prompt with different ids;
  - position below the current length, or negative;
  - wrong fingerprint or backend tag;
  - tokens that differ from the prompt;
  - K/V shape ±1 float, or a missing layer;
  - a resident cache shorter than its entry, or a disposed entry;
  - past capacity;
  - overlapping or descending positions, or a count mismatch.
- **Write failure** at 3 points rolls back.
- **Applied flow** (plan → `AssembleAt` → `SelectiveRecomputer.Recompute` → tail prefill):
  - **CPU F32 oracle, pinned bit-exact.** With everything selected, the cache rows (every layer) and the first-token logits equal a
    plain prefill **bit for bit**, for restored prefixes 0, 7 and 12. At 12 the prefix cuts a chunk, which is then not placed.
  - With only holes recomputed, all rows below `FirstApproxRow` are bit-exact (the restored rows are exact here), and every hole's
    layer-0 K/V equal the plain prefill's exactly.
  - **NaN-filled cache.** Every float of the K/V buffers starts as NaN. At budgets 0, 0.2 and 1.0, the logits and every row up to
    the prompt end come out finite.
  - **F16 storage, by tolerance.** An F16-rounding backend rounds only chunk-backend writes; the CPU has no F16 KV cache. It places
    rows within 2⁻¹⁰ of the F32 placement. At a 20 % budget it moves the first-token logits by 8.8e-4, against a reuse error of 1.55
    (asserted ≤ 10 %).
    - **Simulation limit:** its 100 % recompute is exact only because the model's own writes (prefix, holes, recompute, tail) stay
      F32 in the simulation. On a real F16 cache every forward write is F16. The GPU test must compare against an **F16 plain prefill**
      within the G0 / G2b floors, not against bits and not against F32.

**Red.** Initial round: a compile failure, then 49 / 49 failing against `NotImplementedException` stubs. Fix round: the new tests fail
to compile against `6bc0f393`.

**Mutants.** Initial round: 22 killed, 1 equivalent. Fix round: 8 / 8 killed. See the report
(`.superpowers/sdd/2026-11-01-phase-s/i5-b1-report.md`, logs `i5-b1-mutants.log` and `i5-b1-fix-mutants.log`).

### For the Vulkan follow-up (B4)

- **Holes and NaN.** A new `VulkanKvCache` is not zeroed. After `AssembleAt`, `CurrentLength` lies beyond later holes. A tiled qpos
  kernel that loads K/V tiles past the query position and masks with −inf, or accumulates `p·V` with `p = 0`, gets `0·NaN = NaN`. B4
  must do one of two things:
  - add a GPU test with NaN-filled holes and NaN-filled future rows; or
  - zero-fill the hole runs before the recompute.
- **F16.** `VulkanChunkBackend.CheckCacheSupported` refuses `VulkanKvStorage.F16`. F16 is becoming the default dense Vulkan KV
  (#1151 / #1549), so applied reuse on Vulkan needs that gate lifted. Per the Vulkan owner, the device RoPE shift and tiled qpos
  already handle F16. The GPU test then compares against an F16 plain prefill within the floors.
- **Resident entries.** `VulkanChunkBackend.CreateCache` makes F32 encode caches, and `CopyRowsFrom` requires both caches to have the
  same element format. So resident entries for an F16 destination must be encoded into F16 caches.
- **CPU.** The CPU has no F16 KV cache; the CPU F32 `SimpleKvCache` remains the oracle.
- **Q8_0** (#1550) needs a quantised row-write path, not `IPositionedHostKvCache` F32 rows. That is later work.
- **Store.** `ChunkKvEntry` stores host F32 rows (the store format). An F16 store format is a separate decision: store key plus header
  version.

### Layering (upstream split, ruling 2)

- `ReuseLayout` depends on `ChunkedContext` (core) and on `Selectors/{IRecomputeSelector, ChunkStartsSelector}`. The PR split
  currently defers those two files to `.Research`, but they are plain C# with no Vulkan or Roslyn dependency.
- So they move into the **core** assembly together with `ReuseLayout`. Their crefs to research-only types (`SelectiveRecomputer`,
  `ContiguousRuns`) are now `<c>`.
- **Verified in a scratch copy** of `feature/chunk-cache-upstream-prep`:
  - With `Applied/ReuseLayout.cs`, the two selector files moved from `.Research` into core, and the new `ChunkAssembler.cs`, the core
    project builds with **0 errors** (warnings: only the MinVer "not a git dir" ones from the scratch copy).
  - The core csproj has no Vulkan or Roslyn reference.
  - `DotLLM.ChunkReuse.Research` still builds on top of it (0 errors).
- `AssembleAt` lives in `ChunkAssembler` (core, PR 3) and needs no new dependency.

### Acceptance

- [ ] `ReuseLayout` + `AssembleAt` + tests; CPU suite green (`FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU`).
- [ ] A same-length prompt with different ids is refused (`AssembleAt` always; `Plan` with `expectedPromptIds`).
- [ ] NaN-filled-cache test green.
- [ ] Mutants listed in the PR body, all killed.
- [ ] GPU step, folded into B4: `AssembleAt` on Vulkan with an **F16** destination and F16 resident entries, compared with an F16
  plain prefill within the floors, plus a NaN-hole GPU test. Run under the GPU lock in a user-scheduled slot.
