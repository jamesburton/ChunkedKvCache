"""Reproduction attempt of the one unexplained observation of the first A11 draft (run r2): a shadow request of key K_B hung for
36 minutes (req#18, server log "cancelled (client disconnected) after 36m45s") on an auth + sole-writer CPU server, after K_A's
prewarm of F4 and ~14 identical-prompt shadow probes by K_A (every probe reported `prefix`, so the hit status never came).

Starts its own server (CPU, auth, writer) on a COPY of the CPU store; every request has a 150 s client timeout.
Usage (hold ResourceLock cpu-bench):  python -I repro_a11_hang.py <run-dir with fixtures.json> <store-copy-src> <work-dir> <model> <dotllm.exe>
"""
import importlib.util
import json
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("e2e", HERE / "e2e.py")
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)

run_dir, store_src, work, model, exe = (Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5])
work.mkdir(parents=True, exist_ok=True)
store = work / "store"
if store.exists():
    shutil.rmtree(store)
shutil.copytree(store_src, store)
for lock in store.glob(".chunkstore*"):
    lock.unlink()
fx = json.loads((run_dir / "fixtures.json").read_text(encoding="utf-8"))
ka, kb = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
keys = work / "keys.txt"
keys.write_text(f"{ka} admin\n{kb}\n", encoding="ascii")
port = 18190
log = open(work / "server.log", "w")
srv = subprocess.Popen([str(exe), "serve", model, "--port", str(port), "--host", "127.0.0.1", "--no-warmup", "--no-browser", "--no-ui",
                        "--threads", "8", "--ctx-size", "8192", "--device", "cpu", "--chunk-cache", "--chunk-store", str(store),
                        "--chunk-store-write", "--chunk-store-budget", "4GB", "--chunk-cache-api-keys", str(keys)],
                       stdout=log, stderr=log)
out = {"events": []}


def note(msg):
    out["events"].append(f"{time.strftime('%H:%M:%S')} {msg}")
    print(out["events"][-1], flush=True)


try:
    h = e2e.Http(f"http://127.0.0.1:{port}", None, timeout=150)
    for _ in range(120):
        try:
            if h.text("/ready") is not None and "ready" in h.text("/ready"):
                break
        except Exception:
            time.sleep(1)
    model_name = json.loads(h.text("/v1/models"))["data"][0]["id"]
    f4 = e2e.annotated_chunks(fx["F4"])
    texts = [{"id": c["id"], "text": c["text"], "source": {"path": fx["F4"]["path"]}} for c in f4]
    s, pw, _ = h.json("POST", "/v1/chunk-cache/prewarm", {"texts": texts}, key=ka)
    note(f"prewarm K_A -> {s} {pw}")

    def probe(key, label):
        body, _ = e2e.build_openai(model_name, [fx["F4"]], policy="shadow", report="per_chunk")  # identical prompt every time
        t0 = time.time()
        try:
            r = h.chat(body, key=key)
            note(f"{label}: {r.get('status')} chunks={(r.get('report') or {}).get('chunks')} cached={r.get('cached_tokens')} in {time.time()-t0:.1f}s")
        except Exception as e:  # a timeout is the finding
            note(f"{label}: EXCEPTION {type(e).__name__} after {time.time()-t0:.1f}s")
            out["hang"] = True
            raise

    t0 = time.time()
    i = 0
    while time.time() - t0 < 120:
        i += 1
        probe(ka, f"K_A probe {i}")
        time.sleep(4)
    probe(kb, "K_B probe (identical prompt)")
    out["hang"] = out.get("hang", False)
except Exception as e:
    note(f"stopped: {type(e).__name__}: {e}")
finally:
    srv.kill()
    log.close()
    (work / "repro.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
