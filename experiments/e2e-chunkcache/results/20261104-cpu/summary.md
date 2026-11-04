# e2e-chunkcache run 20261104-cpu

## Provenance

- run_id: 20261104-cpu
- backend: cpu
- date: 2026-11-04T01:07:42.5256203+00:00
- server_commit: ea2279cf
- client_commit: 5f003693
- export_dirty: 0
- research_repo_commit: db8cb3f31ee6d2a4416c143cf2af38d4204567c2
- research_repo_dirty_in_e2e_dir: 3
- model_file: Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- model_hf_revision: ae44f08e1392f39c0e474af10c3ff8355c8b6688
- model_path: C:\Users\james\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots\ae44f08e1392f39c0e474af10c3ff8355c8b6688\Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- driver: AMD Radeon(TM) 8060S Graphics 32.0.32015.7029
- lock_holder: claude A2 session 3ce8490d (cpu-bench r3 01:07Z)
- server_args_base: serve <model> --no-warmup --no-browser --no-ui --threads 8 --ctx-size 8192
- kv_note: server branch has no F16-default Vulkan KV (PR #1597): on Vulkan its KV is F32
- wall_s: {'A0_build': 28.2, 'phase_off': 61.2, 'phase_ro': 323.0, 'phase_nopaged': 75.7, 'phase_write': 166.1, 'phase_write2': 155.4, 'phase_auth': 40.3, 'total': 913.0}

## Checks

| id | result | wall s | expected | observed (abridged) |
|---|---|---|---|---|
| A0 | PASS | 28.1 | {"exit": 0, "encoded": 10, "store_ckv_files": 10, "wall_s": "<= 180"} | {"exit": 0, "encoded": 10, "store_ckv_files": 10, "wall_s": 28.1, "tokens_per_second": 66.59169997197367, "encoded_tokens": 1555} |
| A1 | PASS | 61.0 | {"capabilities_status": 404, "annotated_has_chunk_cache": false, "tokens_equal": true} | {"capabilities_status": 404, "annotated_has_chunk_cache": false, "tokens_equal": true, "token_source": "logprobs"} |
| A2 | PASS | 0.0 | {"versions": [1], "selectors": ["chunk_starts"], "wire_chunkers": ["symbol-512"], "auto_validated": [], "model | {"status": 200, "versions": [1], "policies": ["exact", "shadow", "balanced", "fast", "auto"], "selectors": ["chunk_starts"], "wire_chunkers" |
| A3 | FAIL | 60.2 | {"hit": 8, "miss": 4, "ignored": 0, "hit_tokens": 1500} | {"chunks": {"annotated": 12, "prefix": 0, "hit": 0, "miss": 0, "ignored": 12}, "policy_applied": "exact", "plan_chunk_reused": 0, "predicted |
| A3g | PASS | 66.5 | {"hit": 8, "miss": 4, "ignored": 0, "hit_tokens": 1500} | {"chunks": {"annotated": 12, "prefix": 0, "hit": 8, "miss": 4, "ignored": 0}, "policy_applied": "exact", "plan_chunk_reused": 1500, "predict |
| A4 | PASS | 16.3 | "all token ids identical to plain1 (blocking and streaming)" | {"blocking": {"token_diffs": {}, "cached_tokens": {"plain1": 2672, "ann1": 2672, "plain2": 2672, "ann2": 2672, "shadow_warm": 2672, "exact_w |
| A4b | PASS | 75.5 | "all token ids identical to plain1 (blocking and streaming)" | {"blocking": {"token_diffs": {}, "cached_tokens": {"plain1": 0, "ann1": 2676, "plain2": 2676, "ann2": 2676, "shadow_warm": 2676, "exact_warm |
| A5 | PASS | 1.3 | {"strict": "400 invalid_request_error chunk_hash_mismatch", "non_strict": "200 + warning chunk_hash_mismatch"} | {"strict_status": 400, "strict_type": "invalid_request_error", "strict_code": "chunk_hash_mismatch", "nonstrict_status": 200, "nonstrict_war |
| A6 | FAIL | 58.3 | {"message_delta.chunk_cache.chunks": {"hit": 2, "miss": 1, "ignored": 0}} | {"events": ["content_block_delta", "content_block_start", "content_block_stop", "message_delta", "message_start", "message_stop", "ping"], " |
| A6m | PASS | 58.7 | {"message_delta.chunk_cache.chunks": {"hit": 8, "miss": 4, "ignored": 0}} | {"report_present": true, "chunks": {"annotated": 12, "prefix": 0, "hit": 8, "miss": 4, "ignored": 0}, "warnings": []} |
| A7 | PASS | 61.4 | {"exit": 0, "chunks": {"hit": 8, "miss": 4, "ignored": 0}} | {"exit": 0, "chunks": {"annotated": 12, "prefix": 0, "hit": 8, "miss": 4, "ignored": 0}, "outcome": {"annotated": true, "skip_reason": null, |
| A8 | PASS | 139.0 | {"encode_queued_1st": 0, "encode_queued_2nd": 719, "store.entries": 14, "third_request_F3_status": "hit"} | {"f3_annotated_chunks": 4, "f3_tokens": 719, "max_f3_chunk_tokens": 368, "encode_queued_1st": 0, "encode_queued_2nd": 719, "warnings_2nd": [ |
| A9 | PASS | 19.3 | {"same key file names": true, "payload bytes equal": true, "status lists F3 stored": true} | {"cli_exit": 0, "cli_files": 5, "server_f3_files": 4, "f3_keys": 5, "names_equal_for_server_written": true, "payload_differences": {}, "sele |
| A10 | FAIL | 7.5 | {"prewarm.queued": 1, "default evict deletes nothing": true, "path evict removes F3 files": true, "CLI F1/F2 f | {"prewarm": {"status": 200, "body": {"requested": 1, "already_stored": 0, "queued": 1, "queued_tokens": 169, "refused": 0, "refused_reasons" |
| A10r | PASS | 155.1 | {"prewarm.queued": 1, "default evict deletes nothing": true, "path evict removes F3 files": true, "CLI F1/F2 f | {"entries_after_f3_encode": 14, "prewarm": {"status": 200, "body": {"requested": 1, "already_stored": 0, "queued": 1, "queued_tokens": 169,  |
| A0r | PASS | 23.2 | {"encoded": 10, "indexed_chunks": 10} | {"exit": 0, "encoded": 10, "indexed_chunks": 10, "store_ckv_files": 10, "wall_s": 23.2} |
| A11 | PASS | 40.1 | {"no key": 401, "K_A F1 hit": 0, "K_A F4 hit": 1, "K_B F4 hit": 0, "K_B namespace evict leaves K_A": true, "K_ | {"no_key_status": 401, "K_A_shadow_F1_hit": {"annotated": 4, "prefix": 0, "hit": 0, "miss": 4, "ignored": 0}, "prewarm_K_A": {"status": 200, |
| A12 | PASS | 0.0 | {"hit": 2, "miss": 5, "prefix": 0, "ignored": 0, "tokens": {"prompt": 1896, "prefix_reused": 0, "prefix_reused | {"delta_hit": 2.0, "delta_miss": 5.0, "delta_prefix": 0.0, "delta_ignored": 0.0, "tokens_prompt": {"delta": 1896.0, "present": true}, "token |

## Analysis (A2, written by hand)

Run r3 of three: r1 ran on Vulkan by accident (--device auto) and was discarded; r2 timed out in A11 (driver bug: identical
probes reported prefix, never hit; plus one unexplained hung request, see README). A4 and A4b were rerun with a cold plain
baseline in results/20261104-cpu-a4cold (the r3 A4 plain1 was restored from A3g's identical prompt; both pass).

Passed: A0 A0r A1 A2 A3g A4 A4b A5 A6m A7 A8 A9 A10r A11 A12. Failed (findings, no workaround in the script): A3 (F-A1), A6 (F-A2),
A10 (F-A3, plan expectation). Owners and the Vulkan numbers: experiments/e2e-chunkcache/README.md.
Phase wall s: A0 28, off 61, ro 323, nopaged 76, write 166, write2 155, auth 40; total 913 (budget 20 min, hard 30 min).
Box: idle at start (CPU 4-12%, 100 GB free); r2 (same code) ran about 1.5x faster than r3 (cold 2.4K-token prefill 31.6 s vs 50 s),
so timings here are not a benchmark. Locks (box clock, UTC): cpu-bench r3 01:07-01:23Z, A4 cold rerun 01:23-01:30Z.
