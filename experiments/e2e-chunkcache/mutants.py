import subprocess,os,sys,tempfile
HERE=os.path.dirname(os.path.abspath(__file__))
src=open(os.path.join(HERE,'e2e.py'),encoding='utf-8').read()
S=tempfile.mkdtemp(prefix='e2e-mutants-')
muts={
 'm1_partition_no_total_check': ('    if t.get("prompt") != total:','    if False:'),
 'm1b_partition_prefilled_derived': ('t.get("chunk_reused", 0) + t.get("prefilled", 0)\n    if t.get("prompt") != total:','t.get("chunk_reused", 0) + (t.get("prompt", 0) - t.get("prefix_reused", 0) - t.get("prefix_reused_approx", 0) - t.get("chunk_reused", 0))\n    if t.get("prompt") != total:'),
 'm2_neutrality_text_not_ids': ('    return list(record["tokens"])','    return "".join(record["tokens"])'),
 'm3_isolation_wrong_key': ('obs = {c: (reports[c].get("chunks") or {}).get("hit") for c in expect}','obs = {c: (reports["A"].get("chunks") or {}).get("hit") for c in expect}'),
 'm4_offsets_utf16': ('return len(text[:char_index].encode("utf-8"))','return len(text[:char_index].encode("utf-16-le")) // 2'),
 'm5_neutrality_no_void': ('    if token_signature(p1) != token_signature(p2):','    if False:'),
 'm6_metrics_ignores_delta': ('        if d != reported.get(st, 0):','        if False:'),
 'm7_cached_not_compared': ('    if not cached_ok:\n        ok = False','    pass'),
}
for name,(a,b) in muts.items():
    assert a in src, name
    p=os.path.join(S,name+'.py'); open(p,'w',encoding='utf-8').write(src.replace(a,b,1))
    r=subprocess.run([sys.executable,'-I',os.path.join(HERE,'test_e2e_checks.py')],env={**os.environ,'E2E_MODULE':p},capture_output=True,text=True)
    fails=[l for l in r.stderr.splitlines() if l.startswith(('FAIL:','ERROR:'))]
    print(name,'->',r.stderr.strip().splitlines()[-1],fails)
