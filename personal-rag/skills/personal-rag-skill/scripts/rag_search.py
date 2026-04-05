#!/usr/bin/env python3
"""Personal RAG search — query LanceDB directly with the same embedding model."""

import argparse
import json
import os
import sys

LANCEDB_PATH = os.environ.get(
    "RAG_LANCEDB_PATH",
    os.path.expanduser("~/anythingllm-server/server/storage/lancedb"),
)
MODEL_NAME = os.environ.get("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def main():
    parser = argparse.ArgumentParser(description="Search personal RAG workspace")
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--workspace", "-w", default="my_rag", help="Workspace/table name")
    parser.add_argument("--top-n", "-n", type=int, default=5, help="Number of results")
    parser.add_argument("--threshold", "-t", type=float, default=0.0, help="Min similarity (0-1)")
    args = parser.parse_args()

    try:
        import lancedb
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        json.dump({"ok": False, "error": f"Missing dependency: {e}"}, sys.stdout)
        print()
        sys.exit(1)

    if not os.path.isdir(LANCEDB_PATH):
        json.dump({"ok": False, "error": f"LanceDB path not found: {LANCEDB_PATH}"}, sys.stdout)
        print()
        sys.exit(1)

    model = SentenceTransformer(MODEL_NAME)
    query_vec = model.encode(args.query).tolist()

    db = lancedb.connect(LANCEDB_PATH)
    tables = db.list_tables()
    if args.workspace not in tables:
        json.dump(
            {"ok": False, "error": f"Workspace '{args.workspace}' not found. Available: {tables}"},
            sys.stdout,
        )
        print()
        sys.exit(1)

    table = db.open_table(args.workspace)
    results = (
        table.search(query_vec)
        .distance_type("cosine")
        .limit(args.top_n)
        .to_arrow()
    )

    contexts = []
    for i in range(results.num_rows):
        dist = float(results.column("_distance")[i].as_py())
        score = 1.0 - dist  # cosine distance -> similarity
        if score < args.threshold:
            continue
        contexts.append({
            "text": results.column("text")[i].as_py(),
            "source": {
                "title": results.column("title")[i].as_py(),
                "url": results.column("url")[i].as_py(),
                "docSource": results.column("docSource")[i].as_py(),
                "similarity": round(score, 4),
            },
        })

    output = {
        "ok": True,
        "query": args.query,
        "workspace": args.workspace,
        "count": len(contexts),
        "contexts": contexts,
        "citations": [
            {"title": c["source"]["title"], "score": c["source"]["similarity"]}
            for c in contexts
        ],
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
