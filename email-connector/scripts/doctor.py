"""Verify the email-connector install. Prints a JSON report; exits 0 only if all checks pass.

Used by SETUP.md STEP 8. Each check produces:
    {"name": str, "ok": bool, "detail": str}
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import ssl
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEPS = [
    ("pypff", "libpff-python"),
    ("markdownify", "markdownify"),
    ("striprtf.striprtf", "striprtf"),
    ("fitz", "pymupdf"),
    ("docx", "python-docx"),
    ("openpyxl", "openpyxl"),
    ("pptx", "python-pptx"),
    ("qdrant_client", "qdrant-client"),
    ("requests", "requests"),
    ("dotenv", "python-dotenv"),
]


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def check_python_version() -> dict:
    ok = sys.version_info[:2] == (3, 9)
    return _check("python_3.9", ok, f"running {sys.version.split()[0]} at {sys.executable}")


def check_python_bits() -> dict:
    bits = struct.calcsize("P") * 8
    return _check("python_64bit", bits == 64, f"{bits}-bit interpreter")


def check_platform() -> dict:
    plat = sys.platform
    ok = plat.startswith("win")
    return _check("platform_windows", ok, f"sys.platform={plat}")


def check_dependency(import_name: str, pip_name: str) -> dict:
    try:
        mod = importlib.import_module(import_name)
        version = getattr(mod, "__version__", "unknown")
        return _check(f"dep:{pip_name}", True, f"imported {import_name} ({version})")
    except Exception as exc:  # noqa: BLE001
        return _check(f"dep:{pip_name}", False, f"import failed: {exc}")


def check_env_file(env_path: Path) -> dict:
    if not env_path.exists():
        return _check("env_file", False, f"file not found: {env_path}")
    return _check("env_file", True, f"found: {env_path}")


def check_config(cfg) -> tuple[dict, bool]:
    """Validate that required .env values are populated. Returns (check, ok)."""
    missing: list[str] = []
    if not cfg.embedding.api_url:
        missing.append("EMBEDDING_API_URL")
    if not cfg.embedding.api_key:
        missing.append("EMBEDDING_API_KEY")
    if not cfg.embedding.model:
        missing.append("EMBEDDING_MODEL")
    if cfg.embedding.dim <= 0:
        missing.append("EMBEDDING_DIM")
    if missing:
        return _check("config", False, f"missing required .env values: {missing}"), False
    return _check(
        "config",
        True,
        f"valid (model={cfg.embedding.model}, dim={cfg.embedding.dim}, "
        f"x-dep-ticket={'set' if cfg.embedding.x_dep_ticket else 'empty'})",
    ), True


def check_pst_path(cfg) -> dict:
    if not cfg.pst_path:
        return _check("pst_path", False, "PST_PATH is empty in .env")
    p = Path(cfg.pst_path)
    if not p.exists():
        return _check("pst_path", False, f"file not found: {cfg.pst_path}")
    if not p.is_file():
        return _check("pst_path", False, f"not a regular file: {cfg.pst_path}")
    return _check("pst_path", True, f"{cfg.pst_path} ({p.stat().st_size} bytes)")


def check_data_root(cfg) -> dict:
    try:
        cfg.ensure_dirs()
        probe = cfg.data_root / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return _check("data_root", True, f"writable: {cfg.data_root}")
    except Exception as exc:  # noqa: BLE001
        return _check("data_root", False, f"cannot prepare data_root: {exc}")


def check_embedding_api(cfg) -> dict:
    """Send a tiny POST mirroring the retriever_engine header set."""
    emb = cfg.embedding
    headers = {"Content-Type": "application/json"}
    if emb.api_key:
        headers["Authorization"] = f"Bearer {emb.api_key}"
    if emb.x_dep_ticket:
        headers["x-dep-ticket"] = emb.x_dep_ticket
    if emb.x_system_name:
        headers["x-system-name"] = emb.x_system_name

    payload = json.dumps({"model": emb.model, "input": ["ping"]}).encode("utf-8")
    req = urllib.request.Request(emb.api_url, data=payload, headers=headers, method="POST")

    if emb.verify_ssl:
        ssl_ctx: ssl.SSLContext | None = ssl.create_default_context()
    else:
        ssl_ctx = ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(req, timeout=emb.timeout_sec, context=ssl_ctx) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return _check("embedding_api", False, f"HTTP {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        return _check("embedding_api", False, f"connection failed: {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        return _check("embedding_api", False, f"request error: {exc}")

    items = body.get("data") or body.get("embeddings", [])
    if not items:
        return _check("embedding_api", False, f"unexpected response shape: keys={list(body)[:5]}")
    first = items[0]
    vec = first.get("embedding") if isinstance(first, dict) else first
    if vec is None:
        return _check("embedding_api", False, f"no embedding in first item: {first}")
    if len(vec) != emb.dim:
        return _check(
            "embedding_api",
            False,
            f"dim mismatch: api returned {len(vec)}, .env says {emb.dim}",
        )
    suffix = " (ssl verify ON)" if emb.verify_ssl else " (ssl verify OFF)"
    return _check("embedding_api", True, f"reachable, dim={len(vec)} matches .env{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose email-connector install.")
    parser.add_argument("--env", default=None, help="Path to .env (default: <skill_root>/.env)")
    parser.add_argument("--skip-api", action="store_true", help="Skip embedding API ping")
    parser.add_argument("--skip-pst", action="store_true", help="Skip PST_PATH existence check")
    args = parser.parse_args()

    from scripts.config import DEFAULT_ENV_PATH, load_config  # type: ignore

    env_path = Path(args.env) if args.env else DEFAULT_ENV_PATH
    results: list[dict] = []

    results.append(check_platform())
    results.append(check_python_version())
    results.append(check_python_bits())
    for import_name, pip_name in DEPS:
        results.append(check_dependency(import_name, pip_name))

    results.append(check_env_file(env_path))
    cfg = load_config(env_path) if env_path.exists() else None

    if cfg is not None:
        cfg_check, cfg_ok = check_config(cfg)
        results.append(cfg_check)
        if not args.skip_pst:
            results.append(check_pst_path(cfg))
        if cfg_ok:
            results.append(check_data_root(cfg))
            if not args.skip_api:
                results.append(check_embedding_api(cfg))

    all_ok = all(r["ok"] for r in results)
    print(json.dumps({"all_ok": all_ok, "checks": results}, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
