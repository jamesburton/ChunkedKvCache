"""Phase I5 B1 mutants: each mutant edits a git-archive copy, builds the unit-test project, runs the B1 + assembly tests, reverts.
Usage: python -I mutate.py <archive-copy-dir> <log> [ids...]"""
import subprocess, sys, pathlib, re

ROOT = pathlib.Path(sys.argv[1])
LOG = pathlib.Path(sys.argv[2])
ONLY = set(sys.argv[3:])
RL = "src/DotLLM.ChunkReuse/Applied/ReuseLayout.cs"
CA = "src/DotLLM.ChunkReuse/ChunkAssembler.cs"
FILTER = ("(FullyQualifiedName~ReuseLayoutTests|FullyQualifiedName~ChunkAssemblerAtTests|FullyQualifiedName~ChunkAssemblyTests"
          "|FullyQualifiedName~VulkanAssemblyTests|FullyQualifiedName~BackendSeamTests|FullyQualifiedName~StoredAssemblyTests)"
          "&FullyQualifiedName!~DotLLM.Tests.Unit.Vulkan&Category!=GPU")

MUTANTS = [
    ("M1", "hole not selected", RL, "for (int pos = cursor; pos < p.Position; pos++) selection.Add(pos);", "for (int pos = cursor; pos < p.Position; pos++) { }"),
    ("M2", "selection sorted descending", RL, "Array.Sort(sorted);", "Array.Sort(sorted); Array.Reverse(sorted);"),
    ("M3", "shift by placement index instead of position (host)", CA, "_backend.ShiftKeys(destination, offset, n, offset, _rope);\n            }\n        }\n        catch\n        {\n            // Row writes", "_backend.ShiftKeys(destination, offset, n, c, _rope);\n            }\n        }\n        catch\n        {\n            // Row writes"),
    ("M4", "tail allowed to be empty", RL, "if (hitEnd >= promptLength)", "if (hitEnd > promptLength)"),
    ("M5", "straddling hit placed", RL, "h.TokenStart < restoredRows || h.TokenStart < end", "h.TokenStart < end"),
    ("M5b", "straddling hit placed (both guards removed: explicit check and end starting at restoredRows)", RL, None, None),
    ("M6", "length not advanced", CA, "                    _backend.ShiftKeys(destination, offset, n, offset, _rope);\n            }\n        }\n        catch\n        {\n            // Row writes", "                    _backend.ShiftKeys(destination, offset, n, offset, _rope);\n            }\n            if (explicitPositions) destination.Rollback(start);\n        }\n        catch\n        {\n            // Row writes"),
    ("M7", "position below current length accepted", CA, "if (position < next)", "if (position < next && c > 0)"),
    ("M8", "overlapping positions accepted", CA, "if (position < next)", "if (position < next && c == 0)"),
    ("M9", "prompt-token check skipped", CA, "        if (promptTokens.IsEmpty)\n            return;", "        if (true)\n            return;"),
    ("M10", "no rollback on write failure (host)", CA, "            // Row writes advance the cache length as they go: never leave a partly assembled, partly unshifted cache behind.\n            destination.Rollback(start);", "            // mutant"),
    ("M11", "token check after the first write (not atomic)", CA, "            CheckTokens(c, at[c], chunk.TokenIds, promptTokens);\n        }\n\n        try\n        {\n            for (int c = 0; c < chunks.Count; c++)\n            {\n                ChunkKvEntry chunk = chunks[c];\n                int offset = at[c], n = chunk.TokenIds.Length;\n                for (int l = 0; l < layers; l++)\n                    _backend.WriteRows(destination, l, offset, chunk.KeysPerLayer[l], chunk.ValuesPerLayer[l]);", "        }\n\n        try\n        {\n            for (int c = 0; c < chunks.Count; c++)\n            {\n                ChunkKvEntry chunk = chunks[c];\n                int offset = at[c], n = chunk.TokenIds.Length;\n                for (int l = 0; l < layers; l++)\n                    _backend.WriteRows(destination, l, offset, chunk.KeysPerLayer[l], chunk.ValuesPerLayer[l]);\n                CheckTokens(c, at[c], chunk.TokenIds, promptTokens);"),
    ("M12", "first placed chunk treated as exact (no stand-in)", RL, None, None),
    ("M13", "budget counted over the whole region (holes included)", RL, "budget * placedRows", "budget * (end - restoredRows)"),
    ("M14", "FirstApproxRow = RegionStart", RL, "IsReuse ? Placements[0].Position : null", "IsReuse ? RegionStart : null"),
    ("M15", "ShiftDelta off by one", RL, "public int ShiftDelta => Position;", "public int ShiftDelta => Position + 1;"),
    ("M16", "overlapping hits kept", RL, "h.TokenStart < restoredRows || h.TokenStart < end", "h.TokenStart < restoredRows"),
    ("M17", "shift by placement index (resident)", CA, "                for (int l = 0; l < layers; l++)\n                    _backend.CopyRows(chunk.Cache, l, 0, destination, offset, n);\n                if (offset != 0)\n                    _backend.ShiftKeys(destination, offset, n, offset, _rope);", "                for (int l = 0; l < layers; l++)\n                    _backend.CopyRows(chunk.Cache, l, 0, destination, offset, n);\n                if (offset != 0)\n                    _backend.ShiftKeys(destination, offset, n, c + 1, _rope);"),
    ("M18", "prompt-ids length mismatch ignored", RL, "        if (promptIds.Length != promptLength)\n            return None(restoredRows, Reasons.PromptIdsChanged);\n", ""),
    ("M19", "resident cache-length check removed (reads outside the entry)", CA, "            if (chunk.Cache.CurrentLength < chunk.Length)\n                throw", "            if (false)\n                throw"),
    ("M20", "host entry shape check removed", CA, "if (chunk.KeysPerLayer[l]?.Length != expected || chunk.ValuesPerLayer[l]?.Length != expected)", "if (false)"),
    ("M21", "minimum placed rows ignored", RL, "if (placedRows < minPlacedTokens)", "if (false)"),
    ("M9b", "prompt-token check skipped (non-constant)", CA, "if (promptTokens.IsEmpty)", "if (promptTokens.IsEmpty || chunkTokens.Length > 0)"),
    ("M21b", "minimum placed rows ignored (non-constant)", RL, "if (placedRows < minPlacedTokens)", "if (placedRows < minPlacedTokens && placedRows < 0)"),
    ("M22", "rows below the region not protected: holes start at 0", RL, "int cursor = restoredRows;", "int cursor = 0;"),
]

M12_EDITS = [
    ("var chunkIds = new List<int[]>(placements.Count + 1) { new[] { 0 } };", "var chunkIds = new List<int[]>(placements.Count + 1);"),
    ("                if (c == 0)\n                    throw new InvalidOperationException(\"The chunk-starts ranking reached the stand-in chunk before the budget was spent.\");\n                selection.Add(placements[c - 1].Position + (index - starts[c]));",
     "                selection.Add(placements[c].Position + (index - starts[c]));"),
]


M5B_EDITS = [
    ("h.TokenStart < restoredRows || h.TokenStart < end", "h.TokenStart < end"),
    ("        int end = restoredRows;\n", "        int end = 0;\n"),
]


def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout + p.stderr


def norm(s):
    return s.replace("\r\n", "\n")


def main():
    out = [f"# B1 mutants on {ROOT}", ""]
    for mid, desc, rel, old, new in MUTANTS:
        if ONLY and mid not in ONLY:
            continue
        path = ROOT / rel
        orig = path.read_bytes()
        text = norm(orig.decode("utf-8"))
        edits = M12_EDITS if mid == "M12" else M5B_EDITS if mid == "M5b" else [(old, new)]
        mutated = text
        ok = True
        for o, n in edits:
            if mutated.count(o) < 1:
                ok = False
                break
            mutated = mutated.replace(o, n, 1)
        if not ok:
            out.append(f"{mid} | {desc} | PATTERN NOT FOUND")
            print(out[-1], flush=True)
            continue
        path.write_text(mutated, encoding="utf-8", newline="\n")
        try:
            rc, log = run(["dotnet", "build", "tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj", "-c", "Release", "-m:2", "-v:q", "-nologo"])
            if rc != 0:
                errs = sorted(set(re.findall(r"error [A-Z]+\d+: [^\[]*", log)))[:3]
                verdict, detail = "KILLED (build)", "; ".join(errs)
            else:
                rc, log = run(["dotnet", "test", "tests/DotLLM.Tests.Unit/DotLLM.Tests.Unit.csproj", "-c", "Release", "--no-build", "--filter", FILTER])
                failed = sorted(set(re.findall(r"^\s+Failed ([\w.]+(?:\([^)]*\))?)", log, re.M)))
                summary = re.findall(r"(Failed!|Passed!)\s+-\s+Failed:\s+(\d+), Passed:\s+(\d+)", log)
                if failed or rc != 0:
                    verdict = "KILLED"
                    detail = ", ".join(f.split(".")[-1] for f in failed[:8]) + (f" (+{len(failed) - 8})" if len(failed) > 8 else "") + f" {summary}"
                else:
                    verdict, detail = "SURVIVED", str(summary)
        finally:
            path.write_bytes(orig)
        out.append(f"{mid} | {desc} | {verdict} | {detail}")
        print(out[-1], flush=True)
    LOG.write_text("\n".join(out) + "\n", encoding="utf-8")


main()
