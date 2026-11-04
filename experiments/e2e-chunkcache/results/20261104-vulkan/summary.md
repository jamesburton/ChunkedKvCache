# e2e-chunkcache run 20261104-vulkan

## Provenance

- run_id: 20261104-vulkan
- backend: vulkan
- date: 2026-11-04T01:31:30.4974467+00:00
- server_commit: ea2279cf
- client_commit: 5f003693
- export_dirty: 0
- research_repo_commit: db8cb3f31ee6d2a4416c143cf2af38d4204567c2
- research_repo_dirty_in_e2e_dir: 3
- model_file: Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- model_hf_revision: ae44f08e1392f39c0e474af10c3ff8355c8b6688
- model_path: C:\Users\james\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots\ae44f08e1392f39c0e474af10c3ff8355c8b6688\Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- driver: AMD Radeon(TM) 8060S Graphics 32.0.32015.7029
- lock_holder: claude session 3ce8490d: ResourceLock gpu 01:37Z + gpu-lock.sh e2e-chunkcache
- server_args_base: serve <model> --no-warmup --no-browser --no-ui --threads 8 --ctx-size 8192
- kv_note: server branch has no F16-default Vulkan KV (PR #1597): on Vulkan its KV is F32
- wall_s: {'phase_vk-ro': 42.8, 'phase_vk-write': 13.6, 'total': 82.8}

## Checks

| id | result | wall s | expected | observed (abridged) |
|---|---|---|---|---|
| V1 | PASS | 23.3 | {"model.backend": "vulkan", "A4 passes": true} | {"blocking": {"token_diffs": {}, "cached_tokens": {"plain1": 0, "ann1": 0, "plain2": 0, "ann2": 0, "shadow_warm": 0, "exact_warm": 0}, "cach |
| V2 | PASS | 1.9 | {"hit": 0, "miss": 12} | {"chunks": {"annotated": 12, "prefix": 0, "hit": 0, "miss": 12, "ignored": 0}, "policy_applied": "exact", "warnings": []} |
| V3 | PASS | 13.3 | {"warning": "chunk_encode_skipped", "store listing byte-identical": true} | {"warning_codes": ["chunk_encode_skipped"], "listing_identical": true, "files": 22, "encode_queued": [0, 0]} |
| VOH | FAIL | 17.3 | {"median(annotated) - median(plain) prompt_ms": "< 5"} | {"plain_prompt_ms": [1355.5477, 1360.4468000000002, 1357.1390000000001, 1363.4831000000001, 1358.8569], "annotated_prompt_ms": [1364.8042, 1 |

## Analysis (A3, written by hand)

V1, V2, V3 PASS on the CPU-built store (Vulkan server, F32 KV, model.backend vulkan). VOH of this run (5 pairs): +5.9 ms median;
an earlier 5-pair run gave -5.4 ms; 15 pairs in ../20261104-vulkan-voh15: -0.2 ms.
Locks (box clock, UTC): gpu plus gpu-lock.sh e2e-chunkcache 01:31-01:33Z for this run and 01:33-01:34Z for the 15-pair VOH run;
a first attempt 01:30-01:31Z failed in the driver (V3 read an exclusively held lock file) and was rerun after the fix.
