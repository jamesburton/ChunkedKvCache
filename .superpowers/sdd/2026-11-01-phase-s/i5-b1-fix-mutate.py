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
    ("F1", "empty promptTokens accepted by AssembleAt", CA, "if (explicitPositions && promptTokens.IsEmpty)", "if (explicitPositions && promptTokens.IsEmpty && promptTokens.Length > 0)"),
    ("F2", "Plan ignores expectedPromptIds", RL, "if (!expectedPromptIds.IsEmpty && !expectedPromptIds.SequenceEqual(promptIds))", "if (!expectedPromptIds.IsEmpty && expectedPromptIds.Length != promptIds.Length)"),
    ("F3", "straddling hit reported as inside the prefix", RL, ": hitEnd <= restoredRows ? DropReasons.InsidePrefix", ": h.TokenStart < restoredRows ? DropReasons.InsidePrefix"),
    ("F4", "too-little-reuse hits not reported as dropped", RL, "foreach (ChunkPlacement p in placements) dropped.Add(new DroppedHit(p.SpanIndex, Reasons.TooLittleReuse));", ""),
    ("F5", "prefix covering the prompt reported as no_hits", RL, "return None(restoredRows, Reasons.PrefixCoversPrompt,", "return None(restoredRows, Reasons.NoHits,"),
    ("F6", "prompt-token requirement also applied to Assemble", CA, "if (explicitPositions && promptTokens.IsEmpty)", "if (promptTokens.IsEmpty && (explicitPositions || !explicitPositions))"),
    ("F7", "hole not selected (NaN test must kill it too)", RL, "for (int pos = cursor; pos < p.Position; pos++) selection.Add(pos);", "for (int pos = cursor; pos < p.Position; pos++) { }"),
    ("F8", "dropped list not sorted by span index", RL, "dropped.Sort((a, b) => a.SpanIndex.CompareTo(b.SpanIndex));", "dropped.Sort((a, b) => 0);"),
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
