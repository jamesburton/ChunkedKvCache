# e2e-chunkcache run 20261104-cpu-a4cold

## Provenance

- run_id: 20261104-cpu-a4cold
- backend: cpu
- date: 2026-11-04T01:24:06.5883914+00:00
- server_commit: ea2279cf
- client_commit: 5f003693
- export_dirty: 0
- research_repo_commit: db8cb3f31ee6d2a4416c143cf2af38d4204567c2
- research_repo_dirty_in_e2e_dir: 3
- model_file: Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- model_hf_revision: ae44f08e1392f39c0e474af10c3ff8355c8b6688
- model_path: C:\Users\james\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots\ae44f08e1392f39c0e474af10c3ff8355c8b6688\Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- driver: AMD Radeon(TM) 8060S Graphics 32.0.32015.7029
- lock_holder: claude A2 session 3ce8490d (cpu-bench supplementary 01:24Z)
- server_args_base: serve <model> --no-warmup --no-browser --no-ui --threads 8 --ctx-size 8192
- kv_note: server branch has no F16-default Vulkan KV (PR #1597): on Vulkan its KV is F32
- wall_s: {'A0_build': 28.1, 'phase_ro': 135.1, 'phase_nopaged': 135.3, 'total': 319.0}

## Checks

| id | result | wall s | expected | observed (abridged) |
|---|---|---|---|---|
| A0 | PASS | 28.0 | {"exit": 0, "encoded": 10, "store_ckv_files": 10, "wall_s": "<= 180"} | {"exit": 0, "encoded": 10, "store_ckv_files": 10, "wall_s": 28.0, "tokens_per_second": 66.24986935355346, "encoded_tokens": 1555} |
| A4 | PASS | 134.9 | "all token ids identical to plain1 (blocking and streaming)" | {"blocking": {"token_diffs": {}, "cached_tokens": {"plain1": 0, "ann1": 2672, "plain2": 2672, "ann2": 2672, "shadow_warm": 2672, "exact_warm |
| A4b | PASS | 135.0 | "all token ids identical to plain1 (blocking and streaming)" | {"blocking": {"token_diffs": {}, "cached_tokens": {"plain1": 0, "ann1": 2682, "plain2": 2682, "ann2": 2682, "shadow_warm": 2682, "exact_warm |
