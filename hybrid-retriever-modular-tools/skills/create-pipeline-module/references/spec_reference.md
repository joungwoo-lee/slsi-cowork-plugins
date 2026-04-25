# Pipeline Module SPEC Reference

This is a condensed reference that mirrors `retriever_engine/api/pipeline_runtime/modules/README.md`
inside the `hybrid_retriever_modular` project. Use it when you need the schema in front
of you while authoring a new module.

## Minimum viable module

```python
from typing import Any
from ..base_module import In, Out, Param, make_spec


async def run(retriever, node_inputs, params, runtime_inputs) -> dict[str, Any]:
    return {"results": ...}


SPEC = make_spec(
    type="custom.my_module",     # global unique
    label="My Module",
    description="...",
    category="custom",            # retrieval | fusion | postprocess | custom
    inputs=[In("results", "list[dict]", "이전 단계 결과")],
    outputs=[Out("results", "list[dict]", "변환된 결과")],
    params=[Param("threshold", "float", default=0.5, min=0.0, max=1.0, step=0.05)],
    runner=run,
)
```

## Field reference

### `In(name, type, description, *, required=True, default=None)`

| field         | meaning |
|---------------|---------|
| `name`        | edge target key. Other nodes connect their output to this name. |
| `type`        | string label like `"str"`, `"int"`, `"list[dict]"`. Documentation only. |
| `description` | shown next to the input in the UI contract panel. |
| `required`    | when `False`, the UI tags the input "optional". |
| `default`     | placeholder default if no edge supplies the value. |

### `Out(name, type, description)`

| field         | meaning |
|---------------|---------|
| `name`        | edge source key. Downstream nodes pick this when wiring. |
| `type`        | string label, documentation only. |
| `description` | shown next to the output in the UI contract panel. |

### `Param(name, type, *, label=None, default=None, description="", min=None, max=None, step=None, options=None)`

| field         | UI effect |
|---------------|-----------|
| `name`        | persisted key in the saved pipeline definition. |
| `type`        | drives widget choice (see table below). |
| `label`       | overrides the field label. Defaults to `name`. |
| `default`     | initial value pre-filled into the widget. |
| `description` | shown as widget help text. |
| `min` / `max` | numeric range; for floats inside `[0,1]` triggers slider. |
| `step`        | step size for number inputs / sliders. |
| `options`     | turns string params into a `selectbox`. |

### `category`

| category      | UI section       | Auto-wiring rules |
|---------------|------------------|-------------------|
| `retrieval`   | "검색 모듈"      | input → (`query`, `dataset_ids`, `top_k`); output feeds fusion or chain |
| `fusion`      | "결합 모듈"      | takes `keyword_results` + `vector_results`; max one per pipeline |
| `postprocess` | "후처리 모듈"    | takes `results`, returns `results`; auto-chained |
| `custom`      | "커스텀 모듈"    | same chain rule as `postprocess` |

### Param type → widget

| `type`      | widget                                     |
|-------------|--------------------------------------------|
| `int`       | `st.number_input` (min/max/step honored)   |
| `float`     | `st.slider` if `0 ≤ min,max ≤ 1`, else `st.number_input` |
| `str`       | `st.selectbox` if `options`, else `st.text_input` |
| `bool`      | `st.checkbox`                              |
| `list[str]` | comma-separated `st.text_input`            |
| (other)     | `st.text_input` (string fallback)          |

## Chain convention (custom / postprocess)

For the UI's `_serialize_definition` to auto-wire your module:

```
prev_stage.results  ──►  this_module.results  ──►  next_stage.results
```

Use `In("results", "list[dict]")` and `Out("results", "list[dict]")`. Anything more
exotic (e.g. needing `query` from input) requires editing the saved pipeline definition
JSON or extending `pipeline_builder.py`. Out of scope for this skill.

## Where it ends up

After scaffolding:

```
<project>/retriever_engine/api/pipeline_runtime/modules/<name>.py
```

`registry._discover_modules()` scans this folder on import, so a server restart is
the only step needed to expose the module to:

- `GET /api/v1/pipelines/nodes` (the JSON catalog)
- The Streamlit pipeline builder palette and contract panel
