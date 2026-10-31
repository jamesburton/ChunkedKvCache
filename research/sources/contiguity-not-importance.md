# Contiguity, Not Importance: Budgeted Repair of Stale KV Caches After Document Edits (arXiv 2609.17983)

- URL: https://arxiv.org/abs/2609.17983 (HTML read: https://arxiv.org/html/2609.17983)
- Authors: Mingyang Mao, Wyatt Mackey, Xiaomin Lin. 16 Sep 2026, arXiv (cs.AI). No code link.
- Status: **VERIFIED-FULLTEXT**

## Setup
- An in-place cache is repaired after an edit. The edited span is always recomputed, plus K downstream positions (K in {8,16,32,64}; K=32 is the primary budget).
- Selectors compared: EditLocal (the K positions right after the edit), Attention (ProphetKV-style), CacheBlend (layer-2 KV deviation), **Structural (delimiter tokens nearest the span)**, Random, and the oracles CausalOracle and CarrierWindow.
- Models: Llama-3.1-8B-Instruct, Qwen3-8B, Mistral-7B-v0.3. Data: about 5K tokens of HotpotQA paragraphs with one synthetic record; "direct" vs "derived" (two-hop) questions.

## Key numbers (derived, K=32, margin recovery)
- EditLocal: 0.993 / 1.007 / 0.937 (Llama/Qwen/Mistral). Attention: 0.533 / 0.015 / 0.019. CacheBlend: 0.238 / 0.076 / 0.012. **Structural: 0.126 / 0.008 / 0.012.** Random: about 0.
- Repair is 13-21x faster than full re-prefill.
- Positions ranked by a causal oracle recover 0.92-0.97 when transplanted, but only 0.008-0.209 under actual recomputation, because scattered positions inherit nearby staleness.
- **"Adjacency is load-bearing"**: when the answer-carrying text is 250 or more tokens downstream, EditLocal falls to 0.01-0.09.

## For our plan
- This is the direct prior for **E7 (incremental re-encode)**, so EditLocal(K=32) becomes a mandatory baseline.
- In code, a caller of an edited function is usually far from the edit, often in another file. That is exactly the regime where EditLocal collapses. The open question is graph-guided repair windows placed at **dependent sites** (call sites, uses) rather than next to the edit.
- Caution for E4: the naive "Structural" selector (delimiters) failed badly here. Our selector must be graph-role-based (definitions and uses linked to the edit or the query), and it should recompute contiguous runs, not scattered tokens.
- The paper suggests, but does not test, a window spanning the path from the edit to the carrier text. That is still open.
