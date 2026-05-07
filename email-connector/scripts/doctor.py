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
    ("qdrant_client", "qdrant-client"),
    ("requests", "requests"),
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


def check_config(config_path: Path) -> tuple[dict, dict | None]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        emb = raw.get("embedding", {})
        missing = [f for f in ("endpoint", "api_key", "model", "dim") if not emb.get(f)]
        if missing:
            return _check("config", False, f"missing embedding fields: {missing}"), None
        if emb.get("api_key") == "REPLACE_ME":
            return _check("config", False, "api_key is still the placeholder REPLACE_ME"), None
        try:
            int(emb["dim"])
        except (TypeError, ValueError):
            return _check("config", False, f"embedding.dim is not an integer: {emb.get('dim')!r}"), None
        return _check("config", True, f"valid (model={emb['model']}, dim={emb['dim']})"), raw
    except FileNotFoundError:
        return _check("config", False, f"file not found: {config_path}"), None
    except json.JSONDecodeError as exc:
        return _check("config", False, f"invalid JSON: {exc}"), None


def check_data_root(config_path: Path) -> dict:
    try:
        from scripts.config import load_config  # type: ignore

        cfg = load_config(config_path)
        cfg.ensure_dirs()
        probe = cfg.data_root / ".doctor_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return _check("data_root", True, f"writable: {cfg.data_root}")
    except Exception as exc:  # noqa: BLE001
        return _check("data_root", False, f"cannot prepare data_root: {exc}")


def check_embedding_api(raw_config: dict) -> dict:
    emb = raw_config["embedding"]
    payload = json.dumps({"model": emb["model"], "input": ["ping"]}).encode("utf-8")
    req = urllib.request.Request(
        emb["endpoint"],
        data=payload,
        headers={
            "Authorization": f"Bearer {emb['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    # Honor verify_ssl from config (default false to handle corporate MITM).
    verify_ssl = bool(emb.get("verify_ssl", False))
    if verify_ssl:
        ssl_ctx: ssl.SSLContext | None = ssl.create_default_context()
    else:
        ssl_ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(
            req,
            timeout=int(emb.get("timeout_sec", 30)),
            context=ssl_ctx,
        ) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return _check("embedding_api", False, f"HTTP {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        return _check("embedding_api", False, f"connection failed: {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        return _check("embedding_api", False, f"request error: {exc}")

    try:
        vec = body["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError):
        return _check("embedding_api", False, f"unexpected response shape: keys={list(body)[:5]}")

    expected = int(emb["dim"])
    if len(vec) != expected:
        return _check(
            "embedding_api",
            False,
            f"dim mismatch: api returned {len(vec)}, config says {expected}",
        )
    suffix = " (ssl verify ON)" if verify_ssl else " (ssl verify OFF)"
    return _check("embedding_api", True, f"reachable, dim={len(vec)} matches config{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose email-connector install.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--skip-api", action="store_true", help="Skip embedding API ping")
    args = parser.parse_args()

    config_path = Path(args.config)
    results: list[dict] = []

    results.append(check_platform())
    results.append(check_python_version())
    results.append(check_python_bits())
    for import_name, pip_name in DEPS:
        results.append(check_dependency(import_name, pip_name))

    cfg_check, raw_cfg = check_config(config_path)
    results.append(cfg_check)
    if cfg_check["ok"]:
        results.append(check_data_root(config_path))
        if not args.skip_api and raw_cfg is not None:
            results.append(check_embedding_api(raw_cfg))

    all_ok = all(r["ok"] for r in results)
    print(json.dumps({"all_ok": all_ok, "checks": results}, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
