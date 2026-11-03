#!/usr/bin/env python3
"""Verifies the chunk-cache wire contract fixtures (spec 2026-11-02, section 5).

Usage: python -I check.py [fixture_dir] [--update]
  fixture_dir  defaults to the folder holding this script
  --update     after every semantic check passes, rewrite fixtures.sha256

What it recomputes (nothing is trusted from the files):
  * every inline / manifest hash = "sha256:" + hex of the UTF-8 bytes of the DECODED span text
  * every `at.start` / `at.end` is a UTF-8 byte offset on a character boundary, end exclusive
    (the defective spans of bad-span.json are checked to be defective in exactly the declared way)
  * a reference parse of each request fixture reproduces expected.json (warning codes + counts,
    strict error, accepted span ids)
  * response fixtures: prompt = prefix_reused + prefix_reused_approx + chunk_reused + prefilled,
    chunk_recomputed <= chunk_reused, chunks.annotated = prefix + hit + miss + ignored,
    usage / timings exact counters agree with chunk_cache.tokens
  * capabilities.json shape; fixtures.sha256 matches the bytes on disk
"""
import hashlib
import json
import sys
from pathlib import Path

ALLOWED_EXTRA = {"README.md", "check.py", "fixtures.sha256", ".gitattributes"}
SPAN_CODE = "chunk_span_invalid"
KIND_CODE = {
    "hash_mismatch": "chunk_hash_mismatch",
    "multibyte_boundary": SPAN_CODE,
    "range_invalid": SPAN_CODE,
    "overlap": SPAN_CODE,
    "part_out_of_range": SPAN_CODE,
    "non_text": SPAN_CODE,
}
POLICIES = {"exact", "shadow", "balanced", "fast", "auto"}
failures = []


def fail(msg):
    failures.append(msg)


def sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def load(path: Path):
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        fail(f"{path.name}: cannot load: {e}")
        return None


def parts_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    if isinstance(c, list):
        return c
    return []


def on_boundary(b: bytes, i: int) -> bool:
    return i == 0 or i == len(b) or (b[i] & 0xC0) != 0x80


# ---------------------------------------------------------------- requests
def reference_parse(req):
    """Minimal reference of spec 5.1-5.3/5.8 span validation. Returns (spans, conflict)."""
    spans = []
    messages = req.get("messages", [])
    inline = []
    for mi, msg in enumerate(messages):
        c = msg.get("content")
        if isinstance(c, list):
            for pi, part in enumerate(c):
                if isinstance(part, dict) and "chunk" in part:
                    inline.append((mi, pi, part["chunk"]))
    cc = req.get("chunk_cache")
    manifest = cc.get("chunks") if isinstance(cc, dict) else None
    conflict = bool(inline) and bool(manifest)

    entries = []  # (label, mi, pi, start, end, chunkobj)
    for mi, pi, ch in inline:
        entries.append(("inline", mi, pi, None, None, ch))
    for ch in manifest or []:
        at = ch["at"]
        entries.append(("manifest", at["message"], at["part"], at.get("start"), at.get("end"), ch))

    taken = {}  # (mi, pi) -> list of (start, end) already accepted
    for idx, (label, mi, pi, start, end, ch) in enumerate(entries):
        span = {"i": idx, "id": ch["id"], "kinds": [], "label": label}
        spans.append(span)
        v = ch.get("v", cc.get("v") if isinstance(cc, dict) else None)
        if v != 1:
            fail(f"span {ch['id']}: v must be 1, got {v!r}")
        if not (isinstance(ch["id"], str) and 0 < len(ch["id"]) <= 256):
            fail(f"span {ch['id']!r}: id must be 1..256 chars")
        if not (0 <= mi < len(messages)):
            span["kinds"].append("part_out_of_range")
            continue
        parts = parts_of(messages[mi])
        if not (0 <= pi < len(parts)):
            span["kinds"].append("part_out_of_range")
            continue
        part = parts[pi]
        if part.get("type") != "text":
            span["kinds"].append("non_text")
            continue
        b = part["text"].encode("utf-8")
        s = 0 if start is None else start
        e = len(b) if end is None else end
        if not (0 <= s < e <= len(b)):
            span["kinds"].append("range_invalid")
            continue
        if not (on_boundary(b, s) and on_boundary(b, e)):
            span["kinds"].append("multibyte_boundary")
            continue
        span["start"], span["end"], span["bytes"] = s, e, b[s:e]
        if any(s < e2 and s2 < e for s2, e2 in taken.get((mi, pi), [])):
            span["kinds"].append("overlap")  # the LATER span of the pair (manifest order) is dropped
        else:
            taken.setdefault((mi, pi), []).append((s, e))
        if sha(b[s:e]) != ch["hash"]:
            span["kinds"].append("hash_mismatch")
    return spans, conflict


def check_request(name, req, exp):
    spans, conflict = reference_parse(req)
    got_defects = [{"chunk": s["i"], "kind": k} for s in spans for k in s["kinds"]]
    if got_defects != exp.get("defects", []):
        fail(f"{name}: defects {got_defects} != expected {exp.get('defects', [])}")
    codes = []
    if conflict:
        codes.append("chunk_manifest_conflict")
    for d in got_defects:
        codes.append(KIND_CODE[d["kind"]])
    warnings = []
    for c in codes:
        for w in warnings:
            if w["code"] == c:
                w["count"] += 1
                break
        else:
            warnings.append({"code": c, "count": 1})
    if warnings != exp["warnings"]:
        fail(f"{name}: warnings {warnings} != expected {exp['warnings']}")
    strict = None
    if codes:
        if len(set(codes)) != 1:
            fail(f"{name}: fixture mixes several error codes {sorted(set(codes))}; strict code would be ambiguous")
        strict = {"status": 400, "type": "invalid_request_error", "code": codes[0]}
    if strict != exp["strict_error"]:
        fail(f"{name}: strict_error {strict} != expected {exp['strict_error']}")
    accepted = [] if conflict else [s["id"] for s in spans if not s["kinds"]]
    if accepted != exp["accepted_ids"]:
        fail(f"{name}: accepted ids {accepted} != expected {exp['accepted_ids']}")
    # extra pins
    for i in exp.get("utf16_discriminating_chunks", []):
        at = req["chunk_cache"]["chunks"][i]["at"]
        full = parts_of(req["messages"][at["message"]])[at["part"]]["text"]
        b8 = at["start"]
        prefix = full.encode("utf-8")[:b8].decode("utf-8")
        u16 = len(prefix.encode("utf-16-le")) // 2
        if u16 == b8 or len(prefix) == b8 or u16 == len(prefix):
            fail(f"{name}: chunk {i} start {b8} is not discriminating (utf16={u16}, chars={len(prefix)})")
    lv = exp.get("lf_variant")
    if lv:
        s = spans[lv["chunk"]]
        text = s["bytes"].decode("utf-8")
        if "\r\n" not in text:
            fail(f"{name}: chunk {lv['chunk']} has no CRLF")
        lf = sha(text.replace("\r\n", "\n").encode("utf-8"))
        if lf != lv["lf_hash"] or lf == sha(s["bytes"]):
            fail(f"{name}: lf_variant hash wrong or equal to the CRLF hash")


# --------------------------------------------------------------- responses
TOKEN_KEYS = ["prompt", "prefix_reused", "prefix_reused_approx", "chunk_reused", "chunk_recomputed", "prefilled", "encode_queued"]


def check_tokens(name, where, t):
    for k in TOKEN_KEYS:
        if not (isinstance(t.get(k), int) and t[k] >= 0):
            fail(f"{name}: {where}.{k} must be a non-negative int")
            return
    s = t["prefix_reused"] + t["prefix_reused_approx"] + t["chunk_reused"] + t["prefilled"]
    if t["prompt"] != s:
        fail(f"{name}: {where}: prompt {t['prompt']} != prefix_reused+prefix_reused_approx+chunk_reused+prefilled = {s}")
    if t["chunk_recomputed"] > t["chunk_reused"]:
        fail(f"{name}: {where}: chunk_recomputed {t['chunk_recomputed']} > chunk_reused {t['chunk_reused']}")


def check_response(name, obj):
    cc = obj.get("chunk_cache")
    if not isinstance(cc, dict):
        fail(f"{name}: missing top-level chunk_cache")
        return
    if cc.get("v") != 1:
        fail(f"{name}: chunk_cache.v must be 1")
    if cc.get("policy_requested") not in POLICIES or cc.get("policy_applied") not in POLICIES:
        fail(f"{name}: bad policy_requested / policy_applied")
    ch = cc.get("chunks", {})
    try:
        if ch["annotated"] != ch["prefix"] + ch["hit"] + ch["miss"] + ch["ignored"]:
            fail(f"{name}: chunks.annotated != prefix+hit+miss+ignored")
    except KeyError as e:
        fail(f"{name}: chunks missing {e}")
    t = cc.get("tokens", {})
    check_tokens(name, "tokens", t)
    if cc.get("policy_requested") == "shadow":
        if cc.get("policy_applied") != "exact":
            fail(f"{name}: shadow must apply exact")
        plan = cc.get("plan")
        if not isinstance(plan, dict):
            fail(f"{name}: shadow response needs plan")
        else:
            check_tokens(name, "plan.tokens", plan.get("tokens", {}))
            if plan.get("tokens", {}).get("prompt") != t.get("prompt"):
                fail(f"{name}: plan.tokens.prompt != tokens.prompt")
    elif "plan" in cc:
        fail(f"{name}: plan only under shadow")
    if cc.get("policy_applied") == "exact" and (t.get("chunk_reused") or t.get("prefix_reused_approx")):
        fail(f"{name}: exact applied but reuse counted")
    u = obj.get("usage", {})
    if "prompt_tokens" in u and u["prompt_tokens"] != t.get("prompt"):
        fail(f"{name}: usage.prompt_tokens != tokens.prompt")
    if "prompt_tokens_details" in u and u["prompt_tokens_details"].get("cached_tokens") != t.get("prefix_reused"):
        fail(f"{name}: cached_tokens must equal tokens.prefix_reused (exact rows only)")
    if "cache_read_input_tokens" in u and u["cache_read_input_tokens"] != t.get("prefix_reused"):
        fail(f"{name}: cache_read_input_tokens must equal tokens.prefix_reused")
    tm = obj.get("timings")
    if tm is not None:
        if tm.get("cache_n") != t.get("prefix_reused"):
            fail(f"{name}: timings.cache_n must equal tokens.prefix_reused")
        if tm.get("chunk_recomputed_n", 0) > tm.get("chunk_n", 0):
            fail(f"{name}: timings.chunk_recomputed_n > chunk_n")


def check_capabilities(name, c):
    need = {"versions": list, "policies": list, "selectors": list, "wire_chunkers": list, "auto_validated": list,
            "model": dict, "store": dict, "max_chunks_per_request": int}
    for k, ty in need.items():
        if not isinstance(c.get(k), ty):
            fail(f"{name}: {k} missing or not {ty.__name__}")
            return
    if 1 not in c["versions"]:
        fail(f"{name}: versions must contain 1")
    if not set(c["policies"]) <= POLICIES or "exact" not in c["policies"]:
        fail(f"{name}: policies")
    if "chunk_starts" not in c["selectors"] or not set(c["selectors"]) <= {"chunk_starts", "query_relevance"}:
        fail(f"{name}: selectors")
    if "fixed-512" in c["wire_chunkers"]:
        fail(f"{name}: fixed-512 is not text-first and must not be listed")
    if c["auto_validated"] != []:
        fail(f"{name}: auto_validated must be empty today")
    if not {"id", "supported", "reason"} <= set(c["model"]):
        fail(f"{name}: model keys")
    if not {"entries", "bytes", "budget_bytes", "dtype"} <= set(c["store"]):
        fail(f"{name}: store keys")


# -------------------------------------------------------------------- main
def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    update = "--update" in argv
    d = Path(args[0]).resolve() if args else Path(__file__).resolve().parent
    if not d.is_dir():
        print(f"FAIL {d}: not a folder")
        return 1
    exp_path = d / "expected.json"
    if not exp_path.exists():
        print(f"FAIL no fixtures: {exp_path} missing")
        return 1
    expected = load(exp_path)
    if expected is None:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    reqs, resps, cap = expected["requests"], expected["responses"], expected["capabilities"]
    listed = set(reqs) | set(resps) | {cap, "expected.json"}
    on_disk = {p.name for p in d.iterdir() if p.is_file()}
    for m in sorted(listed - on_disk):
        fail(f"{m}: listed but missing")
    for x in sorted(on_disk - listed - ALLOWED_EXTRA):
        fail(f"{x}: present but not listed in expected.json")
    n = 0
    for name, exp in reqs.items():
        p = d / name
        if not p.exists():
            continue
        req = load(p)
        if req is None:
            continue
        n += 1
        check_request(name, req, exp)
        for needle in exp.get("raw_contains", []):
            if needle.encode() not in p.read_bytes():
                fail(f"{name}: file must contain the raw escape {needle}")
    for name in resps:
        p = d / name
        if p.exists():
            o = load(p)
            if o is not None:
                n += 1
                check_response(name, o)
    if (d / cap).exists():
        o = load(d / cap)
        if o is not None:
            n += 1
            check_capabilities(cap, o)

    sums = {name: hashlib.sha256((d / name).read_bytes()).hexdigest() for name in sorted(listed) if (d / name).exists()}
    text = "".join(f"{h}  {name}\n" for name, h in sums.items())
    sp = d / "fixtures.sha256"
    if update and not failures:
        sp.write_bytes(text.encode())
    elif not sp.exists():
        fail("fixtures.sha256 missing (run with --update once the semantic checks pass)")
    elif sp.read_bytes().decode() != text:
        fail("fixtures.sha256 does not match the files on disk")

    if failures:
        print("\n".join("FAIL " + f for f in failures))
        return 1
    print(f"OK {n} fixtures")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
