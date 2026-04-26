---
name: run-pipeline-eval
description: |
  Measure 정답률 + 평균 실행속도 of saved pipelines in the chain_react_ADK/hybrid_retriever_modular
  project. One-click; ingests a sample dataset, builds (or reuses) a Korean golden QA set
  via gpt-4o-mini, then runs each pipeline against it.

  Trigger when the user says any of:
  "파이프라인 평가", "정답률 측정", "속도 측정", "evaluation 돌려",
  "pipeline accuracy/latency", "벤치마크 돌려", or otherwise asks for numeric
  comparison of saved pipelines.

  Do NOT trigger for the integration test (`run-e2e-test`) or for unrelated
  pytest runs.
---

# Run Pipeline Evaluation

This skill executes `retriever_engine/evaluation/eval.py` inside a checkout of
the `hybrid_retriever_modular` project. The script is fully self-documenting
via `--help`.

## Step-by-step

1. **Locate the project once per session:**

   ```bash
   PROJECT_DIR=$(find "$HOME" -type d -path "*hybrid_retriever_modular" \
     -not -path "*/.venv/*" 2>/dev/null | head -1)
   EVAL_DIR="$PROJECT_DIR/retriever_engine/evaluation"
   PY="$PROJECT_DIR/retriever_engine/.venv/bin/python"
   ```

   If empty, ask the user where the project is.

2. **Pick a mode:**

   | User wants                              | Command                                      |
   |-----------------------------------------|----------------------------------------------|
   | All saved pipelines (default)           | `cd "$EVAL_DIR" && "$PY" eval.py`            |
   | One specific pipeline                   | `cd "$EVAL_DIR" && "$PY" eval.py --pipeline NAME` |
   | Skip ingest (data already in eval_kb)   | add `--skip-ingest`                          |
   | Rebuild the golden QA set               | add `--regen-golden`                         |
   | All options                             | `"$PY" eval.py --help`                       |

   On the first run in a fresh stack, omit both flags so it auto-ingests +
   auto-builds the golden. On subsequent runs in the same session, add
   `--skip-ingest` to save time and embedding cost.

3. **Report the table verbatim** — the script already prints something like:

   ```
   pipeline                   n       정답률       평균 ms
   ----------------------------------------------------
   hybrid_rag_v1             32     96.9%        21.0
   pytest_pipeline_v1        32     96.9%        16.0
   pipeline_a                32     84.4%        15.1
   pipeline_b                32     84.4%        14.3
   ```

   That table is the deliverable. Do not invent additional metrics; the only
   two columns are 정답률 (정답 chunk 가 응답 top-K 안에 있는 비율) and
   평균 ms (`POST /api/v1/pipelines/{name}/run` wall-clock 평균).

4. **Cleanup is optional** — `eval_kb` dataset is reusable across runs.
   Run cleanup only when the user explicitly asks:

   ```bash
   bash "$EVAL_DIR/cleanup.sh"          # drop dataset only
   bash "$EVAL_DIR/cleanup.sh" --hard   # ALSO drop golden/ and reports/
   ```

## Constraints

- Do NOT add metrics ("R@1", "MRR", "nDCG", token cost, percentiles, …) to the
  output. The table is intentionally two columns.
- Do NOT regenerate the golden every run; the frozen `golden/qa.jsonl` is
  what makes runs comparable. Only pass `--regen-golden` when the user asks
  for a fresh set.
- The script reads `API_KEY` and `EMBEDDING_API_KEY` from
  `retriever_engine/.env`; do NOT prompt the user for them.
- This is the **measurement** tool. For end-to-end "does the new module loop
  still work" verification, use the `run-e2e-test` skill instead.
