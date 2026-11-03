# Server: locate `chunk_cache` spans in the rendered prompt (draft)

> **Status: DRAFT, not filed.** Lane S, plan Task 11. Refs #1543 (Lane S lead, `09-server-behaviour-pin.md`) and #1542
> (umbrella). Our side files nothing and pushes nothing; dotllm-97 / the user decide when and whether it is filed.
> **Packaging: Tasks 10, 11 and 13 ship together as one PR** (the flag must do something when it is merged). This text
> becomes that PR's span-location section, or a sub-issue of #1543. Branch `feature/chunk-cache-server`, worktree
> `C:\Development\dotLLM\.claude\worktrees\chunk-cache-server`: `2b53f3b7` (parser follow-up, rulings 33 and 34) and
> `0bc4aab2` (span location) and `68485327` (review fix round), on top of Task 10 (`4e3f8257`).

## Title

Server: `chunk_cache` wire convention: locate annotated spans in the rendered chat prompt (template-altered spans ignored)

## Body

Refs #1543, #1542.

The parser (previous part) accepts spans as positions in the converter's `ChatMessage` list. Reuse needs them as
positions in the **rendered prompt**: the string the chat template produces, which the server tokenises. Templates do
not always copy content verbatim. Task 9 pinned these facts:
- Llama-3.1 trims user, assistant and system content, and JSON-encodes tool content (`| tojson`).
- Qwen3-4B-Instruct-2507 renders content verbatim.
- The #1339 guard inserts U+FDD0 into special-token spellings in caller text.

So each span needs checking before the server says where it is. This part adds that check. It reads the request and
the render only: it does not touch the store or reuse anything.

What it adds:

- **`ChunkSpanLocator.Locate(template, messages, options, rendered, spans, engineMessageOffset)`**
  (`src/DotLLM.Server/ChunkCache/ChunkSpanLocator.cs`, `internal`) → `LocatedSpans(Located, Warnings)`, with
  `LocatedSpan(Span, RenderedStartChar, RenderedEndChar)` in UTF-16 chars into the rendered string (BOS text included).
  The endpoint passes the prompt it has already rendered, so locating adds sentinel renders only.
- **Sentinel render.** Every span is replaced by a sentinel: `U+E000`, a fresh GUID per request, the span index, the
  probe characters `"` `\` LF, then `U+E001`. The template is rendered once with all of them. A span is located only
  when:
  - its sentinel comes out intact, exactly once; and
  - putting the span texts back reproduces the real prompt around it exactly.

  Otherwise the warning is `chunk_template_altered` and the span is plain text.
  - Caller text cannot forge a sentinel: a forged copy makes it appear twice.
  - The probe characters break the sentinel under any escaping filter, so every Llama-3.1 tool-result span is
    altered, even one whose own characters need no escaping.
  - Trimming is caught by the comparison.
- **Markers (ruling 20).** The template marks caller text as a whole message, and the comparison skips U+FDD0 on both
  sides. **Stripping the U+FDD0 markers from a located range gives the span text**, and the range starts and ends on
  span characters. The range is not always `MarkUntrustedSpecials(text)`: a special spelling that crosses the span's
  end leaves its marker inside the range (`q <|im_` of `q <|im_end|> z` is located as `q <`, U+FDD0, `|im_`). A span
  that itself contains U+FDD0 is ignored, because encode drops the marker (the walk also relies on it).
- **Assistant turns.** The guard leaves the template's reasoning tags live (unmarked) in assistant content. A Qwen3
  assistant span holding `<think>` is therefore located by characters, but its tokens differ from the chunk's: a
  control token in the prompt, plain text in the store. The token check in the `exact` / `shadow` part is what rejects
  it.
  - Qwen3 rewrites assistant content that holds `</think>`. A span in the reasoning part of a historical turn, or one
    that starts with the stripped newlines, is altered.
  - Llama-3.1 trims assistant content like user content.
- **Attribution.** The comparison walks from the start and from the end. A span in the common prefix or suffix is
  located with exact offsets. When the two strings differ, the first and last unproven spans are ignored, and the spans
  between them are tried again in another render. This is conservative: a span is never located on a guess.
- **Bounded work.** At most 4 sentinel renders per request, whatever the number of spans. Each pass is linear in the
  prompt length; spans cost O(n log n). There is never one render per span.
- **Profile system prompt (ruling 31).** The parser's engine indices are counted before
  `ProfileSystemPrompt.Apply`. The caller passes the offset as a required argument. A span that is not at its stated
  position is `chunk_span_invalid`, never located elsewhere.
- **Never throws on request content.** If a template throws, drops content or duplicates it on the sentinel render,
  every span it covers is ignored. Out-of-range positions, overlaps and lone surrogates are handled without a throw.
- **Parser follow-up (contract rulings 33, 34).** The parser now treats these as `chunk_annotation_malformed` (a
  warning with the default applied, or 400 when strict): an unknown `report` or `on_miss` string, and a `query.message`
  that is not the index of a request message. A test pins ruling 33's check order: eligibility comes after the id and
  before the range, and an ineligible span reserves no range.
- **Docs.** `docs/CHUNK_CACHE.md` gains a span-location section: the method, a per-template table, attribution, cost and
  the offset. Its validation section now follows rulings 33 and 34. `docs/SERVER.md` is unchanged: nothing
  user-visible changes until the `exact` / `shadow` part wires the endpoints.

Character equality is not token equality at a span's edges. BPE can merge across a span boundary, SentencePiece adds a
leading space, and assistant reasoning tags stay live. The `exact` / `shadow` part therefore checks token ids over the
located range before it counts a span as reusable.

## Acceptance criteria

- [ ] PR targets `dev`, never `main`; ships together with parsing and `exact` / `shadow` (Tasks 10, 13); `Closes #N`
      closed by hand.
- [ ] Flag off: nothing calls the locator (it is reached only through a non-null parse).
- [ ] With the repo's real Qwen3-4B-Instruct-2507 and Llama-3.1 templates (built as `ServerStartup` builds them, with
      the guard tokenizer):
  - [ ] a Qwen3 mid-part span, a Qwen3 tool-result span and a Llama-3.1 span after a glue line are located;
  - [ ] Llama-3.1 edge spans touched by the trim are `chunk_template_altered`;
  - [ ] every Llama-3.1 tool-result span is altered, including a plain-words one;
  - [ ] good spans next to altered ones are still located.
- [ ] Stripping U+FDD0 from every located range gives the span text, and the range starts and ends on span characters.
      A property test checks this over random conversations with non-BMP text, CRLF, quotes, backslashes and special
      spellings: on Qwen3 every span is located; on Llama-3.1 every user or system span is located and every tool span
      is altered.
- [ ] A special spelling crossing a span's end leaves its marker inside the range; one crossing the span's start
      leaves it just before the range (not in it).
- [ ] Assistant turns:
  - [ ] Qwen3: a span holding a live `<think>` is located (no marker in the range); a span in the reasoning part, or
        one starting with the stripped newlines, is altered.
  - [ ] Llama-3.1: a trimmed edge span is altered and a mid span located; with tools listed, the first user message is
        moved and a mid span in it is still located.
- [ ] **Token check (the `exact` / `shadow` part, Task 13):** an assistant span with a live `<think>` is located by the
      locator but fails the token-id check, so it is not counted reusable (`AssistantSpanWithThinkTag_…`); so does a
      span with a special spelling crossing its edge.
- [ ] A span containing `<think>` / `<|im_end|>` is located through the marked comparison; a span with a caller U+FDD0
      is ignored; a forged sentinel in caller text never yields a location.
- [ ] Anthropic end to end (parser → converter → render → locator): a text-block span is located; a tool-result span is
      located on Qwen3 and altered on Llama-3.1.
- [ ] Profile offset: with the offset the span is located; without it the span is `chunk_span_invalid`.
- [ ] Hostile input never throws: a throwing, dropping or duplicating template, inconsistent positions, overlaps, a
      lone surrogate.
- [ ] Cost bound (render counts, no wall-clock asserts): 4,096 spans on a 4 MiB message use one sentinel render; 4,096
      trimmed Llama-3.1 edge spans stop at the render cap (4).
- [ ] Parser: unknown `report` / `on_miss` values and an out-of-range `query.message` are malformed (strict 400) with
      the default applied; known values give no warning; eligibility is checked after the id and before the range.
- [ ] No new JSON DTO or `JsonSerializerContext`; new types `internal`.
- [ ] Correctness tests shown to fail against mutants (table below, also in the PR body).

## Mutant evidence

Run in a `git archive` copy (never the live worktree), `--filter FullyQualifiedName~Server.ChunkCache`, Release, CPU,
`DOTLLM_SKIP_VULKAN=1`. Final run on the review fix round `68485327`: baseline 155 / 155, **20 mutants, 20 killed**
(first run on `0bc4aab2`: 19 / 19). The plan's three named mutants are L1–L3. Red evidence: a stub locator that locates
nothing (L0) fails 31 tests; the parser tests failed 9 before the follow-up was implemented. The "killed by" column
lists the first-run tests; the fix-round tests add kills (the log has them).

| mutant | change | killed by |
|---|---|---|
| P1 | unknown `report` falls back silently | `UnknownOptionValue_IsMalformed_DefaultApplies_StrictIs400` |
| P2 | unknown `on_miss` falls back silently | `UnknownOptionValue_…` |
| P3 | out-of-range `query.message` falls back silently | `QueryDefaultsToLastUserMessage`, `UnknownOptionValue_…` |
| P4 | eligibility checked after range / boundary | `CheckOrder_EligibilityAfterId_BeforeRange_ReservesNoRange` |
| P5 | ineligible span reserves its range (eligibility after overlap) | `CheckOrder_EligibilityAfterId_…` |
| L1 | skip the R comparison (every intact sentinel located) | 12: `Llama31_SpanAtPartEdge_…`, `Llama31_GoodSpansNextToTrimmedSpans_…`, property test, `SpecialSpellingSpan_…`, `CostBound_…` |
| L2 | compare unmarked text (U+FDD0 not skipped) | `SpecialSpellingSpan_LocatedViaMarkedText`, property test |
| L3 | offsets off by the BOS prefix | 13: every Llama-3.1 location test, property test, Anthropic end to end |
| L4 | no probe characters in the sentinel | `Llama31_ToolResultSpan_AlwaysTemplateAltered`, property test, `SentinelInUserText_…` |
| L5 | a sentinel seen twice counts | `SentinelInUserText_CannotCollide` |
| L6 | profile offset ignored | `ProfileSystemPrompt_OffsetIsAdded` |
| L7 | renders unbounded | `CostBound_ManySpans_BoundedRenders` |
| L8 | caller U+FDD0 in a span accepted | `CallerFdd0InSpan_Ignored` |
| L9 | every unproven span blamed | `Llama31_GoodSpansNextToTrimmedSpans_Located`, `CostBound_…` |
| L10 | no walk from the end | `Llama31_GoodSpansNextToTrimmedSpans_Located` |
| L11 | no blame (only broken sentinels dropped between renders) | `Llama31_GoodSpansNextToTrimmedSpans_Located` |
| L12 | engine text-at-position check removed | `InconsistentPositions_AreSpanInvalid_NotAThrow`, `ProfileSystemPrompt_OffsetIsAdded` |
| L13 | a throwing template propagates | `HostileTemplates_IgnoreSpans_NeverThrow` |
| L14 | overlapping engine spans both kept | `InconsistentPositions_…` |
| L15 | forward walk records a span's start before skipping markers (a marker right before the span) | `SpellingStraddlingSpanEdge_LocatedByCharacters` (review S1) |

Logs: `.superpowers/sdd/2026-11-01-phase-s/phase-i-task-11-mutants.log` (first run) and
`phase-i-task-11-fix-mutants.log` (fix round); script `phase-i-task-11-mutate.py`.
