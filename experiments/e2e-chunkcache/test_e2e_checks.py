"""Unit tests of the e2e check functions over canned responses (no server, no model).

Run: python -I -m unittest experiments/e2e-chunkcache/test_e2e_checks.py   (from the repo root; the test adds its own dir)
The E2E_MODULE environment variable points the tests at a mutated copy of e2e.py (mutant runs).
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_path = os.environ.get("E2E_MODULE") or str(HERE / "e2e.py")
_spec = importlib.util.spec_from_file_location("e2e_under_test", _path)
e2e = importlib.util.module_from_spec(_spec)
sys.modules["e2e_under_test"] = e2e
_spec.loader.exec_module(e2e)


def report(prompt=1000, prefix=0, approx=0, reused=0, prefilled=None, hit=3, miss=2, ignored=0, prefix_chunks=0,
           chunk_reused_plan=None, policy="shadow", predicted=40.0, full=90.0, per_chunk=None):
    if prefilled is None:
        prefilled = prompt - prefix - approx - reused
    r = {"v": 1, "policy_requested": policy, "policy_applied": "exact", "reason": None,
         "chunks": {"annotated": prefix_chunks + hit + miss + ignored, "prefix": prefix_chunks, "hit": hit, "miss": miss, "ignored": ignored},
         "tokens": {"prompt": prompt, "prefix_reused": prefix, "prefix_reused_approx": approx, "chunk_reused": reused,
                    "chunk_recomputed": 0, "prefilled": prefilled, "encode_queued": 0},
         "warnings": []}
    if chunk_reused_plan is not None:
        r["plan"] = {"selector": "chunk_starts", "budget": 0.05,
                     "tokens": {"prompt": prompt, "prefix_reused": prefix, "prefix_reused_approx": 0,
                                "chunk_reused": chunk_reused_plan, "chunk_recomputed": 5,
                                "prefilled": prompt - prefix - chunk_reused_plan, "encode_queued": 0},
                     "predicted_ttft_ms": predicted, "full_prefill_estimate_ms": full}
    if per_chunk is not None:
        r["per_chunk"] = per_chunk
    return r


def rec(label, tokens, cached=0, rep=None):
    return {"label": label, "tokens": tokens, "cached_tokens": cached, "report": rep}


class ShadowCounts(unittest.TestCase):
    def test_shadow_counts_match_expected_hits(self):
        expect = {"hit": 3, "miss": 2, "ignored": 0, "hit_tokens": 600}
        good = report(hit=3, miss=2, chunk_reused_plan=600)
        self.assertTrue(e2e.check_shadow_counts("A3", good, expect)["passed"])
        # hit count wrong
        self.assertFalse(e2e.check_shadow_counts("A3", report(hit=2, miss=3, chunk_reused_plan=600), expect)["passed"])
        # miss wrong only
        self.assertFalse(e2e.check_shadow_counts("A3", report(hit=3, miss=1, chunk_reused_plan=600), expect)["passed"])
        # plan reuse tokens wrong
        self.assertFalse(e2e.check_shadow_counts("A3", report(hit=3, miss=2, chunk_reused_plan=500), expect)["passed"])
        # prediction not below the full-prefill estimate
        self.assertFalse(e2e.check_shadow_counts("A3", report(hit=3, miss=2, chunk_reused_plan=600, predicted=90.0, full=90.0), expect)["passed"])
        # ignored must be 0
        self.assertFalse(e2e.check_shadow_counts("A3", report(hit=3, miss=2, ignored=1, chunk_reused_plan=600), expect)["passed"])

    def test_shadow_per_chunk_status_matches_stored(self):
        expect = {"hit": 1, "miss": 1, "ignored": 0, "hit_tokens": 100}
        per = [{"id": "a", "status": "hit", "why": None}, {"id": "b", "status": "miss", "why": None}]
        rep = report(hit=1, miss=1, chunk_reused_plan=100, per_chunk=per)
        self.assertTrue(e2e.check_shadow_counts("A3", rep, expect, {"a": True, "b": False})["passed"])
        self.assertFalse(e2e.check_shadow_counts("A3", rep, expect, {"a": False, "b": False})["passed"])


class Neutrality(unittest.TestCase):
    def runs(self, **override):
        base = [rec("plain1", ["a", "b", "c"], 0), rec("ann1", ["a", "b", "c"], 0, report(hit=0, miss=0)),
                rec("plain2", ["a", "b", "c"], 0), rec("ann2", ["a", "b", "c"], 0, report(hit=0, miss=0)),
                rec("shadow_warm", ["a", "b", "c"], 0, report(hit=0, miss=0)), rec("exact_warm", ["a", "b", "c"], 0, report(hit=0, miss=0))]
        return [override.get(r["label"], r) for r in base]

    def test_exact_neutrality_passes_when_identical(self):
        r = e2e.check_exact_neutrality("A4", self.runs())
        self.assertTrue(r["passed"])
        self.assertFalse(r["void"])

    def test_exact_neutrality_detects_token_difference(self):
        # same text, different token ids: ["ab","c"] vs ["a","bc"]  (a text comparison would call these equal)
        r = e2e.check_exact_neutrality("A4", self.runs(ann1=rec("ann1", ["ab", "c"], 0, report(hit=0, miss=0))))
        # plain tokens are a,b,c; annotated differ in ids -> fail
        self.assertFalse(r["passed"])
        base = [rec("plain1", ["a", "bc"], 0), rec("ann1", ["ab", "c"], 0), rec("plain2", ["a", "bc"], 0), rec("ann2", ["a", "bc"], 0)]
        self.assertFalse(e2e.check_exact_neutrality("A4", base)["passed"])

    def test_exact_neutrality_detects_cached_tokens_difference(self):
        runs = self.runs(ann2=rec("ann2", ["a", "b", "c"], 7, report(hit=0, miss=0)))
        self.assertFalse(e2e.check_exact_neutrality("A4", runs)["passed"])

    def test_exact_neutrality_void_when_plain_baseline_nondeterministic(self):
        runs = self.runs(plain2=rec("plain2", ["a", "b", "x"], 0))
        r = e2e.check_exact_neutrality("A4", runs)
        self.assertTrue(r["void"])
        self.assertFalse(r["passed"])

    def test_exact_neutrality_fails_when_chunks_were_applied(self):
        applied = report(hit=1, miss=0, reused=50)
        runs = self.runs(ann1=rec("ann1", ["a", "b", "c"], 0, applied))
        self.assertFalse(e2e.check_exact_neutrality("A4", runs)["passed"])


class Partition(unittest.TestCase):
    def test_partition_holds(self):
        self.assertTrue(e2e.check_partition("P", [report(prompt=1000, prefix=200, reused=300), report(prompt=500)])["passed"])

    def test_partition_detects_prefilled_ignored(self):
        # prompt 1000 but prefix 200 + reused 300 + prefilled 400: the 100 missing tokens are only visible if prefilled counts
        bad = report(prompt=1000, prefix=200, reused=300, prefilled=400)
        self.assertFalse(e2e.check_partition("P", [bad])["passed"])

    def test_partition_detects_chunk_counts(self):
        bad = report()
        bad["chunks"]["annotated"] = 99
        self.assertFalse(e2e.check_partition("P", [bad])["passed"])

    def test_partition_detects_recomputed_exceeding_reused(self):
        bad = report(reused=10)
        bad["tokens"]["chunk_recomputed"] = 11
        bad["tokens"]["prefilled"] = 990
        self.assertFalse(e2e.check_partition("P", [bad])["passed"])


PROM_BEFORE = """# HELP x
dotllm_chunk_cache_chunks_total{status="hit"} 4
dotllm_chunk_cache_chunks_total{status="miss"} 1
dotllm_chunk_cache_tokens_total{kind="prefilled"} 100
"""
PROM_AFTER = """dotllm_chunk_cache_chunks_total{status="hit"} 11
dotllm_chunk_cache_chunks_total{status="miss"} 3
dotllm_chunk_cache_chunks_total{status="prefix"} 0
dotllm_chunk_cache_chunks_total{status="ignored"} 0
dotllm_chunk_cache_tokens_total{kind="prefilled"} 160
dotllm_chunk_cache_tokens_total{kind="chunk_reused"} 0
"""


class Metrics(unittest.TestCase):
    def test_metrics_counter_delta(self):
        rep = {"hit": 7, "miss": 2, "prefix": 0, "ignored": 0, "tokens": {"prefilled": 60, "chunk_reused": 0}}
        self.assertTrue(e2e.check_metrics_delta("A12", PROM_BEFORE, PROM_AFTER, rep)["passed"])
        wrong = dict(rep, hit=6)
        self.assertFalse(e2e.check_metrics_delta("A12", PROM_BEFORE, PROM_AFTER, wrong)["passed"])
        missing_kind = dict(rep, tokens={"prefilled": 60, "chunk_reused": 0, "encode_queued": 0})
        self.assertFalse(e2e.check_metrics_delta("A12", PROM_BEFORE, PROM_AFTER, missing_kind)["passed"])

    def test_metrics_namespace_label_fails(self):
        leaky = PROM_AFTER + 'dotllm_chunk_cache_chunks_total{status="hit",namespace="k-abc"} 1\n'
        rep = {"hit": 7, "miss": 2, "prefix": 0, "ignored": 0, "tokens": {"prefilled": 60}}
        self.assertFalse(e2e.check_metrics_delta("A12", PROM_BEFORE, leaky, rep)["passed"])


class Isolation(unittest.TestCase):
    def test_namespace_isolation_detects_cross_hit(self):
        a = report(hit=2, miss=0)
        b_ok = report(hit=0, miss=2)
        b_leak = report(hit=2, miss=0)
        self.assertTrue(e2e.check_namespace_isolation("A11", {"A": a, "B": b_ok}, {"A": 2, "B": 0})["passed"])
        self.assertFalse(e2e.check_namespace_isolation("A11", {"A": a, "B": b_leak}, {"A": 2, "B": 0})["passed"])
        # B's report is the one that leaks while A's is clean: reading A twice would not notice
        self.assertFalse(e2e.check_namespace_isolation("A11", {"A": report(hit=0, miss=2), "B": b_leak}, {"A": 0, "B": 0})["passed"])

    def test_namespace_leaks_found(self):
        ns = e2e.derived_namespace("k" * 40)
        self.assertEqual(e2e.namespace_leaks(["nothing here", f"log {ns} line"], [ns]), [ns])
        self.assertEqual(e2e.namespace_leaks(["clean"], [ns]), [])


class Manifest(unittest.TestCase):
    def sel(self, text_a, text_b):
        def chunk(i, t, start, end):
            return {"id": f"f.cs:{start}-{end}@0", "hash": e2e.sha256_hash(t), "tokens": 40, "text": t, "start_line": start,
                    "end_line": end, "key": f"k{i}"}
        return [{"path": "src/f.cs", "chunks": [chunk(1, text_a, 1, 2), chunk(2, text_b, 3, 4)]}]

    def test_manifest_offsets_are_utf8_bytes(self):
        a = "café éé\n"        # four non-ASCII-adjacent characters: 2 bytes each in UTF-8, 1 UTF-16 unit
        b = "int x = 1;\n"
        prompt, placed = e2e.build_prompt(self.sel(a, b))
        entries = e2e.manifest_entries(placed, 1)
        raw = prompt.encode("utf-8")
        for e, p in zip(entries, [a, b]):
            s, t = e["at"]["start"], e["at"]["end"]
            self.assertEqual(raw[s:t].decode("utf-8"), p)  # the byte range is exactly the span text
            self.assertEqual(e["hash"], e2e.sha256_hash(p))
        # the second span starts after the multi-byte text: byte offset exceeds the character offset
        self.assertGreater(entries[1]["at"]["start"], placed[1]["char_start"])

    def test_short_chunks_are_not_annotated(self):
        sel = self.sel("a" * 10, "b" * 10)
        sel[0]["chunks"][0]["tokens"] = 5
        prompt, placed = e2e.build_prompt(sel)
        self.assertEqual(len(placed), 1)
        self.assertIn("a" * 10, prompt)  # still in the prompt text


if __name__ == "__main__":
    unittest.main()
