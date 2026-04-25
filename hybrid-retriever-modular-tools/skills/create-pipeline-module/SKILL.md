---
name: create-pipeline-module
description: |
  Author a new pipeline module for the chain_react_ADK/hybrid_retriever_modular project
  and verify it auto-registers in the runtime registry and the Streamlit pipeline builder UI.

  Trigger when the user says any of:
  "하이브리드 리트리버 모듈 만들어", "파이프라인 모듈 추가", "retriever 모듈 생성",
  "hybrid retriever module", "pipeline module 만들어", "새 모듈 등록해",
  or directly references the project name `hybrid_retriever_modular` together with
  a module / node creation intent.

  Do NOT trigger for unrelated RAG ingestion, document upload, or generic Python file creation.
---

# Create Pipeline Module Skill

This skill scaffolds a new node module for the **hybrid_retriever_modular** project
(at `sandbox/myprojects/chain_react_ADK/hybrid_retriever_modular` inside a checkout of
`jw-sandbox`) and verifies it shows up in the runtime registry that powers the
Streamlit pipeline builder.

## When to use

Use this skill **whenever** the user wants to add or register a new pipeline node
(검색/결합/후처리/커스텀) in the hybrid_retriever_modular project. The deliverable
is a new file under `retriever_engine/api/pipeline_runtime/modules/` plus a
verification that it auto-registered.

Do not use this skill for:
- General Python utilities outside the hybrid_retriever_modular tree.
- Editing existing modules (just edit the file directly with the standard tools).
- RAG ingestion / document upload tasks (see `personal-rag` plugin).

## Inputs to gather (ask the user only what you cannot infer)

Required:
1. **Module short name** — used as filename and as the suffix of `type`. Lowercase snake_case.
   Example: `score_filter`, `dedup_by_doc`, `mmr_rerank`.
2. **Category** — one of `retrieval` / `fusion` / `postprocess` / `custom`.
   - `retrieval`: takes `query` + `dataset_ids` from input, outputs `<name>_results`.
   - `fusion`: takes `keyword_results` + `vector_results`, outputs `results`. Only one per pipeline.
   - `postprocess`: takes `results`, outputs `results`. Auto-chains to previous stage.
   - `custom`: same chain rule as postprocess; just a different palette section.
3. **What it does** — one sentence, used in `description` and palette tooltip.

Strongly recommended (infer from the description if user does not specify):
4. **Inputs** — list of `(name, type, description, required, default)`.
5. **Outputs** — list of `(name, type, description)`.
6. **Params** — list of tunable static parameters with type/default/min/max/options.
7. **Run body** — actual logic. If the user only describes intent, write a minimal
   correct implementation; do not leave `pass` / `TODO`.

Do NOT ask for: file path, registration step, or UI wiring. Those are automatic.

## Locating the project

The project lives somewhere under a checkout of the `jw-sandbox` repository. Locate it
once per session:

```bash
PROJECT_DIR=$(find "$HOME" -type d -path "*hybrid_retriever_modular" \
  -not -path "*/.venv/*" -not -path "*/node_modules/*" 2>/dev/null | head -1)
echo "$PROJECT_DIR"
```

If empty, ask the user where they have `hybrid_retriever_modular` checked out.

The relative paths inside the project are fixed:
- Modules folder: `retriever_engine/api/pipeline_runtime/modules/`
- Registry: `retriever_engine/api/pipeline_runtime/registry.py`
- Helper: `retriever_engine/api/pipeline_runtime/base_module.py`
- Venv python: `retriever_engine/.venv/bin/python` (use this for verification)

## Step-by-step flow

### 1) Confirm the spec with the user (one short message)

Echo back the gathered spec as a short bullet list and ask for confirmation
**only if the user gave you a vague intent**. If the user already gave a concrete spec,
skip the confirmation and proceed.

### 2) Generate the module file

Call the scaffold script in this skill:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/create-pipeline-module/scripts/scaffold_module.py" \
  --project-dir "$PROJECT_DIR" \
  --name "<module_short_name>" \
  --type "<category>.<module_short_name>" \
  --label "<Human Label>" \
  --description "<one sentence>" \
  --category "<retrieval|fusion|postprocess|custom>" \
  --inputs '<JSON list>' \
  --outputs '<JSON list>' \
  --params '<JSON list>' \
  --run-body-file /tmp/run_body.py \
  [--force]
```

JSON shapes (see `references/spec_reference.md` for full field list):

```json
// inputs
[{"name": "results", "type": "list[dict]", "description": "이전 단계 결과", "required": true, "default": null}]

// outputs
[{"name": "results", "type": "list[dict]", "description": "필터링된 결과"}]

// params
[{"name": "threshold", "type": "float", "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
  "description": "유사도 컷오프"},
 {"name": "mode", "type": "str", "default": "strict", "options": ["strict", "loose"]}]
```

`--run-body-file` should contain ONLY the body of the `run()` function (indented at
the function-body level), not the `async def` line. The script wraps it.

The script refuses to overwrite an existing file unless `--force` is passed.

### 3) Verify registration

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/create-pipeline-module/scripts/verify_registration.py" \
  --project-dir "$PROJECT_DIR" \
  --type "<category>.<module_short_name>"
```

This loads the engine's registry inside the project's venv (no FastAPI server needed) and
prints the normalized SPEC plus the inputs/outputs contract. Treat any non-zero exit
code or missing-type message as a failure and inspect the file you just wrote.

### 4) Report to the user

Output a compact summary:
- File written: `<absolute path>`
- Type: `<category>.<name>`, Category: `<category>`, Primary output: `<key>`
- Inputs / Outputs / Params bullet list (as the verify script printed them)
- One-liner: "Restart the FastAPI server to expose this in the running UI; the file
  is already in the auto-discovery path."

Do NOT restart the user's running server unless they ask. Do not push or commit.

## Category templates (run-body starting points)

If the user did not give explicit logic, use one of these as the seed and adapt it.

### retrieval
```python
del runtime_inputs
query = node_inputs["query"]
dataset_ids = node_inputs["dataset_ids"]
top_k = int(node_inputs.get("top_k", params.get("top_k", 20)))
results = []
for dataset_id in dataset_ids:
    results.extend(await retriever.<your_search_method>(dataset_id, query, top_k))
return {"<your_name>_results": results}
```

### fusion
```python
del runtime_inputs
kw = node_inputs.get("keyword_results", [])
vc = node_inputs.get("vector_results", [])
# combine kw + vc with the strategy you want
return {"results": <combined>}
```

### postprocess / custom
```python
del retriever, runtime_inputs
results = node_inputs.get("results", [])
threshold = float(params.get("threshold", 0.0))
return {"results": [r for r in results if float(r.get("similarity", 0.0)) >= threshold]}
```

## Constraints / gotchas

- Custom and postprocess modules MUST take `In("results")` and emit `Out("results")`
  for the UI's auto-chain to wire them up. Other input keys require manual edge wiring
  in the saved pipeline definition (out of scope for this skill).
- Module `type` should be `"<category>.<short_name>"`. The UI groups by `category`.
- Only one `fusion` node is allowed per pipeline; if user asks for a fusion variant,
  remind them they will need to remove the existing one in the UI.
- Default values declared in `params` are pre-filled into the UI editor. Always set
  sensible defaults so the module is usable without configuration.
- Never write to anything outside the `modules/` folder. Do not edit `registry.py`,
  `pipeline_builder.py`, or any other file — this skill exists precisely because that
  is no longer required.

## Files in this skill

| Path | Purpose |
|------|---------|
| `scripts/scaffold_module.py` | Generates the `<name>.py` file from a JSON spec. |
| `scripts/verify_registration.py` | Loads the project's registry and prints the normalized SPEC for a given type. |
| `references/spec_reference.md` | Full field list for the SPEC schema (mirrors `modules/README.md` in the project). |
