"""E8 transcript recorder: drive a local dotLLM server as a read-only code agent and record every turn.

Usage (server first: `dotllm serve <model.gguf> --port 8099 --threads 8 --device cpu --no-browser --no-warmup`):
    uv run record.py --base-url http://127.0.0.1:8099 --model-name qwen3-4b --repo C:\\Development\\CSharpDocAgentFrameworkMCP \\
        --tasks tasks-pilot.json --out transcripts/pilot-qwen3 --max-turns 6

One agent run of T assistant turns yields up to T-1 transcripts (one per turn that has history): messages = the chat so far,
next = the assistant reply that followed. Transcripts of one run share a `source` (cluster for the bootstrap).
Tools are read-only (read_file, grep, list_dir) and sandboxed to --repo. Everything read from the repo is untrusted TEXT: it is
passed to the model as tool output and written to JSON, never executed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

SYSTEM = (
    "You are a careful code-reading agent. Answer the user's question about the repository by calling the tools. "
    "Read files before you claim anything about them. Call one tool at a time. When you know the answer, reply in plain text "
    "without calling a tool."
)

TOOLS = [
    {"name": "read_file", "description": "Read a text file from the repository (first 6000 characters).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "path relative to the repo root"}}, "required": ["path"]}},
    {"name": "grep", "description": "Search the repository for a regular expression; returns up to 20 matching lines as path:line:text.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "list_dir", "description": "List a directory of the repository (names only).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "path relative to the repo root, '.' for the root"}}, "required": ["path"]}},
]

SKIP_DIRS = {".git", "bin", "obj", "node_modules", ".vs", "packages"}
MAX_OUT = 6000
MAX_FILE = 400_000


def safe(repo: Path, rel: str) -> Path:
    p = (repo / rel).resolve()
    if repo.resolve() not in (p, *p.parents):
        raise ValueError("path escapes the repository")
    return p


def run_tool(repo: Path, name: str, args: dict) -> str:
    try:
        if name == "read_file":
            p = safe(repo, str(args["path"]))
            if not p.is_file() or p.stat().st_size > MAX_FILE:
                return "error: not a readable file"
            return p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")[:MAX_OUT]
        if name == "list_dir":
            p = safe(repo, str(args.get("path", ".")))
            if not p.is_dir():
                return "error: not a directory"
            names = sorted(e.name + ("/" if e.is_dir() else "") for e in p.iterdir() if e.name not in SKIP_DIRS)
            return "\n".join(names)[:MAX_OUT]
        if name == "grep":
            rx = re.compile(str(args["pattern"]))
            hits: list[str] = []
            for root, dirs, files in os.walk(repo):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for f in sorted(files):
                    if not f.endswith((".cs", ".md", ".json", ".csproj", ".py", ".ts", ".txt")):
                        continue
                    fp = Path(root) / f
                    if fp.stat().st_size > MAX_FILE:
                        continue
                    for i, line in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if rx.search(line):
                            hits.append(f"{fp.relative_to(repo).as_posix()}:{i}:{line.strip()[:160]}")
                            if len(hits) >= 20:
                                return "\n".join(hits)[:MAX_OUT]
            return "\n".join(hits) or "no matches"
        return f"error: unknown tool {name}"
    except Exception as ex:  # tool errors are data for the model, not crashes
        return f"error: {type(ex).__name__}: {ex}"


def chat(base: str, model: str, messages: list[dict], max_tokens: int) -> dict:
    body = {
        "model": model, "temperature": 0, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": SYSTEM}] + [to_wire(m) for m in messages],
        "tools": [{"type": "function", "function": t} for t in TOOLS],
    }
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)["choices"][0]["message"]


def to_wire(m: dict) -> dict:
    out = {"role": m["role"], "content": m.get("content") or ""}
    if m.get("tool_calls"):
        out["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in m["tool_calls"]]
    if m.get("tool_call_id"):
        out["tool_call_id"] = m["tool_call_id"]
    return out


def from_wire(m: dict) -> dict:
    calls = [{"id": c.get("id") or f"call_{i}", "name": c["function"]["name"], "arguments": c["function"]["arguments"]
              if isinstance(c["function"]["arguments"], str) else json.dumps(c["function"]["arguments"])}
             for i, c in enumerate(m.get("tool_calls") or [])]
    out = {"role": "assistant", "content": m.get("content") or ""}
    if calls:
        out["tool_calls"] = calls
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model-name", required=True, help="label stored in the transcripts (and sent as `model`)")
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--tasks", required=True, type=Path, help="JSON list of {id, prompt}")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=400)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    tasks = json.loads(a.tasks.read_text(encoding="utf-8"))
    written = 0
    for task in tasks:
        messages = [{"role": "user", "content": task["prompt"]}]
        for turn in range(1, a.max_turns + 1):
            reply = from_wire(chat(a.base_url, a.model_name, messages, a.max_tokens))
            if turn >= 2:  # a transcript needs history before the answered message
                tr = {"id": f"{a.model_name}-{task['id']}-t{turn}", "model": a.model_name, "source": f"{a.model_name}/{task['id']}",
                      "system": SYSTEM, "tools": TOOLS, "messages": messages, "next": reply}
                (a.out / f"{tr['id']}.json").write_text(json.dumps(tr, indent=1), encoding="utf-8")
                written += 1
            print(f"[{task['id']}] turn {turn}: {'tool ' + ','.join(c['name'] for c in reply.get('tool_calls', [])) if reply.get('tool_calls') else 'final answer'}", flush=True)
            messages.append(reply)
            if not reply.get("tool_calls"):
                break
            for c in reply["tool_calls"]:
                try:
                    args = json.loads(c["arguments"])
                except json.JSONDecodeError:
                    args = {}
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": run_tool(a.repo, c["name"], args)})
    print(f"wrote {written} transcripts to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
