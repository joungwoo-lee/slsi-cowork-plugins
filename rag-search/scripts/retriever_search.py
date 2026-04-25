#!/usr/bin/env python3
import argparse
import json
import os
import sys
from typing import Any, Dict, List

import requests

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def _flatten_to_dict_list(obj: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []

    def _walk(x: Any):
        if x is None:
            return
        if isinstance(x, dict):
            result.append(x)
        elif isinstance(x, (list, tuple)):
            for v in x:
                _walk(v)
        else:
            result.append({"content": str(x)})

    _walk(obj)
    return result


def _f(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def run() -> int:
    parser = argparse.ArgumentParser(description="Query Hybrid Retriever retrieval API")
    parser.add_argument("--base-url", default=os.getenv("RAG_BASE_URL", "http://ssai-dev.samsungds.net:9380"))
    parser.add_argument("--api-key", default=os.getenv("RAG_API_KEY", "ragflow-key"))
    parser.add_argument("--dataset-ids", default=os.getenv("RAG_DATASET_IDS", "knowledge-base01"))
    parser.add_argument("--query", required=True)
    parser.add_argument("--pipeline-name", default=os.getenv("RAG_PIPELINE_NAME", ""))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--vector-similarity-weight", type=float, default=0.0)
    parser.add_argument("--similarity-threshold", type=float, default=0.0)
    parser.add_argument("--keyword", action="store_true", default=True)
    parser.add_argument("--timeout", type=int, default=int(os.getenv("RAG_TIMEOUT", "60")))
    args = parser.parse_args()

    dataset_ids = [x.strip() for x in args.dataset_ids.split(",") if x.strip()]
    if not dataset_ids:
        print(json.dumps({"ok": False, "error": "dataset_ids is required"}, ensure_ascii=False))
        return 2

    base_url = args.base_url.rstrip("/")
    payload = {
        "question": args.query.strip(),
        "query": args.query.strip(),
        "dataset_ids": dataset_ids,
        "keyword": True,
        "pipeline_name": args.pipeline_name.strip() or None,
        "vector_similarity_weight": args.vector_similarity_weight,
        "similarity_threshold": args.similarity_threshold,
        "top_k": max(1, args.top_k),
        "page": max(1, args.page),
        "page_size": max(1, args.page_size),
        "rerank_id": None,
        "metadata_condition": None,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {args.api_key}",
    }

    try:
        resp = requests.post(
            f"{base_url}/api/v1/retrieval",
            headers=headers,
            json=payload,
            timeout=args.timeout,
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"request_failed: {e}"}, ensure_ascii=False))
        return 1

    if resp.status_code != 200:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": resp.status_code,
                    "error": "retrieval_api_error",
                    "raw_text": resp.text,
                },
                ensure_ascii=False,
            )
        )
        return 1

    try:
        data = resp.json()
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "invalid_json", "raw_text": resp.text},
                ensure_ascii=False,
            )
        )
        return 1

    items_any = (data.get("data") or {}).get("items") or (data.get("data") or {}).get("chunks") or data.get("data") or []
    items = _flatten_to_dict_list(items_any)
    top_n = max(1, min(50, args.top_n))
    selected = items[:top_n]

    contexts, citations = [], []
    for c in selected:
        doc_name = c.get("document_name") or c.get("name")
        pos = c.get("position")
        if pos is None and isinstance(c.get("positions"), list) and c["positions"]:
            pos = c["positions"][0]

        contexts.append(
            {
                "text": c.get("content", ""),
                "source": {
                    "dataset_id": c.get("dataset_id"),
                    "document_id": c.get("document_id"),
                    "document_name": doc_name,
                    "position": pos,
                    "chunk_id": c.get("id"),
                    "similarity": _f(c.get("similarity")),
                    "vector_similarity": _f(c.get("vector_similarity")),
                    "term_similarity": _f(c.get("term_similarity")),
                },
            }
        )
        citations.append(
            {
                "document_name": doc_name,
                "position": pos,
                "score": _f(c.get("similarity")),
                "chunk_id": c.get("id"),
            }
        )

    print(
        json.dumps(
            {
                "ok": True,
                "query": args.query,
                "base_url": base_url,
                "dataset_ids": dataset_ids,
                "pipeline_name": args.pipeline_name.strip() or None,
                "count": len(contexts),
                "contexts": contexts,
                "citations": citations,
                "raw": data,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
