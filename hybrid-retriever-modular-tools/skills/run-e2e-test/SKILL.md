---
name: run-e2e-test
description: |
  Run the end-to-end skill-workflow test for the chain_react_ADK/hybrid_retriever_modular
  project: tear down → start stack → scaffold a new module → save a new pipeline →
  ingest 4 sample docs → search → verify the new pipeline executed → check Streamlit UI.
  Each step prints PASS/FAIL.

  Trigger when the user says any of:
  "통합 테스트 돌려", "e2e 테스트", "전체 테스트", "스킬 워크플로우 테스트",
  "지난번처럼 테스트해", "hybrid retriever e2e", or otherwise asks to run the
  full author→register→ingest→search→UI loop.

  Do NOT trigger for the smaller `run-pipeline-eval` skill (정답률/속도 측정),
  or for unrelated pytest runs.
---

# Run E2E Skill-Workflow Test

This skill executes the bundled reproducer at
`retriever_engine/tests/e2e_skill_workflow/run_e2e_test.sh` inside a checkout of
the `hybrid_retriever_modular` project, then runs `cleanup.sh` to drop the
test-only dataset / pipeline / module file.

## Step-by-step

1. **Locate the project once per session:**

   ```bash
   PROJECT_DIR=$(find "$HOME" -type d -path "*hybrid_retriever_modular" \
     -not -path "*/.venv/*" -not -path "*/node_modules/*" 2>/dev/null | head -1)
   ```

   If empty, ask the user where the project is checked out.

2. **Run the test:**

   ```bash
   bash "$PROJECT_DIR/retriever_engine/tests/e2e_skill_workflow/run_e2e_test.sh"
   ```

   The script prints `[OK]` or `[FAIL]` per step (12 steps total) and exits
   non-zero on the first failure. Surface the last 30 lines so the user sees
   the comparison: `total / unique_docs` from step 11 proves the new
   `custom.e2e_doc_diversity` module actually ran.

3. **Always run cleanup right after** (even on failure):

   ```bash
   bash "$PROJECT_DIR/retriever_engine/tests/e2e_skill_workflow/cleanup.sh"
   ```

   This removes:
   - pipeline `e2e_test_pipeline`
   - dataset `e2e_smoke` (with its OpenSearch index, Qdrant collection, MinIO bucket)
   - module file `modules/e2e_doc_diversity.py`
   - leftover `/tmp/e2e_pipeline.json`, `/tmp/run_body.py`

   It does NOT stop containers and does NOT touch `.env`.

4. **Report briefly:**
   - PASS or FAIL + which step failed (if any)
   - The diversity-check line from step 11 (`unique_docs=N`)
   - Confirm cleanup ran cleanly

## Overrides (rarely needed)

The script honors these env vars — pass them only when the user explicitly
asks (e.g. "데이터셋 이름 다르게 해" or there's a name collision):

```
DATASET_ID=other_dataset PIPELINE_NAME=other_pipe MODULE_NAME=other_mod \
API_BASE=http://localhost:9380 UI_BASE=http://localhost:9381 \
bash "$PROJECT_DIR/retriever_engine/tests/e2e_skill_workflow/run_e2e_test.sh"
```

## Constraints

- Do NOT scaffold the module manually or hand-craft the pipeline JSON — the
  script does both via the bundled `scaffold_module.py` and the frozen
  `artifacts/`.
- Do NOT skip `cleanup.sh` — if leftovers survive, the next run's baseline
  check (`MODULE_TYPE absent`) will fail immediately.
- This is the **integration** test. For per-pipeline accuracy/speed numbers,
  use the `run-pipeline-eval` skill instead.
