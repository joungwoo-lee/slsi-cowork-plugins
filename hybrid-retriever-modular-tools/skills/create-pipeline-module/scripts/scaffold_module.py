#!/usr/bin/env python3
"""Generate a new pipeline module file for hybrid_retriever_modular.

Used by the `create-pipeline-module` skill. The script renders a
`<name>.py` file under `<project-dir>/retriever_engine/api/pipeline_runtime/modules/`
using the new SPEC helper (`make_spec` / `In` / `Out` / `Param`).

It is intentionally pure stdlib so it runs in any python3 the harness picks up.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

VALID_CATEGORIES = {"retrieval", "fusion", "postprocess", "custom"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-dir", required=True,
                   help="Absolute path to the hybrid_retriever_modular project directory")
    p.add_argument("--name", required=True,
                   help="Module short name (snake_case). Used as filename and type suffix.")
    p.add_argument("--type", required=True,
                   help='Full node type, e.g. "custom.score_filter"')
    p.add_argument("--label", required=True, help="Human-facing label shown in the UI palette")
    p.add_argument("--description", required=True, help="One-sentence description")
    p.add_argument("--category", required=True, choices=sorted(VALID_CATEGORIES))
    p.add_argument("--inputs", required=True,
                   help='JSON list of input dicts: [{"name","type","description","required","default"}]')
    p.add_argument("--outputs", required=True,
                   help='JSON list of output dicts: [{"name","type","description"}]')
    p.add_argument("--params", default="[]",
                   help='JSON list of param dicts: [{"name","type","default","min","max","step","options","description","label"}]')
    p.add_argument("--run-body-file",
                   help="Path to a file containing the body of the run() function (no def line). "
                        "If omitted, a category-appropriate placeholder is used.")
    p.add_argument("--primary-output", default=None,
                   help="Override primary output key. Defaults to outputs[0].name.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite an existing file with the same name.")
    return p.parse_args()


def fail(msg: str, code: int = 2) -> None:
    print(f"[scaffold_module] error: {msg}", file=sys.stderr)
    sys.exit(code)


def validate_name(name: str) -> None:
    if not NAME_RE.match(name):
        fail(f"--name must be lowercase snake_case (got: {name!r})")


def validate_type(type_str: str, category: str, name: str) -> None:
    if "." not in type_str:
        fail(f"--type must look like 'category.name' (got: {type_str!r})")
    head, tail = type_str.split(".", 1)
    if category != "fusion" and head not in {"retrieval", "postprocess", "custom"} and category not in {"retrieval"}:
        # retrieval modules conventionally use "retrieval.<name>"
        # custom / postprocess can also live under their category prefix
        # We don't hard-fail on type prefix mismatch — it's conventional, not enforced by registry.
        pass
    if tail != name:
        fail(f"--type suffix ({tail!r}) must match --name ({name!r})")


def parse_json_list(raw: str, label: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"--{label} is not valid JSON: {exc}")
    if not isinstance(value, list):
        fail(f"--{label} must be a JSON list")
    for i, item in enumerate(value):
        if not isinstance(item, dict) or "name" not in item:
            fail(f"--{label}[{i}] must be a dict with at least a 'name' key (got: {item!r})")
    return value


def py_repr(value: Any) -> str:
    """Render a Python literal we can paste into source."""
    return repr(value)


def render_in(item: dict[str, Any]) -> str:
    name = item["name"]
    type_ = item.get("type", "any")
    desc = item.get("description", "")
    parts = [py_repr(name), py_repr(type_), py_repr(desc)]
    if not item.get("required", True):
        parts.append("required=False")
    if item.get("default") is not None:
        parts.append(f"default={py_repr(item['default'])}")
    return f"        In({', '.join(parts)}),"


def render_out(item: dict[str, Any]) -> str:
    return (
        f"        Out({py_repr(item['name'])}, "
        f"{py_repr(item.get('type', 'any'))}, "
        f"{py_repr(item.get('description', ''))}),"
    )


def render_param(item: dict[str, Any]) -> str:
    name = item["name"]
    p_type = item.get("type", "str")
    parts = [py_repr(name), py_repr(p_type)]
    for key in ("label", "default", "description"):
        if item.get(key) is not None:
            parts.append(f"{key}={py_repr(item[key])}")
    for key in ("min", "max", "step"):
        if item.get(key) is not None:
            parts.append(f"{key}={py_repr(item[key])}")
    if item.get("options") is not None:
        parts.append(f"options={py_repr(item['options'])}")
    return f"        Param({', '.join(parts)}),"


PLACEHOLDER_BODIES = {
    "retrieval": '''del runtime_inputs
query = node_inputs["query"]
dataset_ids = node_inputs["dataset_ids"]
top_k = int(node_inputs.get("top_k", params.get("top_k", 20)))
results: list[dict[str, Any]] = []
for dataset_id in dataset_ids:
    # TODO: replace with the actual retriever call
    results.extend(await retriever.keyword_search(dataset_id, query, top_k))
return {"REPLACE_WITH_PRIMARY_OUTPUT_KEY": results}
''',
    "fusion": '''del runtime_inputs
keyword_results = node_inputs.get("keyword_results", [])
vector_results = node_inputs.get("vector_results", [])
# TODO: implement combination strategy
combined = list({r.get("chunk_id"): r for r in keyword_results + vector_results}.values())
return {"results": combined}
''',
    "postprocess": '''del retriever, runtime_inputs
results = node_inputs.get("results", [])
# TODO: implement post-processing
return {"results": results}
''',
    "custom": '''del retriever, runtime_inputs
results = node_inputs.get("results", [])
# TODO: implement your transformation
return {"results": results}
''',
}


def load_run_body(path: str | None, category: str, primary_output: str | None) -> str:
    if path:
        body = Path(path).read_text(encoding="utf-8").rstrip() + "\n"
    else:
        body = PLACEHOLDER_BODIES[category]
        if primary_output:
            body = body.replace("REPLACE_WITH_PRIMARY_OUTPUT_KEY", primary_output)
    # Indent every non-empty line by 4 spaces (function body level)
    lines = []
    for line in body.splitlines():
        if line.strip() == "":
            lines.append("")
        else:
            lines.append("    " + line)
    return "\n".join(lines).rstrip() + "\n"


TEMPLATE = '''"""Internal module for the external `{type}` node.

Generated by the create-pipeline-module skill.

Drop a file in this folder and the engine's registry auto-discovers it on next
server start. Edit / extend freely — this scaffold is a starting point, not a
final form.
"""

from typing import Any

from ..base_module import In, Out, Param, make_spec


async def run(retriever, node_inputs: dict[str, Any], params: dict[str, Any], runtime_inputs: dict[str, Any]) -> dict[str, Any]:
{run_body}

SPEC = make_spec(
    type={type_repr},
    label={label_repr},
    description={description_repr},
    category={category_repr},
    inputs=[
{inputs_block}
    ],
    outputs=[
{outputs_block}
    ],
    params=[
{params_block}
    ],{primary_output_line}
    runner=run,
)
'''


def render(args: argparse.Namespace,
           inputs: list[dict[str, Any]],
           outputs: list[dict[str, Any]],
           params: list[dict[str, Any]]) -> str:
    primary_output = args.primary_output or (outputs[0]["name"] if outputs else None)
    inputs_block = "\n".join(render_in(i) for i in inputs) if inputs else "        # (no inputs)"
    outputs_block = "\n".join(render_out(o) for o in outputs) if outputs else "        # (no outputs)"
    params_block = "\n".join(render_param(p) for p in params) if params else "        # (no params)"
    primary_output_line = (
        f"\n    primary_output={py_repr(primary_output)}," if primary_output else ""
    )
    run_body = load_run_body(args.run_body_file, args.category, primary_output)

    return TEMPLATE.format(
        type=args.type,
        type_repr=py_repr(args.type),
        label_repr=py_repr(args.label),
        description_repr=py_repr(args.description),
        category_repr=py_repr(args.category),
        inputs_block=inputs_block,
        outputs_block=outputs_block,
        params_block=params_block,
        primary_output_line=primary_output_line,
        run_body=run_body,
    )


def resolve_target(project_dir: str, name: str) -> Path:
    project = Path(project_dir).expanduser().resolve()
    modules_dir = project / "retriever_engine" / "api" / "pipeline_runtime" / "modules"
    if not modules_dir.is_dir():
        fail(f"modules folder not found at {modules_dir}. "
             "Is --project-dir pointing at the hybrid_retriever_modular root?")
    return modules_dir / f"{name}.py"


def main() -> None:
    args = parse_args()
    validate_name(args.name)
    validate_type(args.type, args.category, args.name)

    inputs = parse_json_list(args.inputs, "inputs")
    outputs = parse_json_list(args.outputs, "outputs")
    params = parse_json_list(args.params, "params")

    target = resolve_target(args.project_dir, args.name)
    if target.exists() and not args.force:
        fail(f"file already exists: {target}\nUse --force to overwrite.", code=3)

    rendered = render(args, inputs, outputs, params)
    # Final compile sanity check before writing.
    try:
        compile(rendered, str(target), "exec")
    except SyntaxError as exc:
        fail(f"generated code has a SyntaxError: {exc}\n--- begin ---\n{rendered}--- end ---")

    target.write_text(rendered, encoding="utf-8")
    print(f"[scaffold_module] wrote {target}")
    print(f"[scaffold_module] type={args.type} category={args.category} "
          f"primary_output={args.primary_output or (outputs[0]['name'] if outputs else None)!r}")


if __name__ == "__main__":
    main()
