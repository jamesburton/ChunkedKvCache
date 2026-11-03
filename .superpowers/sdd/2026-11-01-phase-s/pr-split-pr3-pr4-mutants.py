"""PR split, PRs 3 and 4: re-run the cited library mutants against each cut's own tests.

Usage: python -I pr-split-pr3-pr4-mutants.py <set: pr03|pr04> <git-archive copy root> <log> [ids...]

The copy is `git archive pr/chunkreuse-core` (pr03) or `git archive pr/chunkreuse-store` (pr04) extracted to scratch
(never a live worktree). Each mutant: replace text in one file (pattern must occur exactly once), build the unit tests
(Release, -m:2), run `FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse` (CPU, DOTLLM_SKIP_VULKAN=1), record the failing
tests, restore the file byte for byte. Mutant ids and edits are the originals from phase-i-task-1/2/2-fix/5-mutate.py and
phase-i-task-5-mutants.py; G09/G10/F13 (task-3 logs, no script kept) are re-created from their descriptions.
"""
import os, re, subprocess, sys

SET, ROOT, LOG = sys.argv[1], sys.argv[2], sys.argv[3]
ONLY = set(sys.argv[4:])

KEY = "src/DotLLM.ChunkReuse/Store/ChunkKey.cs"
NS = "src/DotLLM.ChunkReuse/Store/ChunkNamespace.cs"
FP = "src/DotLLM.ChunkReuse/ChunkFingerprint.cs"
TOK = "src/DotLLM.ChunkReuse/Corpus/ChunkTokenization.cs"
LIN = "src/DotLLM.ChunkReuse/Corpus/LinesChunker.cs"
FIX = "src/DotLLM.ChunkReuse/Corpus/FixedSizeChunker.cs"
WIRE = "src/DotLLM.ChunkReuse/Corpus/WireChunking.cs"
FCS = "src/DotLLM.ChunkReuse/Store/FileChunkStore.cs"
SCA = "src/DotLLM.ChunkReuse/Store/StoredContextAssembler.cs"

APPEND_NS = "        AppendString(hash, Scheme);\r\n        AppendString(hash, @namespace, StrictUtf8);\r\n"

PR03 = [
    # phase-i-task-5 (Task 5): wire chunking in core files
    ("T5-M2", "hash over UTF-16", WIRE, [("SHA256.HashData(Encoding.UTF8.GetBytes(text))", "SHA256.HashData(Encoding.Unicode.GetBytes(text))")]),
    ("T5-M3", "round trip compares lengths only", WIRE,
     [("if (!ids.AsSpan().SequenceEqual(c.TokenIds)) failed.Add(c.Id);", "if (ids.Length != c.TokenIds.Length) failed.Add(c.Id);")]),
    ("T5-M12", "FixedSizeChunker id slices eligible", FIX,
     [("EndOffset = endOffset, WireEligible = false });", "EndOffset = endOffset, WireEligible = true });")]),
    ("T5-M13", "lines-512 on the allow-list now", WIRE,
     [('FrozenSet.Create(StringComparer.Ordinal, "symbol-512");', 'FrozenSet.Create(StringComparer.Ordinal, "symbol-512", "lines-512");')]),
    ("T5-M14", "IsWireChunker ignores the list (any symbol-*)", WIRE,
     [("return Eligible.Contains(chunkerName);", 'return chunkerName.StartsWith("symbol-", StringComparison.Ordinal);')]),
    # phase-i-task-5 (Task 5b): chunk tokenisation
    ("B-M1", "unmarked EncodeRaw", TOK,
     [("return tokenizer.EncodeRaw(tokenizer.MarkUntrustedSpecials(chunkText));", "return tokenizer.EncodeRaw(chunkText);")]),
    ("B-M2", "marking applied twice (expected equivalent: marking is idempotent)", TOK,
     [("return tokenizer.EncodeRaw(tokenizer.MarkUntrustedSpecials(chunkText));",
       "return tokenizer.EncodeRaw(tokenizer.MarkUntrustedSpecials(tokenizer.MarkUntrustedSpecials(chunkText)));")]),
    ("B-M3", "Encode (BOS framing) instead of EncodeRaw", TOK,
     [("return tokenizer.EncodeRaw(tokenizer.MarkUntrustedSpecials(chunkText));", "return tokenizer.Encode(tokenizer.MarkUntrustedSpecials(chunkText));")]),
    ("B-M7", "LinesChunker rest-fits check on EncodeRaw", LIN, [("ChunkTokenization.Encode(_tokenizer, text[start..])", "_tokenizer.EncodeRaw(text[start..])")]),
    ("B-M8", "LinesChunker binary-search probes on bare EncodeRaw", LIN,
     [("ChunkTokenization.Encode(_tokenizer, text[start..mid])", "_tokenizer.EncodeRaw(text[start..mid])")]),
    ("B-M9", "LinesChunker line-end probe on EncodeRaw", LIN,
     [("ChunkTokenization.Encode(_tokenizer, text[start..(i + 1)])", "_tokenizer.EncodeRaw(text[start..(i + 1)])")]),
    ("B-M10", "LinesChunker CRLF back-off probe on EncodeRaw", LIN,
     [("ChunkTokenization.Encode(_tokenizer, text[start..end])", "_tokenizer.EncodeRaw(text[start..end])")]),
    ("B-M11", "FixedSizeChunker on EncodeRaw", FIX, [("ChunkTokenization.Encode(_tokenizer, file.Text)", "_tokenizer.EncodeRaw(file.Text)")]),
    ("B-M12", "VerifyRoundTrip on EncodeRaw", WIRE, [("ChunkTokenization.Encode(tokenizer, textOf(c))", "tokenizer.EncodeRaw(textOf(c))")]),
    # phase-i-task-2 (namespace in the key) — key / namespace files only
    ("N1", "namespace not hashed", KEY, [(APPEND_NS, "        AppendString(hash, Scheme);\r\n")]),
    ("N2", "default namespace skipped (null-skip), scheme v4", KEY,
     [(APPEND_NS, "        AppendString(hash, Scheme);\r\n        if (@namespace.Length > 0) AppendString(hash, @namespace, StrictUtf8);\r\n")]),
    ("N2b", "default namespace skipped and scheme left at v3", KEY,
     [(APPEND_NS, "        AppendString(hash, Scheme);\r\n        if (@namespace.Length > 0) AppendString(hash, @namespace, StrictUtf8);\r\n"),
      ('"chunk-key/v4"', '"chunk-key/v3"')]),
    ("N3", "namespace hashed but the scheme string not bumped", KEY, [('"chunk-key/v4"', '"chunk-key/v3"')]),
    ("N4", "namespace hashed without its length prefix", KEY,
     [(APPEND_NS, "        AppendString(hash, Scheme);\r\n        hash.AppendData(Encoding.UTF8.GetBytes(@namespace));\r\n")]),
    ("N5", "namespace hashed after the tokens (field order)", KEY,
     [(APPEND_NS, "        AppendString(hash, Scheme);\r\n"),
      ("        return new ChunkKey(Convert.ToHexStringLower(hash.GetHashAndReset()));",
       "        AppendString(hash, @namespace, StrictUtf8);\r\n        return new ChunkKey(Convert.ToHexStringLower(hash.GetHashAndReset()));")]),
    ("N8", "ForApiKey returns the full 64-hex digest", NS,
     [("Convert.ToHexStringLower(digest[..(DigestHexChars / 2)])", "Convert.ToHexStringLower(digest)")]),
    ("N9", "ForApiKey drops the k- prefix", NS, [('return "k-" + Convert', "return Convert")]),
    ("N10", "ForApiKey hashes UTF-16 instead of UTF-8", NS, [("Encoding.UTF8.GetBytes(apiKey)", "Encoding.Unicode.GetBytes(apiKey)")]),
    ("N11", "ForApiKey accepts an empty key", NS,
     [("ArgumentException.ThrowIfNullOrEmpty(apiKey);", "ArgumentNullException.ThrowIfNull(apiKey);")]),
    ("N12", "ForApiKey returns the key itself (no digest)", NS,
     [('return "k-" + Convert.ToHexStringLower(digest[..(DigestHexChars / 2)]);', 'return "k-" + apiKey;')]),
    # phase-i-task-2-fix (validity rule)
    ("F1", "ChunkKey.Create skips the validity rule (null check only)", KEY,
     [("        ChunkNamespace.Validate(@namespace, nameof(@namespace));\r\n\r\n", "        ArgumentNullException.ThrowIfNull(@namespace);\r\n\r\n")]),
    ("F2", "namespace encoded with the replacing UTF-8 encoder (expected equivalent: the rule admits ASCII only)", KEY,
     [("AppendString(hash, @namespace, StrictUtf8);", "AppendString(hash, @namespace);")]),
    ("F3", "F1 + F2: no rule and the replacing encoder (lone surrogates collide)", KEY,
     [("        ChunkNamespace.Validate(@namespace, nameof(@namespace));\r\n\r\n", "        ArgumentNullException.ThrowIfNull(@namespace);\r\n\r\n"),
      ("AppendString(hash, @namespace, StrictUtf8);", "AppendString(hash, @namespace);")]),
    ("F4", "IsValid accepts upper case", NS, [("(>= 'a' and <= 'z') or (>= '0'", "(>= 'a' and <= 'z') or (>= 'A' and <= 'Z') or (>= '0'")]),
    ("F5", "IsValid has no length bound", NS, [("if (value is null || value.Length > MaxLength || value == ReservedDefaultName) return false;", "if (value is null || value == ReservedDefaultName) return false;")]),
    ("F6", "IsValid accepts '/' and '\\\\'", NS, [("or '.' or '_' or '-'))", "or '.' or '_' or '-' or '/' or '\\\\'))")]),
    ("F7", "IsValid accepts anything non-null", NS, [("            if (c is not", "            if (false && c is not")]),
    ("F8", "Validate accepts invalid values (null check only)", NS, [("        if (!IsValid(value))\r\n", "        if (false)\r\n")]),
    ("F10", "IsValid treats null as valid", NS,
     [("if (value is null || value.Length > MaxLength || value == ReservedDefaultName) return false;", "if (value is null) return true; if (value.Length > MaxLength || value == ReservedDefaultName) return false;")]),
    ("F11", "reserved name 'default' accepted (Task 4b rule)", NS,
     [("if (value is null || value.Length > MaxLength || value == ReservedDefaultName) return false;", "if (value is null || value.Length > MaxLength) return false;")]),
    # task-3 logs (re-created): key encoding
    ("G09", "key field order swapped (fingerprint / tokenizer)", KEY,
     [("        AppendString(hash, modelFingerprint);\r\n        AppendString(hash, tokenizerId);\r\n",
       "        AppendString(hash, tokenizerId);\r\n        AppendString(hash, modelFingerprint);\r\n")]),
    ("G10", "key token count not hashed", KEY, [("        AppendInt(hash, tokenIds.Length);\r\n", "")]),
    ("F13", "positioning not hashed", KEY, [("        AppendInt(hash, (int)positioning);\r\n", "")]),
    # phase-i-task-1: fingerprint backend field
    ("M11", "CPU fingerprint also hashes the backend field", FP,
     [("        if (!string.Equals(backend, ChunkBackendTags.Cpu, StringComparison.Ordinal))\r\n            Append(sb, \"backend\", backend);",
       "        Append(sb, \"backend\", backend);")]),
    ("M12", "fingerprint omits the backend for every tag", FP,
     [("        if (!string.Equals(backend, ChunkBackendTags.Cpu, StringComparison.Ordinal))\r\n            Append(sb, \"backend\", backend);", "")]),
    # phase-r-p task-4 (encoder / assembler / RoPE shift), re-created on today's code (backend seam)
    ("RP-M1", "RoPE delta sign flipped", "src/DotLLM.ChunkReuse/RopeShift.cs",
     [("float angle = positionDelta * freq;", "float angle = -positionDelta * freq;")]),
    ("RP-M2", "RoPE pairing swapped (NeoX <-> Norm)", "src/DotLLM.ChunkReuse/RopeShift.cs",
     [("bool neoX = rope.Type == RoPEType.NeoX;", "bool neoX = rope.Type != RoPEType.NeoX;")]),
    ("RP-M4", "CPU backend never shifts keys", "src/DotLLM.ChunkReuse/Backends/CpuChunkBackend.cs",
     [("RopeShift.Apply(k, _config.HeadDim, delta, in rope);", "")]),
    ("RP-M5", "assembly starts at 0 instead of CurrentLength", "src/DotLLM.ChunkReuse/ChunkAssembler.cs",
     [("int start = destination.CurrentLength;", "int start = 0;")]),
    ("RP-R1b", "RopeShift skips the last head of the slice", "src/DotLLM.ChunkReuse/RopeShift.cs",
     [("offset < keys.Length; offset += headDim", "offset < keys.Length - headDim; offset += headDim")]),
    ("RP-R2", "encoder context guard removed", "src/DotLLM.ChunkReuse/ChunkEncoder.cs",
     [("if (n > model.Config.MaxSequenceLength)", "if (n < 0)")]),
    ("RP-R3", "assembler capacity guard removed", "src/DotLLM.ChunkReuse/ChunkAssembler.cs",
     [("if (total > destination.MaxLength)", "if (total < 0)")]),
]

PR04 = [
    # phase-i-task-1 (backend tag in the .ckv header, store-backed assembly)
    ("M1", "header written but tag never checked on read (any bytes accepted)", FCS,
     [("        foreach (byte b in tagBytes)\r\n            if (!IsTagChar(b)) return false;", "")]),
    ("M1b", "reader ignores the header tag and reports cpu", FCS, [("Encoding.ASCII.GetString(tagBytes), tokens", "\"cpu\", tokens")]),
    ("M2", "assembler keys on cpu regardless of the backend", SCA,
     [("RopeParameters.FromConfig(config), Backend, KvDtype.F32, tokenIds", "RopeParameters.FromConfig(config), \"cpu\", KvDtype.F32, tokenIds")]),
    ("M3", "v1 accepted (read as cpu, no tag field)", FCS,
     [("        if (!r.Int32(out int version) || version != FormatVersion) return false;",
       "        if (!r.Int32(out int version) || (version != FormatVersion && version != 1)) return false;"),
      ("        if (!r.Int32(out int tagLen) || tagLen <= 0 || tagLen > MaxBackendTagBytes) return false;\r\n        if (!r.Bytes(tagLen, out ReadOnlySpan<byte> tagBytes)) return false;",
       "        ReadOnlySpan<byte> tagBytes = \"cpu\"u8;\r\n        if (version == FormatVersion) {\r\n        if (!r.Int32(out int tagLen) || tagLen <= 0 || tagLen > MaxBackendTagBytes) return false;\r\n        if (!r.Bytes(tagLen, out tagBytes)) return false; }")]),
    ("M4", "hit check ignores the entry's backend", SCA,
     [("        if (!string.Equals(entry.Backend, Backend, StringComparison.Ordinal)) return false;\r\n", "")]),
    ("M5", "identity check recomputes the fingerprint with the cpu tag", SCA, [("TokenizerId, Backend);", "TokenizerId, \"cpu\");")]),
    ("M6", "misses encoded on the CPU backend (entries stamped cpu)", SCA, [("_encoder.Encode(model, backend, ids)", "_encoder.Encode(model, ids)")]),
    ("M7", "ForModel fingerprints with the cpu tag for every backend", SCA,
     [("        string tag = backend?.Tag ?? ChunkBackendTags.Cpu;", "        string tag = ChunkBackendTags.Cpu;")]),
    ("M8", "Put does not validate the backend tag", FCS, [("        if (!IsWellFormedBackendTag(entry.Backend))\r\n", "        if (false)\r\n")]),
    ("M9", "HeaderBytes omits the backend tag", FCS, [(" + 4 + Encoding.UTF8.GetByteCount(backend) + 8", " + 8")]),
    ("M10", "destination not vetted by the backend", SCA,
     [("        backend.RequireCache(destination); // CPU", "        // backend.RequireCache(destination); // CPU")]),
    ("M11", "CPU fingerprint also hashes the backend field", FP,
     [("        if (!string.Equals(backend, ChunkBackendTags.Cpu, StringComparison.Ordinal))\r\n            Append(sb, \"backend\", backend);",
       "        Append(sb, \"backend\", backend);")]),
    ("M12", "fingerprint omits the backend for every tag", FP,
     [("        if (!string.Equals(backend, ChunkBackendTags.Cpu, StringComparison.Ordinal))\r\n            Append(sb, \"backend\", backend);", "")]),
    ("M13", "tag length upper bound not checked", FCS, [(" || tagLen > MaxBackendTagBytes) return false;", ") return false;")]),
    ("TF1", "header comparison applied only for the cpu assembler (phase-i-task-1 F1)", SCA,
     [("        if (!string.Equals(entry.Backend, Backend, StringComparison.Ordinal)) return false;",
       "        if (Backend == \"cpu\" && !string.Equals(entry.Backend, Backend, StringComparison.Ordinal)) return false;")]),
    ("TF2", "Put keeps any valid entry regardless of its tag (phase-i-task-1 F2)", FCS,
     [("so it cannot stick.\r\n        if (HoldsValidEntry(key, entry.Backend)) return;", "so it cannot stick.\r\n        if (Contains(key)) return;")]),
    # phase-i-task-2: namespace through the assembler (+ N1 to show the moved index test is not needed)
    ("N1", "namespace not hashed", KEY, [(APPEND_NS, "        AppendString(hash, Scheme);\r\n")]),
    ("N6", "Assemble looks up in the default namespace whatever it is given", SCA,
     [("ChunkKey key = KeyOf(config, ids, @namespace);", "ChunkKey key = KeyOf(config, ids);")]),
    ("N7", "KeyOf drops its namespace", SCA, [("tokenIds,\r\n            @namespace: @namespace);", "tokenIds);")]),
    ("N14", "Assemble and KeyOf accept a null namespace as the default (re-created on today's Validate call)", SCA,
     [("        ArgumentNullException.ThrowIfNull(store);\r\n        ChunkNamespace.Validate(@namespace, nameof(@namespace));\r\n",
       "        ArgumentNullException.ThrowIfNull(store);\r\n        @namespace ??= ChunkNamespace.Default;\r\n        ChunkNamespace.Validate(@namespace, nameof(@namespace));\r\n"),
      ("        ArgumentNullException.ThrowIfNull(config);\r\n        ArgumentNullException.ThrowIfNull(@namespace);\r\n",
       "        ArgumentNullException.ThrowIfNull(config);\r\n        @namespace ??= ChunkNamespace.Default;\r\n")]),
    ("F9", "Assemble checks only null up front (KeyOf validates before the first store read)", SCA,
     [("        ChunkNamespace.Validate(@namespace, nameof(@namespace));\r\n", "        ArgumentNullException.ThrowIfNull(@namespace);\r\n")]),
    # store side of the split key tests (new in the prep): a changed key must miss
    ("S1", "FileChunkStore.Contains ignores the key name (any entry file counts)", FCS,
     [("    public bool Contains(ChunkKey key)\r\n    {\r\n", "    public bool Contains(ChunkKey key)\r\n    {\r\n        if (Keys().Any()) return true;\r\n")]),
]

MUTANTS = {"pr03": PR03, "pr04": PR04}[SET]
env = dict(os.environ, DOTLLM_SKIP_VULKAN="1")


def run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")


def build_and_test():
    b = run(["dotnet", "build", "tests/DotLLM.Tests.Unit", "-c", "Release", "-m:2", "-v", "q", "-nologo"])
    if b.returncode != 0:
        errs = sorted(set(l.strip() for l in b.stdout.splitlines() if ": error" in l))[:3]
        return None, errs
    t = run(["dotnet", "test", "tests/DotLLM.Tests.Unit", "-c", "Release", "--no-build",
             "--filter", "FullyQualifiedName~DotLLM.Tests.Unit.ChunkReuse", "--", "xUnit.MaxParallelThreads=2"])
    failed = sorted(set(re.findall(r"^\s+Failed (\S+)", t.stdout, re.M)))
    summary = [l.strip() for l in t.stdout.splitlines() if "Passed!" in l or "Failed!" in l]
    return (failed, summary), None


with open(LOG, "a", encoding="utf-8") as log:
    res, errs = build_and_test()
    log.write(f"# set {SET}, copy {ROOT}\nBASELINE: {'BUILD FAILED ' + str(errs) if res is None else res[1]} failed={[] if res is None else res[0]}\n")
    log.flush()
    for mid, desc, rel, edits in MUTANTS:
        if ONLY and mid not in ONLY:
            continue
        path = os.path.join(ROOT, rel)
        orig = open(path, "rb").read()
        text = orig.decode("utf-8")
        ok = True
        for old, new in edits:
            if "\r\n" not in text:
                old, new = old.replace("\r\n", "\n"), new.replace("\r\n", "\n")
            if text.count(old) != 1:
                log.write(f"{mid}: PATTERN NOT FOUND ONCE ({text.count(old)}): {old[:80]!r}\n"); ok = False; break
            text = text.replace(old, new)
        if not ok:
            log.flush(); continue
        try:
            open(path, "wb").write(text.encode("utf-8"))
            res, errs = build_and_test()
            if res is None:
                log.write(f"{mid} ({desc}): BUILD FAILED {errs}\n"); log.flush(); continue
            failed, summary = res
            log.write(f"{mid} ({desc}): {'KILLED' if failed else 'SURVIVED'} {summary}\n")
            for f in failed:
                log.write(f"    {f}\n")
            log.flush()
        finally:
            open(path, "wb").write(orig)
            assert open(path, "rb").read() == orig
    log.write("done\n")
