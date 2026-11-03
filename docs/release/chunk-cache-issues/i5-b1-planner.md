# ChunkReuse: reuse planner (`ReuseLayout`) and placement with holes (`ChunkAssembler.AssembleAt`) (draft)

> **Status: DRAFT, not filed.** Phase I5 plan (`docs/superpowers/plans/2026-11-03-phase-i5-applied-reuse.md`) Task B1,
> PR slice I5-1. Refs #1542 (umbrella). Nothing filed or pushed; the user decides per PR.
> Branch: `feature/chunk-cache` (worktree `C:\Development\dotLLM\.claude\worktrees\chunk-cache`), commit `6bc0f393` (+ any fix
> rounds listed in `.superpowers/sdd/2026-11-01-phase-s/i5-b1-report.md`). To be merged into `feature/chunk-cache-apply` (B0).

## Title

ChunkReuse: plan applied chunk reuse in a prompt (placements, holes, recompute rows) and place chunks at arbitrary positions

## Body

Applied chunk reuse (#1542, policies `balanced` / `fast`) needs two library pieces that the server seeder (I5-3) consumes. Neither
touches the engine or the server, and nothing calls them yet.

**`ReuseLayout.Plan(promptLength, restoredRows, hits, promptIds, budget, minPlacedTokens = 256)`** (`DotLLM.ChunkReuse.Applied`):
turns the verified hit spans of a prompt into a plan.
- **Placements.** Hits in position order; a hit is dropped when empty or out of range, when it starts below the restored prefix
  (inside or straddling it: those rows are exact already, reported as `prefix`), when it overlaps an earlier kept hit, or when it ends
  at the prompt end (at least one tail token must be prefilled to produce first-token logits). `ChunkPlacement.ShiftDelta` = target
  position (entries are encoded at `0..n-1`).
- **Holes.** Every region position that is not placed (glue text, misses) is a hole and **always selected for recompute**: assembly
  never writes it, and the ascending recompute writes it before any later row reads it. Also exposed as runs (`Holes`).
- **Recompute rows.** `round(budget × placed rows)` chunk rows ranked by `ChunkStartsSelector` (equal-length prefixes of every placed
  chunk). A one-token stand-in takes the lab's "exact chunk 0" role, so the first placed chunk, which follows the template header and
  glue in a prompt, is treated as stale like the others. Holes are extra (not charged to the budget).
- **Lineage handoff.** `FirstApproxRow` = first placed position: rows below it (restored prefix and holes before the first chunk,
  which attend only exact rows) are exact; every row at or after it is approximate. This is what `PrefixCache.Store(...,
  firstApproxRow)` (#1575) receives.
- **No reuse** (`RegionEnd == RegionStart`, stable `Reason`): `no_hits`, `too_little_reuse` (< 256 placed rows by default),
  `prompt_ids_changed` (prompt length differs from the plan). Invalid arguments (budget outside `[0, 1]` or not finite, negative
  lengths) throw.

**`ChunkAssembler.AssembleAt`** (host `ChunkKvEntry` and device-resident `ResidentChunkKvEntry`; one chunk or an ordered list):
places chunks at given positions at or after the cache's current length, re-rotating keys by the target position, and leaves the
rows in between untouched (holes). Atomic: the destination, every chunk (fingerprint, backend tag, K/V shape, and, when given, the
prompt's own tokens at that position) and every position (ascending, disjoint, inside capacity) are checked before the first
write, so a refused call changes nothing and only rows inside each entry are read; a write failure rolls the cache back to its start
length. `Assemble` now runs on the same core (running offsets), unchanged in behaviour.

**Storage-agnostic.** Rows move only through `IChunkBackend` (host F32 rows in/out; `IPositionedHostKvCache` on Vulkan, which stores F32
or F16). Which caches are accepted stays the backend's decision (`RequireCache`). Today both backends accept F32 only (CPU: exact
`SimpleKvCache`; Vulkan: `VulkanKvCache` F32) — F16 is a backend change, not a planner / assembler one (see "F16" below).

### Tests (CPU, synthetic dense `qwen3` model)

`ReuseLayoutTests` (28 test cases, pure): holes all selected; selection strictly ascending inside the region; every region position placed or
selected; tail ≥ 1 token; straddling / inside-prefix hits not placed; overlapping hit dropped; unsorted hits; invalid hits dropped;
budget counts placed rows only (20 % of 1,000 = 200, holes extra); rounding; budget 1 = whole region; too little reuse (255 vs 256);
equal chunk-start prefixes (67 / 67 / 66); first placed chunk is stale; `ShiftDelta`; `FirstApproxRow`; prompt-id length mismatch;
argument checks.

`ChunkAssemblerAtTests` (22 test cases): hole rows byte-identical after placement and length = end; placed layer-0 keys equal the model's own keys at
the target position within 3e-5 of the head norm (measured 1.2e-6); every layer equals the host RoPE shift; `AssembleAt` at running
offsets equals `Assemble` bit for bit; list form equals single calls; resident equals host; refusals leave every byte and the length
unchanged (below current length, negative, wrong fingerprint, wrong backend tag, tokens differ from the prompt, K/V shape ±1 float or a
missing layer, resident cache shorter than the entry, disposed entry, past capacity, overlapping / descending / count mismatch); write
failure at 3 points rolls back. **Applied flow** (plan → `AssembleAt` → `SelectiveRecomputer.Recompute` → tail prefill):
- **CPU F32 oracle, pinned bit-exact:** with everything selected the cache rows (every layer) and the first-token logits equal a plain
  prefill **bit for bit**, for restored prefixes 0, 7 and 12 (12 cuts a chunk, which is then not placed). With only holes recomputed,
  all rows below `FirstApproxRow` are bit-exact and every hole's layer-0 K/V equal the plain prefill's exactly.
- **F16 storage, by tolerance:** an F16-rounding backend (the CPU has no F16 KV cache; it rounds as an F16 `VulkanKvCache` does)
  places rows within 2⁻¹⁰ of the F32 placement, a 100 % recompute erases the rounding entirely, and at a 20 % budget it moves the
  first-token logits by 8.8e-4 against a reuse error of 1.55 (asserted ≤ 10 %).

Red: compile failure, then 49 / 49 failing against `NotImplementedException` stubs. Mutants: see the report
(`.superpowers/sdd/2026-11-01-phase-s/i5-b1-report.md`, log `i5-b1-mutants.log`).

### F16 / Q8_0 (follow-ups, not in this PR)

- `VulkanChunkBackend.CheckCacheSupported` refuses `VulkanKvStorage.F16`; with F16 the default dense Vulkan KV (#1151 / #1549), applied
  reuse on Vulkan needs that gate lifted (the device RoPE shift and tiled qpos already handle F16 per the Vulkan owner) plus a GPU test
  judged against the G0 / G2b floors, not bits.
- `VulkanChunkBackend.CreateCache` makes F32 encode caches and `CopyRowsFrom` requires one element format, so resident entries for an
  F16 destination must be encoded into F16 caches.
- The CPU has no F16 KV cache; the CPU F32 `SimpleKvCache` remains the oracle. Q8_0 (#1550) needs a quantised row-write path (not
  `IPositionedHostKvCache` F32 rows) and is later work.
- `ChunkKvEntry` stores host F32 rows (store format); an F16 store format is a separate decision (store key + header version).

### Layering (upstream split)

`ReuseLayout` depends on `ChunkedContext` (core) and `Selectors/{IRecomputeSelector, ChunkStartsSelector}` (deferred to I5 in the PR
split, pure C#, no Vulkan / Roslyn). It therefore ships with those two selector files in I5-1, in the core assembly (they have no heavy
dependency); `SelectiveRecomputer` (Vulkan reference) stays in `.Research` / I5-3 and is referenced only in docs (`<c>`, no cref).
`AssembleAt` lives in `ChunkAssembler` (core, PR 3) and needs no new dependency.

### Acceptance

- [ ] `ReuseLayout` + `AssembleAt` + tests; CPU suite green (`FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU`).
- [ ] Mutants listed in the PR body, all killed.
- [ ] GPU step (plan B1 Step 5, `AssembleAt_Vulkan_EqualsCpu`, F16 cache in scope) run under the GPU lock in a user-scheduled slot.
