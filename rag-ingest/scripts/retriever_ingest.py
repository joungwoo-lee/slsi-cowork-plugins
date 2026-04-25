#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def _to_opt_bool(v: str) -> Optional[bool]:
    s = (v or "").strip().lower()
    if s in ("none", "null", ""):
        return None
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    raise ValueError(f"invalid bool option: {v}")


def run() -> int:
    parser = argparse.ArgumentParser(description="Upload+ingest one file to Hybrid Retriever")
    parser.add_argument("--base-url", default=os.getenv("RAG_BASE_URL", "http://ssai-dev.samsungds.net:9380"))
    parser.add_argument("--api-key", default=os.getenv("RAG_API_KEY", "ragflow-key"))
    parser.add_argument("--dataset-id", default=os.getenv("RAG_DATASET_IDS", "knowledge-base01"))
    parser.add_argument("--file-path", required=True)
    parser.add_argument("--pipeline-name", default=os.getenv("RAG_PIPELINE_NAME", ""))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("RAG_TIMEOUT", "60")))
    parser.add_argument("--use-hierarchical", default="none", help="true|false|none")
    parser.add_argument("--use-contextual", default="none", help="true|false|none")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    path = Path(args.file_path)
    if not path.exists() or not path.is_file():
        print(json.dumps({"ok": False, "error": f"file_not_found: {args.file_path}"}, ensure_ascii=False))
        return 2

    headers = {"Authorization": f"Bearer {args.api_key}"}

    data = {}
    uh = _to_opt_bool(args.use_hierarchical)
    uc = _to_opt_bool(args.use_contextual)
    if uh is not None:
        data["use_hierarchical"] = str(uh).lower()
    if uc is not None:
        data["use_contextual"] = str(uc).lower()
    if args.pipeline_name and args.pipeline_name.strip():
        data["pipeline_name"] = args.pipeline_name.strip()

    try:
        with path.open("rb") as f:
            files = {"file": (path.name, f)}
            up = requests.post(
                f"{base_url}/api/v1/datasets/{args.dataset_id}/documents",
                headers=headers,
                files=files,
                data=data,
                timeout=args.timeout,
            )
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"upload_request_failed: {e}"}, ensure_ascii=False))
        return 1

    if up.status_code != 200:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": up.status_code,
                    "error": "upload_failed",
                    "raw_text": up.text,
                },
                ensure_ascii=False,
            )
        )
        return 1

    try:
        upj = up.json()
        doc_id = upj["data"]["id"]
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"upload_response_parse_failed: {e}", "raw_text": up.text}, ensure_ascii=False))
        return 1

    payload = {"document_ids": [doc_id]}
    try:
        pr = requests.post(
            f"{base_url}/api/v1/datasets/{args.dataset_id}/chunks",
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=args.timeout,
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"parse_request_failed: {e}", "uploaded_doc_id": doc_id}, ensure_ascii=False))
        return 1

    if pr.status_code != 200:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": pr.status_code,
                    "error": "parse_failed",
                    "uploaded_doc_id": doc_id,
                    "raw_text": pr.text,
                },
                ensure_ascii=False,
            )
        )
        return 1

    try:
        prj = pr.json()
    except Exception:
        prj = {"raw_text": pr.text}

    print(
        json.dumps(
            {
                "ok": True,
                "base_url": base_url,
                "dataset_id": args.dataset_id,
                "file_path": str(path),
                "pipeline_name": args.pipeline_name.strip() or None,
                "uploaded_doc_id": doc_id,
                "parse_response": prj,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
