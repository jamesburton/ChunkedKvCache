# e2e-chunkcache: Phase I5 Part A

First scripted end-to-end run of the chunk cache as it exists on `feature/chunk-cache-server`: CLI-built store ->
`dotllm serve --chunk-cache` -> annotated OpenAI / Anthropic requests, on the real Qwen3-4B-Instruct-2507 Q4_K_M.
No request reuses K/V yet (applied reuse is Part B). Plan: `docs/superpowers/plans/2026-11-03-phase-i5-applied-reuse.md`.

Files: `run.ps1` (orchestration), `e2e.py` (stdlib driver and checks), `test_e2e_checks.py` (self-test, no model),
`mutants.py` (mutant runner for the self-test), `ClientSmoke/` (A7, the C_A client).

Run: see the header of `run.ps1`. Self-test: `python -I experiments/e2e-chunkcache/test_e2e_checks.py`.
(Results table and verdict are filled in by A2-A4.)
