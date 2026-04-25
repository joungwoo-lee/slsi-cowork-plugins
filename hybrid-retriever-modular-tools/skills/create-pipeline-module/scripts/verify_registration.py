#!/usr/bin/env python3
"""Verify that a freshly scaffolded module is auto-discovered by the registry.

Loads the project's runtime registry inside its own venv (so the runtime's
dependencies — pydantic, loguru, etc. — are available) and prints the normalized
SPEC for the requested node type.

Exit codes:
    0 — type found, contract printed
    1 — venv python not found
    2 — registry import failed
    3 — type not registered
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-dir", required=True)
    p.add_argument("--type", required=True, help="Full node type to verify, e.g. custom.score_filter")
    return p.parse_args()


INSPECTOR = r"""
import contextlib
import io
import json
import sys

# 프로젝트 루트의 config.py 등이 import 시 stdout 으로 banner 를 찍는 경우가 있어,
# JSON 출력을 오염시키지 않도록 import 동안에는 stdout 을 stderr 로 우회한다.
sys.path.insert(0, "retriever_engine")
_stash = io.StringIO()
with contextlib.redirect_stdout(_stash):
    try:
        from api.pipeline_runtime.registry import list_pipeline_nodes
    except Exception as exc:
        sys.stderr.write(_stash.getvalue())
        print("REGISTRY_IMPORT_ERROR:", repr(exc), file=sys.stderr)
        sys.exit(2)
sys.stderr.write(_stash.getvalue())

target = sys.argv[1]
nodes = list_pipeline_nodes()
match = next((n for n in nodes if n["type"] == target), None)
if match is None:
    print(json.dumps({
        "found": False,
        "target": target,
        "registered_types": sorted(n["type"] for n in nodes),
    }, ensure_ascii=False))
    sys.exit(3)

print(json.dumps({"found": True, "spec": match}, ensure_ascii=False, indent=2))
"""


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    venv_python = project_dir / "retriever_engine" / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        print(f"[verify] venv python not found at {venv_python}", file=sys.stderr)
        print("[verify] hint: run the project's setup once so the venv exists.", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [str(venv_python), "-c", INSPECTOR, args.type],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
    )
    if result.stderr:
        # Surface stderr unconditionally so the caller can see config-loaded banners etc.
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode == 2:
        sys.exit(2)
    if result.returncode == 3:
        try:
            payload = json.loads(result.stdout.strip())
            print(f"[verify] type {payload['target']!r} NOT found in registry.")
            print("[verify] currently registered types:")
            for t in payload["registered_types"]:
                print(f"  - {t}")
        except Exception:
            print(result.stdout)
        sys.exit(3)

    payload = json.loads(result.stdout)
    spec = payload["spec"]
    print(f"[verify] ✓ {spec['type']} registered")
    print(f"  label         : {spec['label']}")
    print(f"  category      : {spec['category']}")
    print(f"  description   : {spec['description']}")
    print(f"  primary_output: {spec.get('primary_output')}")
    _print_io("inputs", spec.get("inputs", []))
    _print_io("outputs", spec.get("outputs", []))
    _print_params(spec.get("params", []))


def _print_io(label: str, items: list) -> None:
    print(f"  {label}:")
    if not items:
        print("    (none)")
        return
    for it in items:
        flags = []
        if "required" in it and not it.get("required", True):
            flags.append("optional")
        if it.get("default") is not None:
            flags.append(f"default={it['default']!r}")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        desc = f" — {it['description']}" if it.get("description") else ""
        print(f"    - {it['name']} : {it.get('type', 'any')}{flag_str}{desc}")


def _print_params(items: list) -> None:
    print("  params:")
    if not items:
        print("    (none)")
        return
    for p in items:
        bits = [f"{p['name']}: {p.get('type', 'str')}"]
        if p.get("default") is not None:
            bits.append(f"default={p['default']!r}")
        if p.get("min") is not None or p.get("max") is not None:
            bits.append(f"range=[{p.get('min')}, {p.get('max')}]")
        if p.get("options"):
            bits.append(f"options={p['options']}")
        desc = f" — {p['description']}" if p.get("description") else ""
        print(f"    - {' '.join(bits)}{desc}")


if __name__ == "__main__":
    main()
