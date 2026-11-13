Scope for bringing **applied** chunk reuse (lossy, opt-in) to `dev`, plus the experiment that decides whether the auto-chunking idea (chunk chat messages server-side when the prefix cache misses, e.g. after a system-prompt or tool-list edit) is worth building. Planning/measurement only: no implementation PR before James approves the plan. Defaults stay `exact`; any default or policy change needs James. Refs #1542, #1543, #1590.

## Where things stand (verified 2026-11-13)
- On `dev` the chunk cache serves only `exact` / `shadow`: nothing reduces prefill.
- The applied path was never built in the server. Not on dev and not on the research branches: the `--chunk-cache-apply` flag was only planned (I5 Part B B3+).
- Library pieces exist off-dev: `ChunkAssembler`, the CPU/Vulkan chunk backends (`IPositionedHostKvCache`), the planner with `AssembleAt` (`feature/chunk-cache*`), and the engine seeder hook `IPromptKvSeeder` (#1590, `feature/chunk-apply-seeder`).
- Recurrent/hybrid models are refused by design (`chunk_model_unsupported`, `ChunkCacheRuntime`). Phase T research (recurrent state) follows the dense work.

## Proposed scope (dense models only)
1. B3: CPU applied path in the server (needs `--no-paged` today), per-request opt-in AND server flag.
2. B4: Vulkan, F16 KV target.
3. B5: cost model (re-rotation + selective recompute must beat plain prefill on TTFT).
4. Auto-chunking at chat-message boundaries, server-side, no client annotations, used only past the matched prefix.

## Experiment cell (runs first; no code)
Multi-turn agent transcripts with an edited system prompt and/or tool list; full prefill vs reuse at 5 / 10 / 20 / 40 % recompute; exact-match and KL; TwIL-8B (dense Granite) included; plus the TTFT cost check. Open question it answers: after a system-prompt edit every message chunk is stale and assistant replies encode the old prompt, so the 20 % bar measured on code-context chunks may not carry over.

## Overlap
#1780 (seed from a protected entry) and #1781 (Vulkan entry growth past the 1,024 headroom) change `PrefixCache` / `TextGenerator` adoption, as does #1590. Coordinate before touching either; #1723-#1730 (Vulkan prefill, block-granular trie) also apply.

Default: stays `exact`.
