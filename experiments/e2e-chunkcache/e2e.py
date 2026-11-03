#!/usr/bin/env python3
"""Phase I5 Part A: end-to-end driver for the dotLLM chunk cache (stdlib only).

Subcommands
  prep   --model M --cc-exe X --repo R --store S --out O     write O/fixtures.json (chunkcache select, tokenizer only)
  check  ID [ID ...] --base-url U ... --out O                run checks, write O/checks/<id>.json
  summarize --out O [--meta meta.json]                       merge checks into O/checks.json and O/summary.md

Every check returns {id, passed, void, expected, observed, evidence_files}. A check that cannot judge (for example a
non-deterministic plain baseline) is void, and void fails the run. No check papers over a server answer: the observed
value is always recorded.

The check logic lives in pure functions (top of file) that test_e2e_checks.py exercises over canned responses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CHUNKER = "symbol-512"
MIN_CHUNK_TOKENS = 32  # server default min_chunk_tokens: shorter chunks are not annotated (they would be `ignored`)
FILES = {  # role -> file name (a --path glob matching one file of the fixture repo)
    "F1": "ChunkNamespace.cs",   # encoded by the CLI
    "F2": "IChunkStore.cs",      # encoded by the CLI
    "F3": "ChunkStoreBusyException.cs",  # not encoded: server-write target
    "F4": "StoreStats.cs",       # prewarm target
}
SYSTEM = "You are a careful code assistant."
QUERY = "In one short sentence, what is the purpose of the code above?"


# ----------------------------------------------------------------------------------------------------------------------
# Pure functions
# ----------------------------------------------------------------------------------------------------------------------

def sha256_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def char_to_byte(text: str, char_index: int) -> int:
    """UTF-8 byte offset of a Python character index (the wire's offsets are UTF-8 bytes, ruling 17/19)."""
    return len(text[:char_index].encode("utf-8"))


def result(cid, passed, expected, observed, evidence=None, void=False, note=None):
    r = {"id": cid, "passed": bool(passed) and not void, "void": bool(void), "expected": expected,
         "observed": observed, "evidence_files": evidence or []}
    if note:
        r["note"] = note
    return r


def annotated_chunks(file_sel):
    """Chunks of a file selection that are annotated: at least MIN_CHUNK_TOKENS tokens (shorter ones stay plain text)."""
    return [c for c in file_sel["chunks"] if c["tokens"] >= MIN_CHUNK_TOKENS]


def build_prompt(file_sels):
    """One tool-result string: a glue header per file, then the file's chunk texts in document order.

    Returns (prompt, placed) where placed lists every annotated chunk with its character and UTF-8 byte range in the
    prompt. Chunks shorter than MIN_CHUNK_TOKENS are in the text but not in `placed`.
    """
    prompt = ""
    placed = []
    for fs in file_sels:
        lines = [c["start_line"] for c in fs["chunks"]] + [c["end_line"] for c in fs["chunks"]]
        prompt += f"// {fs['path']} (lines {min(lines)}-{max(lines)})\n"
        for c in fs["chunks"]:
            start = len(prompt)
            prompt += c["text"]
            if c["tokens"] >= MIN_CHUNK_TOKENS:
                placed.append({"file": fs["path"], "id": c["id"], "hash": c["hash"], "tokens": c["tokens"],
                               "text": c["text"], "char_start": start, "char_end": len(prompt),
                               "byte_start": char_to_byte(prompt, start), "byte_end": char_to_byte(prompt, len(prompt))})
    return prompt, placed


def manifest_entries(placed, message_index, wrong_hash_at=None):
    out = []
    for i, p in enumerate(placed):
        h = p["hash"]
        if wrong_hash_at == i:
            h = "sha256:" + ("0" * 64)
        out.append({"id": p["id"], "hash": h,
                    "at": {"message": message_index, "part": 0, "start": p["byte_start"], "end": p["byte_end"]},
                    "source": {"path": p["file"]}})
    return out


def build_openai(model, file_sels, policy=None, report="per_chunk", strict=False, max_tokens=16, stream=False,
                 wrong_hash_at=None, options=None, annotate=True):
    prompt, placed = build_prompt(file_sels)
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "logprobs": True,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt},
                         {"role": "user", "content": QUERY}]}
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    if annotate:
        cc = {"v": 1, "chunks": manifest_entries(placed, 1, wrong_hash_at)}
        if policy:
            cc["policy"] = policy
        if report:
            cc["report"] = report
        if strict:
            cc["strict"] = True
        if options:
            cc.update(options)
        body["chunk_cache"] = cc
    return body, placed


def build_anthropic(model, file_sels, policy="shadow", max_tokens=16, stream=True):
    """Inline `chunk` annotations on text blocks (surface 2). One block per header and per chunk."""
    blocks = []
    placed = []
    for fs in file_sels:
        lines = [c["start_line"] for c in fs["chunks"]] + [c["end_line"] for c in fs["chunks"]]
        blocks.append({"type": "text", "text": f"// {fs['path']} (lines {min(lines)}-{max(lines)})"})
        for c in fs["chunks"]:
            b = {"type": "text", "text": c["text"]}
            if c["tokens"] >= MIN_CHUNK_TOKENS:
                b["chunk"] = {"v": 1, "id": c["id"], "hash": c["hash"], "chunker": CHUNKER, "source": {"path": fs["path"]}}
                placed.append({"id": c["id"], "tokens": c["tokens"], "file": fs["path"]})
            blocks.append(b)
    blocks.append({"type": "text", "text": QUERY})
    body = {"model": model, "max_tokens": max_tokens, "temperature": 0, "stream": stream, "system": SYSTEM,
            "messages": [{"role": "user", "content": blocks}],
            "chunk_cache": {"v": 1, "policy": policy, "report": "per_chunk"}}
    return body, placed


def token_signature(record):
    """The generated token sequence (logprob tokens when the server gave them, else the content pieces)."""
    return list(record["tokens"])


def partition_problems(report):
    """Spec 5.9 partition problems of a chunk_cache report (empty list = holds)."""
    problems = []
    t = report.get("tokens") or {}
    ch = report.get("chunks") or {}
    total = t.get("prefix_reused", 0) + t.get("prefix_reused_approx", 0) + t.get("chunk_reused", 0) + t.get("prefilled", 0)
    if t.get("prompt") != total:
        problems.append(f"tokens: prompt {t.get('prompt')} != prefix {t.get('prefix_reused')} + approx "
                        f"{t.get('prefix_reused_approx')} + chunk_reused {t.get('chunk_reused')} + prefilled {t.get('prefilled')}")
    if t.get("chunk_recomputed", 0) > t.get("chunk_reused", 0):
        problems.append("chunk_recomputed > chunk_reused")
    n = ch.get("prefix", 0) + ch.get("hit", 0) + ch.get("miss", 0) + ch.get("ignored", 0)
    if ch.get("annotated") != n:
        problems.append(f"chunks: annotated {ch.get('annotated')} != prefix+hit+miss+ignored {n}")
    plan = report.get("plan")
    if plan:
        pt = plan.get("tokens") or {}
        ptot = pt.get("prefix_reused", 0) + pt.get("prefix_reused_approx", 0) + pt.get("chunk_reused", 0) + pt.get("prefilled", 0)
        if pt.get("prompt") != ptot:
            problems.append(f"plan.tokens partition broken ({pt})")
    return problems


def check_partition(cid, reports):
    probs = {i: partition_problems(r) for i, r in enumerate(reports)}
    bad = {i: p for i, p in probs.items() if p}
    return result(cid, not bad and len(reports) > 0, "partition holds on every report", {"reports": len(reports), "problems": bad})


def check_shadow_counts(cid, report, expect, per_chunk_stored=None):
    """expect: hit, miss, ignored, hit_tokens (sum of hit chunk tokens)."""
    obs = {}
    ok = True
    ch = report.get("chunks") or {}
    obs["chunks"] = ch
    for k in ("hit", "miss", "ignored"):
        if ch.get(k) != expect[k]:
            ok = False
    obs["policy_applied"] = report.get("policy_applied")
    if report.get("policy_applied") != "exact":
        ok = False
    plan = report.get("plan") or {}
    obs["plan_chunk_reused"] = (plan.get("tokens") or {}).get("chunk_reused")
    if obs["plan_chunk_reused"] != expect["hit_tokens"]:
        ok = False
    obs["predicted_ttft_ms"] = plan.get("predicted_ttft_ms")
    obs["full_prefill_estimate_ms"] = plan.get("full_prefill_estimate_ms")
    if not (isinstance(obs["predicted_ttft_ms"], (int, float)) and isinstance(obs["full_prefill_estimate_ms"], (int, float))
            and obs["predicted_ttft_ms"] < obs["full_prefill_estimate_ms"]):
        ok = False
    if per_chunk_stored is not None:
        per = {c["id"]: c["status"] for c in report.get("per_chunk", [])}
        want = {i: ("hit" if stored else "miss") for i, stored in per_chunk_stored.items()}
        obs["per_chunk_mismatch"] = {i: [per.get(i), w] for i, w in want.items() if per.get(i) != w}
        if obs["per_chunk_mismatch"]:
            ok = False
    return result(cid, ok, expect, obs)


def check_exact_neutrality(cid, records):
    """records (one transport): plain1, ann1, plain2, ann2, then optional warm-slot runs (all compared with plain1).

    Void (fails the run) when plain1 and plain2 differ: the baseline is non-deterministic, so no comparison is meaningful.
    """
    by = {r["label"]: r for r in records}
    p1, p2 = by["plain1"], by["plain2"]
    if token_signature(p1) != token_signature(p2):
        return result(cid, False, "plain1 == plain2 token ids", {"plain1": token_signature(p1), "plain2": token_signature(p2)},
                      void=True, note="plain baseline is non-deterministic; neutrality cannot be judged")
    ok = True
    diffs = {}
    base = token_signature(p1)
    for r in records:
        if r["label"].startswith("plain"):
            continue
        if token_signature(r) != base:
            ok = False
            diffs[r["label"]] = token_signature(r)
        rep = r.get("report")
        if rep is not None:
            if partition_problems(rep):
                ok = False
                diffs[r["label"] + ":partition"] = partition_problems(rep)
            if (rep.get("tokens") or {}).get("chunk_reused", 0) != 0 or rep.get("policy_applied") != "exact":
                ok = False
                diffs[r["label"] + ":applied"] = {"policy_applied": rep.get("policy_applied"),
                                                 "chunk_reused": (rep.get("tokens") or {}).get("chunk_reused")}
    cached_ok = by["ann2"]["cached_tokens"] == p2["cached_tokens"]
    if not cached_ok:
        ok = False
    obs = {"token_diffs": diffs, "cached_tokens": {r["label"]: r["cached_tokens"] for r in records},
           "cached_tokens_ann2_equals_plain2": cached_ok}
    return result(cid, ok, "all token ids == plain1; cached_tokens(ann2) == cached_tokens(plain2); chunk_reused 0", obs)


def parse_prometheus(text):
    """-> {(name, frozenset(label items)): float}"""
    out = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{([^}]*)\})?\s+([^\s]+)', line)
        if not m:
            continue
        labels = frozenset(re.findall(r'(\w+)="([^"]*)"', m.group(3) or ""))
        try:
            out[(m.group(1), labels)] = float(m.group(4))
        except ValueError:
            pass
    return out


def metric(parsed, name, **labels):
    return parsed.get((name, frozenset(labels.items())), 0.0)


def check_metrics_delta(cid, before_text, after_text, reported):
    """reported: {"hit": n, "miss": n, "prefix": n, "ignored": n, "tokens": {kind: n}} summed over annotated requests."""
    b, a = parse_prometheus(before_text), parse_prometheus(after_text)
    obs = {}
    ok = True
    for st in ("hit", "miss", "prefix", "ignored"):
        d = metric(a, "dotllm_chunk_cache_chunks_total", status=st) - metric(b, "dotllm_chunk_cache_chunks_total", status=st)
        obs[f"delta_{st}"] = d
        if d != reported.get(st, 0):
            ok = False
    for kind, n in (reported.get("tokens") or {}).items():
        d = metric(a, "dotllm_chunk_cache_tokens_total", kind=kind) - metric(b, "dotllm_chunk_cache_tokens_total", kind=kind)
        present = ("dotllm_chunk_cache_tokens_total", frozenset({("kind", kind)})) in a
        obs[f"tokens_{kind}"] = {"delta": d, "present": present}
        if not present or d != n:
            ok = False
    leaked = [n for (n, labels) in a if n.startswith("dotllm_chunk_") and any(k == "namespace" for k, _ in labels)]
    obs["namespace_labels"] = leaked
    if leaked:
        ok = False
    return result(cid, ok, reported, obs)


def check_namespace_isolation(cid, reports, expect):
    """reports: {caller: chunk_cache report}; expect: {caller: expected hit count}. A cross-namespace hit fails."""
    obs = {c: (reports[c].get("chunks") or {}).get("hit") for c in expect}
    ok = all(obs[c] == expect[c] for c in expect)
    return result(cid, ok, expect, obs)


def namespace_leaks(bodies_and_logs, namespaces):
    """Names of namespace strings that occur in any of the given texts."""
    return sorted({ns for ns in namespaces for t in bodies_and_logs if ns in t})


def derived_namespace(api_key):
    return "k-" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------------------------------------------------

class Http:
    def __init__(self, base_url, api_key=None, timeout=600):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.log = []  # every response body text (for the namespace-leak scan)

    def _req(self, method, path, body=None, headers=None, key="self", raw_body=None):
        h = {"Content-Type": "application/json"}
        k = self.api_key if key == "self" else key
        if k:
            h["X-API-Key"] = k
        if headers:
            h.update(headers)
        data = raw_body if raw_body is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            return resp
        except urllib.error.HTTPError as e:
            return e

    def json(self, method, path, body=None, key="self"):
        resp = self._req(method, path, body, key=key)
        raw = resp.read()
        text = raw.decode("utf-8", "replace")
        self.log.append(text)
        try:
            parsed = json.loads(text) if text.strip() else None
        except ValueError:
            parsed = None
        return resp.status if hasattr(resp, "status") else resp.code, parsed, text

    def text(self, path):
        resp = self._req("GET", path, key=None)
        return resp.read().decode("utf-8", "replace")

    def chat(self, body, key="self"):
        """Blocking or streaming /v1/chat/completions -> run record."""
        t0 = time.time()
        if body.get("stream"):
            resp = self._req("POST", "/v1/chat/completions", body, key=key)
            status = resp.status if hasattr(resp, "status") else resp.code
            if status != 200:
                text = resp.read().decode("utf-8", "replace")
                self.log.append(text)
                return {"status": status, "error_text": text, "json": _try_json(text)}
            return parse_openai_sse(resp, self.log, t0)
        status, parsed, text = self.json("POST", "/v1/chat/completions", body, key=key)
        if status != 200:
            return {"status": status, "error_text": text, "json": parsed}
        return record_from_openai(parsed, time.time() - t0)

    def messages_stream(self, body, key="self"):
        t0 = time.time()
        resp = self._req("POST", "/v1/messages", body, headers={"anthropic-version": "2023-06-01"}, key=key)
        status = resp.status if hasattr(resp, "status") else resp.code
        if status != 200:
            text = resp.read().decode("utf-8", "replace")
            self.log.append(text)
            return {"status": status, "error_text": text}
        events = []
        ev = None
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            self.log.append(line)
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                d = line[5:].strip()
                try:
                    events.append((ev, json.loads(d)))
                except ValueError:
                    pass
        report = None
        for e, d in events:
            if d.get("type") == "message_delta" and "chunk_cache" in d:
                report = d["chunk_cache"]
        return {"status": 200, "events": [e for e, _ in events], "report": report, "wall_s": time.time() - t0}


def _try_json(t):
    try:
        return json.loads(t)
    except ValueError:
        return None


def record_from_openai(j, wall_s):
    ch = (j.get("choices") or [{}])[0]
    lp = (ch.get("logprobs") or {}).get("content")
    tokens = [x.get("token") for x in lp] if lp else [(ch.get("message") or {}).get("content") or ""]
    usage = j.get("usage") or {}
    timings = j.get("timings") or {}
    return {"status": 200, "text": (ch.get("message") or {}).get("content"), "tokens": tokens,
            "token_source": "logprobs" if lp else "text",
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", timings.get("cache_n", 0)) or 0,
            "prompt_tokens": usage.get("prompt_tokens"), "prompt_ms": timings.get("prompt_ms"), "timings": timings,
            "report": j.get("chunk_cache"), "wall_s": wall_s, "finish_reason": ch.get("finish_reason")}


def parse_openai_sse(resp, log, t0):
    tokens, pieces, report, timings, usage = [], [], None, {}, {}
    have_lp = False
    first = None
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        log.append(line)
        if not line.startswith("data:"):
            continue
        d = line[5:].strip()
        if d == "[DONE]":
            break
        try:
            j = json.loads(d)
        except ValueError:
            continue
        if first is None:
            first = time.time() - t0
        for ch in j.get("choices") or []:
            lp = (ch.get("logprobs") or {}).get("content")
            if lp:
                have_lp = True
                tokens.extend(x.get("token") for x in lp)
            c = (ch.get("delta") or {}).get("content")
            if c:
                pieces.append(c)
        if j.get("chunk_cache") is not None:
            report = j["chunk_cache"]
        if j.get("timings"):
            timings = j["timings"]
        if j.get("usage"):
            usage = j["usage"]
    return {"status": 200, "text": "".join(pieces), "tokens": tokens if have_lp else pieces,
            "token_source": "logprobs" if have_lp else "text",
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", timings.get("cache_n", 0)) or 0,
            "prompt_tokens": usage.get("prompt_tokens"), "prompt_ms": timings.get("prompt_ms"), "timings": timings,
            "report": report, "wall_s": time.time() - t0, "ttft_s": first}


# ----------------------------------------------------------------------------------------------------------------------
# Fixtures (chunkcache select) and the check runner
# ----------------------------------------------------------------------------------------------------------------------

def run_cc(args, model, threads=8, extra_env=None):
    t0 = time.time()
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env={**os.environ, **(extra_env or {})})
    return p.returncode, p.stdout, p.stderr, time.time() - t0


def select_file(cc, model, repo, store, name):
    cmd = [cc, "select", "--model", model, "--directory", repo, "--chunker", "symbol", "--path", name,
           "--budget", "1000000", "--include-text", "--json"]
    if store and Path(store).exists():
        cmd += ["--store", store]
    code, out, err, _ = run_cc(cmd, model)
    if code != 0:
        raise SystemExit(f"select {name} failed ({code}): {err[-500:]}")
    j = json.loads(out)
    chunks = [{"id": c["id"], "path": c["path"], "start_line": c["start_line"], "end_line": c["end_line"], "tokens": c["tokens"],
               "hash": c["hash"], "key": c.get("key"), "text": c["text"], "stored": c.get("stored")}
              for c in j["chunks"]]
    if not chunks:
        raise SystemExit(f"select {name}: no chunks")
    # chunk texts must tile the file: the glue-free concatenation is what the prompt carries
    return {"role": None, "name": name, "path": chunks[0]["path"], "chunks": chunks}


def cmd_prep(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fx = {}
    for role, name in FILES.items():
        fs = select_file(a.cc_exe, a.model, a.repo, None, name)
        fs["role"] = role
        fx[role] = fs
    (out / "fixtures.json").write_text(json.dumps(fx, indent=1), encoding="utf-8")
    for role, fs in fx.items():
        print(role, fs["path"], len(fs["chunks"]), "chunks", sum(c["tokens"] for c in fs["chunks"]), "tokens",
              len(annotated_chunks(fs)), "annotated")


class Ctx:
    def __init__(self, a):
        self.a = a
        self.out = Path(a.out)
        (self.out / "checks").mkdir(parents=True, exist_ok=True)
        (self.out / "evidence").mkdir(parents=True, exist_ok=True)
        self.fx = json.loads((self.out / "fixtures.json").read_text(encoding="utf-8"))
        self.http = Http(a.base_url, a.api_key) if a.base_url else None
        self.model_name = a.model_name
        ledger = self.out / f"ledger-{a.phase}.json"
        self.ledger_path = ledger
        self.ledger = json.loads(ledger.read_text()) if ledger.exists() else {"hit": 0, "miss": 0, "prefix": 0, "ignored": 0, "tokens": {}}
        self.metrics_before = None

    def sel(self, *roles):
        return [self.fx[r] for r in roles]

    def evidence(self, name, obj):
        p = self.out / "evidence" / name
        p.write_text(json.dumps(obj, indent=1) if not isinstance(obj, str) else obj, encoding="utf-8")
        return f"evidence/{name}"

    def count(self, rep):
        if not rep:
            return
        for st in ("hit", "miss", "prefix", "ignored"):
            self.ledger[st] += (rep.get("chunks") or {}).get(st, 0)
        for k, v in (rep.get("tokens") or {}).items():
            self.ledger["tokens"][k] = self.ledger["tokens"].get(k, 0) + v
        self.ledger_path.write_text(json.dumps(self.ledger))

    def chat(self, body, key="self"):
        r = self.http.chat(body, key=key)
        if r.get("status") == 200:
            self.count(r.get("report"))
        return r

    def store_files(self):
        return sorted(str(p.relative_to(self.a.store)).replace("\\", "/") for p in Path(self.a.store).rglob("*.ckv")) \
            if self.a.store and Path(self.a.store).exists() else []

    def caps(self, key="self"):
        s, j, t = self.http.json("GET", "/v1/chunk-cache", key=key)
        return s, j

    def poll_entries(self, target, timeout=120, key="self"):
        t0 = time.time()
        last = None
        while time.time() - t0 < timeout:
            s, j = self.caps(key)
            last = (j or {}).get("store", {}).get("entries")
            if last is not None and last >= target:
                return last, time.time() - t0
            time.sleep(3)
        return last, time.time() - t0

    def expect_for(self, roles):
        placed_hit, placed_miss = [], []
        for r in roles:
            for c in annotated_chunks(self.fx[r]):
                (placed_hit if r in ("F1", "F2") else placed_miss).append(c)
        return placed_hit, placed_miss


def split_roles(ctx, hit_roles, miss_roles):
    hit = [c for r in hit_roles for c in annotated_chunks(ctx.fx[r])]
    miss = [c for r in miss_roles for c in annotated_chunks(ctx.fx[r])]
    return hit, miss


# ---- individual checks ------------------------------------------------------------------------------------------------

def chk_A0(ctx):
    a = ctx.a
    cmd = [a.cc_exe, "build", "--model", a.model, "--store", a.store, "--directory", a.repo, "--chunker", "symbol",
           "--path", FILES["F1"], "--path", FILES["F2"], "--threads", str(a.threads), "--json"]
    code, out, err, wall = run_cc(cmd, a.model)
    ctx.evidence("A0-build.stderr.txt", err[-4000:])
    j = None
    try:
        j = json.loads(out)
    except ValueError:
        pass
    expected_h = len(ctx.fx["F1"]["chunks"]) + len(ctx.fx["F2"]["chunks"])
    files = ctx.store_files()
    obs = {"exit": code, "encoded": (j or {}).get("encoded_chunks"), "store_ckv_files": len(files), "wall_s": round(wall, 1),
           "tokens_per_second": (j or {}).get("tokens_per_second"), "encoded_tokens": (j or {}).get("encoded_tokens")}
    ev = [ctx.evidence("A0-build.json", j or out[-2000:])]
    ok = code == 0 and obs["encoded"] == expected_h and len(files) == expected_h and wall <= 180
    return result("A0", ok, {"exit": 0, "encoded": expected_h, "store_ckv_files": expected_h, "wall_s": "<= 180"}, obs, ev)


def chk_A1(ctx):
    h = ctx.http
    s404, _, _ = h.json("GET", "/v1/chunk-cache")
    body_a, _ = build_openai(ctx.model_name, ctx.sel("F1", "F2", "F3"), policy="shadow")
    body_p, _ = build_openai(ctx.model_name, ctx.sel("F1", "F2", "F3"), annotate=False)
    ra, rp = h.chat(body_a), h.chat(body_p)
    obs = {"capabilities_status": s404, "annotated_has_chunk_cache": ra.get("report") is not None,
           "tokens_equal": ra.get("tokens") == rp.get("tokens"), "token_source": rp.get("token_source")}
    ok = s404 == 404 and not obs["annotated_has_chunk_cache"] and obs["tokens_equal"] and ra.get("status") == 200
    return result("A1", ok, {"capabilities_status": 404, "annotated_has_chunk_cache": False, "tokens_equal": True}, obs)


def chk_A2(ctx):
    s, j = ctx.caps()
    n_enc = len(ctx.fx["F1"]["chunks"]) + len(ctx.fx["F2"]["chunks"])
    j = j or {}
    m, st = j.get("model") or {}, j.get("store") or {}
    obs = {"status": s, "versions": j.get("versions"), "policies": j.get("policies"), "selectors": j.get("selectors"),
           "wire_chunkers": j.get("wire_chunkers"), "auto_validated": j.get("auto_validated"), "model_supported": m.get("supported"),
           "model_backend": m.get("backend"), "kv_dtype": m.get("kv_dtype"), "store_entries": st.get("entries"),
           "store_dtype": st.get("dtype")}
    ok = (s == 200 and j.get("versions") == [1]
          and set(["exact", "shadow", "balanced", "fast", "auto"]) <= set(j.get("policies") or [])
          and j.get("selectors") == ["chunk_starts"] and j.get("wire_chunkers") == [CHUNKER]
          and j.get("auto_validated") == [] and m.get("supported") is True and st.get("entries") == n_enc
          and st.get("dtype") == "f32")
    return result("A2", ok, {"versions": [1], "selectors": ["chunk_starts"], "wire_chunkers": [CHUNKER], "auto_validated": [],
                             "model.supported": True, "store.entries": n_enc, "store.dtype": "f32"}, obs,
                  [ctx.evidence("A2-capabilities.json", j)])


def shadow_request(ctx, roles=("F1", "F2", "F3"), key="self", **kw):
    body, placed = build_openai(ctx.model_name, ctx.sel(*roles), policy="shadow", report="per_chunk", **kw)
    return ctx.chat(body, key=key), placed


def chk_A3(ctx):
    r, placed = shadow_request(ctx)
    if r.get("status") != 200:
        return result("A3", False, "200", {"status": r.get("status"), "body": r.get("error_text", "")[:500]})
    hit, miss = split_roles(ctx, ("F1", "F2"), ("F3",))
    expect = {"hit": len(hit), "miss": len(miss), "ignored": 0, "hit_tokens": sum(c["tokens"] for c in hit)}
    stored = {c["id"]: bool(c.get("stored")) for r_ in ("F1", "F2", "F3") for c in annotated_chunks(ctx.fx[r_])}
    # `stored` per chunk from a fresh select against the store (the CLI's own view)
    fresh = {}
    for role in ("F1", "F2", "F3"):
        fs = select_file(ctx.a.cc_exe, ctx.a.model, ctx.a.repo, ctx.a.store, FILES[role])
        for c in fs["chunks"]:
            fresh[c["id"]] = bool(c.get("stored"))
    stored = {c["id"]: fresh.get(c["id"], False) for r_ in ("F1", "F2", "F3") for c in annotated_chunks(ctx.fx[r_])}
    res = check_shadow_counts("A3", r["report"], expect, per_chunk_stored=stored)
    res["evidence_files"] = [ctx.evidence("A3-response-report.json", r["report"])]
    res["observed"]["prompt_tokens"] = r.get("prompt_tokens")
    res["observed"]["prompt_ms"] = r.get("prompt_ms")
    return res


def neutrality_sequence(ctx, stream, cid, roles=("F1", "F2", "F3")):
    kw = {"stream": stream}
    plain, _ = build_openai(ctx.model_name, ctx.sel(*roles), annotate=False, **kw)
    ann, _ = build_openai(ctx.model_name, ctx.sel(*roles), policy="exact", report="summary", **kw)
    shadow, _ = build_openai(ctx.model_name, ctx.sel(*roles), policy="shadow", report="summary", **kw)
    recs = []
    for label, body in (("plain1", plain), ("ann1", ann), ("plain2", plain), ("ann2", ann), ("shadow_warm", shadow), ("exact_warm", ann)):
        r = ctx.chat(body)
        if r.get("status") != 200:
            return None, {"label": label, "status": r.get("status"), "body": r.get("error_text", "")[:400]}
        r["label"] = label
        recs.append(r)
    return recs, None


def chk_A4(ctx, cid="A4"):
    obs, evid, ok, void = {}, [], True, False
    notes = []
    for stream in (False, True):
        name = "streaming" if stream else "blocking"
        recs, err = neutrality_sequence(ctx, stream, cid)
        if err:
            return result(cid, False, "200 on every request", {name: err})
        res = check_exact_neutrality(cid, recs)
        obs[name] = res["observed"]
        obs[name]["token_source"] = recs[0]["token_source"]
        obs[name]["prompt_ms"] = {r["label"]: r.get("prompt_ms") for r in recs}
        ok = ok and res["passed"]
        void = void or res["void"]
        if res.get("note"):
            notes.append(f"{name}: {res['note']}")
        evid.append(ctx.evidence(f"{cid}-{name}.json", [{k: v for k, v in r.items() if k != "timings"} for r in recs]))
    return result(cid, ok, "all token ids identical to plain1 (blocking and streaming)", obs, evid, void=void,
                  note="; ".join(notes) or None)


def chk_A4b(ctx):
    return chk_A4(ctx, "A4b")


def chk_A5(ctx):
    body, placed = build_openai(ctx.model_name, ctx.sel("F1", "F2"), policy="shadow", strict=True, wrong_hash_at=0, max_tokens=4)
    status, j, text = ctx.http.json("POST", "/v1/chat/completions", body)
    err = (j or {}).get("error") or {}
    nbody, _ = build_openai(ctx.model_name, ctx.sel("F1", "F2"), policy="shadow", strict=False, wrong_hash_at=0, max_tokens=4)
    r = ctx.chat(nbody)
    warns = [w.get("code") if isinstance(w, dict) else w for w in ((r.get("report") or {}).get("warnings") or [])]
    obs = {"strict_status": status, "strict_type": err.get("type"), "strict_code": err.get("code"),
           "nonstrict_status": r.get("status"), "nonstrict_warnings": warns}
    ok = (status == 400 and err.get("type") == "invalid_request_error" and err.get("code") == "chunk_hash_mismatch"
          and r.get("status") == 200 and "chunk_hash_mismatch" in warns)
    return result("A5", ok, {"strict": "400 invalid_request_error chunk_hash_mismatch", "non_strict": "200 + warning chunk_hash_mismatch"}, obs)


def chk_A6(ctx):
    body, placed = build_anthropic(ctx.model_name, ctx.sel("F1", "F2", "F3"))
    r = ctx.http.messages_stream(body)
    if r.get("status") != 200:
        return result("A6", False, "200", {"status": r.get("status"), "body": r.get("error_text", "")[:500]})
    rep = r["report"]
    hit, miss = split_roles(ctx, ("F1", "F2"), ("F3",))
    obs = {"events": sorted(set(r["events"])), "report_present": rep is not None}
    if rep:
        ctx.count(rep)
        obs["chunks"] = rep.get("chunks")
    want = {"hit": len(hit), "miss": len(miss), "ignored": 0}
    ok = rep is not None and all((rep.get("chunks") or {}).get(k) == v for k, v in want.items())
    return result("A6", ok, {"message_delta.chunk_cache.chunks": want}, obs, [ctx.evidence("A6-report.json", rep or {})])


def chk_A7(ctx):
    a = ctx.a
    prompt, placed = build_prompt(ctx.sel("F1", "F2", "F3"))
    req = {"model": ctx.model_name, "system": SYSTEM, "prompt": prompt, "query": QUERY, "max_tokens": 16,
           "chunks": [{"id": p["id"], "text": p["text"]} for p in placed]}
    rp = ctx.out / "evidence" / "A7-smoke-request.json"
    rp.write_text(json.dumps(req), encoding="utf-8")
    cmd = ["dotnet", a.smoke_dll, a.base_url, str(rp)] + ([a.api_key] if a.api_key else [])
    code, out, err, wall = run_cc(cmd, a.model)
    j = None
    try:
        j = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        pass
    rep = (j or {}).get("report")
    if rep:
        ctx.count(rep)
    hit, miss = split_roles(ctx, ("F1", "F2"), ("F3",))
    want = {"hit": len(hit), "miss": len(miss), "ignored": 0}
    obs = {"exit": code, "chunks": (rep or {}).get("chunks"), "outcome": (j or {}).get("outcome"), "stderr": err[-300:]}
    ok = code == 0 and rep is not None and all((rep.get("chunks") or {}).get(k) == v for k, v in want.items())
    return result("A7", ok, {"exit": 0, "chunks": want}, obs, [ctx.evidence("A7-smoke-output.json", j or out[-2000:])])


def f3_request(ctx, key="self", **kw):
    body, placed = build_openai(ctx.model_name, ctx.sel("F1", "F2", "F3"), policy="shadow", report="per_chunk", **kw)
    return ctx.chat(body, key=key)


def chk_A8(ctx):
    n_enc = len(ctx.fx["F1"]["chunks"]) + len(ctx.fx["F2"]["chunks"])
    f3 = annotated_chunks(ctx.fx["F3"])
    f3_tokens = sum(c["tokens"] for c in f3)
    obs = {"f3_annotated_chunks": len(f3), "f3_tokens": f3_tokens, "max_f3_chunk_tokens": max(c["tokens"] for c in f3)}
    r1 = f3_request(ctx)
    q1 = (r1.get("report") or {}).get("tokens", {}).get("encode_queued")
    r2 = f3_request(ctx)
    q2 = (r2.get("report") or {}).get("tokens", {}).get("encode_queued")
    obs.update({"encode_queued_1st": q1, "encode_queued_2nd": q2,
                "warnings_2nd": (r2.get("report") or {}).get("warnings")})
    entries, waited = ctx.poll_entries(n_enc + len(f3), 120)
    obs.update({"entries_after": entries, "entries_expected": n_enc + len(f3), "poll_s": round(waited, 1)})
    r3 = f3_request(ctx)
    ch3 = (r3.get("report") or {}).get("chunks") or {}
    per3 = {c["id"]: c["status"] for c in (r3.get("report") or {}).get("per_chunk", [])}
    f3_status = {c["id"]: per3.get(c["id"]) for c in f3}
    obs["third_chunks"] = ch3
    obs["f3_third_status"] = f3_status
    ok = (q1 == 0 and q2 == f3_tokens and entries == n_enc + len(f3) and all(s == "hit" for s in f3_status.values())
          and obs["max_f3_chunk_tokens"] <= 512)
    return result("A8", ok, {"encode_queued_1st": 0, "encode_queued_2nd": f3_tokens, "store.entries": n_enc + len(f3),
                             "third_request_F3_status": "hit"}, obs, [ctx.evidence("A8-requests.json",
                             {"r1": r1.get("report"), "r2": r2.get("report"), "r3": r3.get("report")})])


def chk_A9(ctx):
    a = ctx.a
    s2 = a.store2
    if Path(s2).exists():
        import shutil
        shutil.rmtree(s2)
    cmd = [a.cc_exe, "build", "--model", a.model, "--store", s2, "--directory", a.repo, "--chunker", "symbol",
           "--path", FILES["F3"], "--threads", str(a.threads), "--json"]
    code, out, err, wall = run_cc(cmd, a.model)
    srv = {p: Path(a.store) / p for p in ctx.store_files()}
    cli = {str(p.relative_to(s2)).replace("\\", "/"): p for p in Path(s2).rglob("*.ckv")}
    f3_keys = {c["key"] for c in ctx.fx["F3"]["chunks"] if c["key"]}
    # server-written F3 entries: files whose name carries an F3 chunk key
    def keyof(rel):
        return Path(rel).stem
    srv_f3 = {rel: p for rel, p in srv.items() if keyof(rel) in f3_keys}
    obs = {"cli_exit": code, "cli_files": len(cli), "server_f3_files": len(srv_f3), "f3_keys": len(f3_keys),
           "names_equal_for_server_written": sorted(map(keyof, srv_f3)) == sorted(keyof(r) for r in cli if keyof(r) in {keyof(x) for x in srv_f3})}
    diffs = {}
    for rel, p in srv_f3.items():
        match = [q for r, q in cli.items() if keyof(r) == keyof(rel)]
        if not match:
            diffs[keyof(rel)] = "missing in CLI store"
            continue
        b1, b2 = p.read_bytes(), match[0].read_bytes()
        if b1 != b2:
            diffs[keyof(rel)] = {"len": [len(b1), len(b2)], "first_diff": next((i for i, (x, y) in enumerate(zip(b1, b2)) if x != y), None)}
    obs["payload_differences"] = diffs
    # status lists F3 as stored: select against the store now
    sel = select_file(a.cc_exe, a.model, a.repo, a.store, FILES["F3"])
    stored = {c["id"]: bool(c.get("stored")) for c in sel["chunks"] if c["tokens"] >= MIN_CHUNK_TOKENS}
    obs["select_stored_annotated_f3"] = stored
    ok = (code == 0 and len(srv_f3) == len(annotated_chunks(ctx.fx["F3"])) and obs["names_equal_for_server_written"]
          and not diffs and all(stored.values()))
    return result("A9", ok, {"same key file names": True, "payload bytes equal": True, "status lists F3 stored": True}, obs)


def chk_A10(ctx):
    h = ctx.http
    n_enc = len(ctx.fx["F1"]["chunks"]) + len(ctx.fx["F2"]["chunks"])
    f3 = annotated_chunks(ctx.fx["F3"])
    f4 = annotated_chunks(ctx.fx["F4"])
    obs = {}
    before_entries = ctx.caps()[1]["store"]["entries"]
    texts = [{"id": c["id"], "text": c["text"], "source": {"path": ctx.fx["F4"]["path"]}} for c in f4]
    s, pw, _ = h.json("POST", "/v1/chunk-cache/prewarm", {"texts": texts})
    obs["prewarm"] = {"status": s, "body": pw}
    entries, waited = ctx.poll_entries(before_entries + len(f4), 120)
    obs["entries_after_prewarm"] = [before_entries, entries]
    files_before = ctx.store_files()
    s, ev, _ = h.json("POST", "/v1/chunk-cache/evict", {})
    obs["default_evict"] = {"status": s, "body": ev}
    files_after_default = ctx.store_files()
    f3_files = [f for f in ctx.store_files() if Path(f).stem in {c["key"] for c in ctx.fx["F3"]["chunks"]}]
    s, ev, _ = h.json("POST", "/v1/chunk-cache/evict", {"mode": "path", "path": ctx.fx["F3"]["path"], "dry_run": False})
    obs["path_evict"] = {"status": s, "body": ev}
    files_final = ctx.store_files()
    cli_keys = {c["key"] for r_ in ("F1", "F2") for c in ctx.fx[r_]["chunks"]}
    f3_keys = {c["key"] for c in ctx.fx["F3"]["chunks"]}
    remaining_cli = [f for f in files_final if Path(f).stem in cli_keys]
    remaining_f3 = [f for f in files_final if Path(f).stem in f3_keys]
    obs.update({"f3_files_before_evict": len(f3_files), "f3_files_after": len(remaining_f3), "cli_files_after": len(remaining_cli),
                "default_evict_deleted_nothing": files_before == files_after_default})
    r = f3_request(ctx)
    rep = r.get("report") or {}
    obs["post_forget_encode_queued"] = (rep.get("tokens") or {}).get("encode_queued")
    obs["post_forget_warnings"] = rep.get("warnings")
    ok = (s == 200 and pw and pw.get("queued") == len(f4) and entries == before_entries + len(f4)
          and obs["default_evict"]["status"] in (200, 403) and obs["default_evict_deleted_nothing"]
          and not remaining_f3 and len(remaining_cli) == n_enc and obs["post_forget_encode_queued"] == 0)
    return result("A10", ok, {"prewarm.queued": len(f4), "default evict deletes nothing": True, "path evict removes F3 files": True,
                              "CLI F1/F2 files kept": n_enc, "post-forget F3 request queues": 0}, obs,
                  [ctx.evidence("A10.json", obs)])


def write_keys(path, ka, kb):
    Path(path).write_text(f"{ka} admin\n{kb}\n", encoding="utf-8")


def chk_A11(ctx):
    a = ctx.a
    ka, kb = a.key_a, a.key_b
    h = ctx.http
    obs = {}
    s_nokey, _, _ = h.json("GET", "/v1/chunk-cache", key=None)
    obs["no_key_status"] = s_nokey
    ra, _ = shadow_request(ctx, ("F1",), key=ka)
    obs["K_A_shadow_F1_hit"] = (ra.get("report") or {}).get("chunks")
    f4 = annotated_chunks(ctx.fx["F4"])
    texts = [{"id": c["id"], "text": c["text"], "source": {"path": ctx.fx["F4"]["path"]}} for c in f4]
    s, pw, _ = h.json("POST", "/v1/chunk-cache/prewarm", {"texts": texts}, key=ka)
    obs["prewarm_K_A"] = {"status": s, "queued": (pw or {}).get("queued")}
    # wait (<= 120 s) until K_A's own request sees the prewarmed F4 chunk (encodes run after 2 s of quiet)
    t0 = time.time()
    rka = None
    while time.time() - t0 < 120:
        rka, _ = shadow_request(ctx, ("F4",), key=ka)
        if ((rka.get("report") or {}).get("chunks") or {}).get("hit") == len(f4):
            break
        time.sleep(4)
    obs["K_A_F4"] = (rka.get("report") or {}).get("chunks")
    rkb, _ = shadow_request(ctx, ("F4",), key=kb)
    obs["K_B_F4"] = (rkb.get("report") or {}).get("chunks")
    files_before = ctx.store_files()
    s_ev, ev, _ = h.json("POST", "/v1/chunk-cache/evict", {"mode": "namespace", "dry_run": False}, key=kb)
    obs["K_B_evict_namespace"] = {"status": s_ev, "body": ev}
    files_after = ctx.store_files()
    obs["files_unchanged_by_K_B_evict"] = files_before == files_after
    rka2, _ = shadow_request(ctx, ("F4",), key=ka)
    obs["K_A_F4_after_K_B_evict"] = (rka2.get("report") or {}).get("chunks")
    sb, jb = ctx.caps(kb)
    sa, ja = ctx.caps(ka)
    obs["caps_K_B_entries"] = (jb or {}).get("store", {}).get("entries")
    obs["caps_K_A_entries"] = (ja or {}).get("store", {}).get("entries")
    leaks = namespace_leaks(h.log + [Path(a.server_log).read_text(errors="replace") if a.server_log and Path(a.server_log).exists() else ""],
                            [derived_namespace(ka), derived_namespace(kb)])
    obs["namespace_strings_found"] = leaks
    iso = check_namespace_isolation("A11", {"A": rka["report"], "B": rkb["report"]},
                                    {"A": len(f4), "B": 0})
    ok = (s_nokey == 401 and (obs["K_A_shadow_F1_hit"] or {}).get("hit") == 0 and obs["prewarm_K_A"]["queued"] == len(f4)
          and iso["passed"] and obs["files_unchanged_by_K_B_evict"]
          and (obs["K_A_F4_after_K_B_evict"] or {}).get("hit") == len(f4)
          and obs["caps_K_B_entries"] == 0 and (obs["caps_K_A_entries"] or 0) >= len(f4) and not leaks)
    return result("A11", ok, {"no key": 401, "K_A F1 hit": 0, "K_A F4 hit": len(f4), "K_B F4 hit": 0,
                              "K_B namespace evict leaves K_A": True, "K_B capabilities entries": 0, "namespace strings leaked": []}, obs,
                  [ctx.evidence("A11.json", obs)])


def chk_A12(ctx):
    after = ctx.http.text("/metrics")
    ctx.evidence(f"A12-metrics-{ctx.a.phase}.txt", after)
    return check_metrics_delta("A12", "", after, ctx.ledger)


def chk_V1(ctx):
    s, j = ctx.caps()
    m = (j or {}).get("model") or {}
    res = chk_A4(ctx, "V1")
    res["observed"]["capabilities"] = {"status": s, "backend": m.get("backend"), "supported": m.get("supported"),
                                       "kv_dtype": m.get("kv_dtype"), "store_entries": (j or {}).get("store", {}).get("entries")}
    res["passed"] = res["passed"] and m.get("backend") == "vulkan" and m.get("supported") is True
    res["expected"] = {"model.backend": "vulkan", "A4 passes": True}
    return res


def chk_V2(ctx):
    r, placed = shadow_request(ctx)
    if r.get("status") != 200:
        return result("V2", False, "200", {"status": r.get("status"), "body": r.get("error_text", "")[:500]})
    rep = r["report"]
    verified = len(annotated_chunks(ctx.fx["F1"])) + len(annotated_chunks(ctx.fx["F2"])) + len(annotated_chunks(ctx.fx["F3"]))
    ch = rep.get("chunks") or {}
    obs = {"chunks": ch, "policy_applied": rep.get("policy_applied"), "warnings": rep.get("warnings")}
    ok = ch.get("hit") == 0 and ch.get("miss") == verified and rep.get("policy_applied") == "exact"
    return result("V2", ok, {"hit": 0, "miss": verified}, obs, [ctx.evidence("V2-report.json", rep)])


def store_snapshot(store):
    snap = {}
    for p in sorted(Path(store).rglob("*")):
        if p.is_file():
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for blk in iter(lambda: f.read(1 << 20), b""):
                    h.update(blk)
            snap[str(p.relative_to(store)).replace("\\", "/")] = [p.stat().st_size, h.hexdigest()]
    return snap


def chk_V3(ctx):
    before = store_snapshot(ctx.a.store)
    r1 = f3_request(ctx)
    r2 = f3_request(ctx)
    time.sleep(8)  # the idle rule is 2 s; a Vulkan server must never encode
    after = store_snapshot(ctx.a.store)
    codes = []
    for r in (r1, r2):
        for w in ((r.get("report") or {}).get("warnings") or []):
            codes.append(w.get("code") if isinstance(w, dict) else w)
    obs = {"warning_codes": sorted(set(codes)), "listing_identical": before == after, "files": len(after),
           "encode_queued": [(r.get("report") or {}).get("tokens", {}).get("encode_queued") for r in (r1, r2)]}
    if before != after:
        obs["changed"] = sorted(set(before) ^ set(after)) + [k for k in before if k in after and before[k] != after[k]]
    ok = "chunk_encode_skipped" in codes and before == after
    return result("V3", ok, {"warning": "chunk_encode_skipped", "store listing byte-identical": True}, obs)


def chk_VOH(ctx):
    """Vulkan exact overhead: server prompt_ms of annotated(exact) minus plain, alternating, medians (spec 12.5, target < 5 ms)."""
    n = ctx.a.repeats
    plain, _ = build_openai(ctx.model_name, ctx.sel("F1", "F2", "F3"), annotate=False, max_tokens=1)
    ann, _ = build_openai(ctx.model_name, ctx.sel("F1", "F2", "F3"), policy="exact", report="summary", max_tokens=1)
    ctx.chat(plain)  # warm
    pm, am = [], []
    for _ in range(n):
        pm.append(ctx.chat(plain).get("prompt_ms"))
        am.append(ctx.chat(ann).get("prompt_ms"))
    import statistics as st
    pm_f = [x for x in pm if x is not None]
    am_f = [x for x in am if x is not None]
    med = (st.median(am_f) - st.median(pm_f)) if pm_f and am_f else None
    obs = {"plain_prompt_ms": pm, "annotated_prompt_ms": am, "median_overhead_ms": med,
           "median_plain_ms": st.median(pm_f) if pm_f else None, "median_annotated_ms": st.median(am_f) if am_f else None}
    return result("VOH", med is not None and med < 5, {"median(annotated) - median(plain) prompt_ms": "< 5"}, obs)


CHECKS = {"A0": chk_A0, "A1": chk_A1, "A2": chk_A2, "A3": chk_A3, "A4": chk_A4, "A4b": chk_A4b, "A5": chk_A5, "A6": chk_A6,
          "A7": chk_A7, "A8": chk_A8, "A9": chk_A9, "A10": chk_A10, "A11": chk_A11, "A12": chk_A12,
          "V1": chk_V1, "V2": chk_V2, "V3": chk_V3, "VOH": chk_VOH}


def cmd_check(a):
    ctx = Ctx(a)
    overall = 0
    for cid in a.ids:
        t0 = time.time()
        try:
            res = CHECKS[cid](ctx)
        except Exception as e:  # a check crashing is a failed check, with the cause recorded
            res = result(cid, False, "check runs", {"exception": f"{type(e).__name__}: {e}"})
        res["wall_s"] = round(time.time() - t0, 1)
        res["phase"] = a.phase
        (ctx.out / "checks" / f"{cid}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(f"{cid}: {'PASS' if res['passed'] else ('VOID' if res['void'] else 'FAIL')} ({res['wall_s']} s)")
        if not res["passed"]:
            overall = 1
            print("   observed:", json.dumps(res["observed"])[:600])
    return overall


def cmd_summarize(a):
    out = Path(a.out)
    checks = {}
    for p in sorted((out / "checks").glob("*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        checks[c["id"]] = c
    (out / "checks.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")
    meta = json.loads(Path(a.meta).read_text(encoding="utf-8")) if a.meta and Path(a.meta).exists() else {}
    lines = [f"# e2e-chunkcache run {out.name}", "", "## Provenance", ""]
    lines += [f"- {k}: {v}" for k, v in meta.items()]
    lines += ["", "## Checks", "", "| id | result | wall s | expected | observed (abridged) |", "|---|---|---|---|---|"]
    order = list(CHECKS)
    for cid in sorted(checks, key=lambda x: order.index(x) if x in order else 99):
        c = checks[cid]
        st = "PASS" if c["passed"] else ("VOID" if c["void"] else "FAIL")
        exp = json.dumps(c["expected"])[:110].replace("|", "/")
        obs = json.dumps(c["observed"])[:140].replace("|", "/")
        lines.append(f"| {cid} | {st} | {c.get('wall_s')} | {exp} | {obs} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    failed = [c for c in checks.values() if not c["passed"]]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prep")
    p.add_argument("--model", required=True)
    p.add_argument("--cc-exe", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("check")
    p.add_argument("ids", nargs="+")
    p.add_argument("--base-url")
    p.add_argument("--api-key")
    p.add_argument("--key-a")
    p.add_argument("--key-b")
    p.add_argument("--store")
    p.add_argument("--store2")
    p.add_argument("--out", required=True)
    p.add_argument("--model")
    p.add_argument("--model-name", default="qwen3-4b")
    p.add_argument("--cc-exe")
    p.add_argument("--repo")
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--smoke-dll")
    p.add_argument("--server-log")
    p.add_argument("--phase", default="phase")
    p.add_argument("--repeats", type=int, default=5)
    p = sub.add_parser("summarize")
    p.add_argument("--out", required=True)
    p.add_argument("--meta")
    a = ap.parse_args(argv)
    return {"prep": cmd_prep, "check": cmd_check, "summarize": cmd_summarize}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
