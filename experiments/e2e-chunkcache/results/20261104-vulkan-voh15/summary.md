# e2e-chunkcache run 20261104-vulkan-voh15

## Provenance

- run_id: 20261104-vulkan-voh15
- backend: vulkan
- date: 2026-11-04T01:33:13.4500187+00:00
- server_commit: ea2279cf
- client_commit: 5f003693
- export_dirty: 0
- research_repo_commit: db8cb3f31ee6d2a4416c143cf2af38d4204567c2
- research_repo_dirty_in_e2e_dir: 3
- model_file: Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- model_hf_revision: ae44f08e1392f39c0e474af10c3ff8355c8b6688
- model_path: C:\Users\james\.cache\huggingface\hub\models--bartowski--Qwen_Qwen3-4B-Instruct-2507-GGUF\snapshots\ae44f08e1392f39c0e474af10c3ff8355c8b6688\Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- driver: AMD Radeon(TM) 8060S Graphics 32.0.32015.7029
- lock_holder: claude session 3ce8490d: ResourceLock gpu 01:41Z + gpu-lock.sh
- server_args_base: serve <model> --no-warmup --no-browser --no-ui --threads 8 --ctx-size 8192
- kv_note: server branch has no F16-default Vulkan KV (PR #1597): on Vulkan its KV is F32
- wall_s: {'phase_vk-ro': 49.5, 'total': 69.4}

## Checks

| id | result | wall s | expected | observed (abridged) |
|---|---|---|---|---|
| VOH | PASS | 49.2 | {"median(annotated) - median(plain) prompt_ms": "< 5"} | {"plain_prompt_ms": [1361.2466000000002, 1357.8509000000001, 1354.8518000000001, 1357.3157, 1357.7081, 1380.8217, 1358.9891, 1388.6712, 1361 |
