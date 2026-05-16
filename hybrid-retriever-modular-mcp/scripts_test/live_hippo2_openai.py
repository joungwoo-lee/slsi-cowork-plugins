"""Live Hippo2 smoke test using the repo's .env.

Uses the existing embedding OpenAI key for both embeddings and LLM calls when
``LLM_*`` is unset. Prints only sanitized config metadata, never secrets.

Run: py -3.12 scripts_test/live_hippo2_openai.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.config import load_config

LIVE_REPO = Path(r"C:/Users/joung/slsi-cowork-plugins/hybrid-retriever-modular-mcp")


def _read_response(proc: subprocess.Popen[str], msg_id: int) -> dict:
    while True:
        line = proc.stdout.readline()
        if not line:
            err = proc.stderr.read()
            raise RuntimeError(f"server exited before response {msg_id}: {err[:500]}")
        msg = json.loads(line)
        if msg.get("id") == msg_id:
            return msg


def main() -> int:
    cfg = load_config(LIVE_REPO / ".env")
    if not cfg.embedding or not cfg.embedding.is_configured:
        raise RuntimeError("embedding config missing in .env")
    if not cfg.llm or not cfg.llm.is_configured:
        raise RuntimeError("llm config missing after fallback resolution")

    print({
        "embedding": {
            "host": urlparse(cfg.embedding.api_url).netloc,
            "model": cfg.embedding.model,
            "dim": cfg.embedding.dim,
            "has_key": bool(cfg.embedding.api_key),
        },
        "llm": {
            "host": urlparse(cfg.llm.api_url).netloc,
            "model": cfg.llm.model,
            "has_key": bool(cfg.llm.api_key),
        },
    })

    server_py = LIVE_REPO / "server.py"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        ["py", "-3.12", str(server_py)],
        cwd=str(LIVE_REPO),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    next_id = iter(range(1, 10000))

    def send(method: str, params: dict | None = None, *, is_notification: bool = False):
        msg = {"jsonrpc": "2.0", "method": method}
        if not is_notification:
            msg["id"] = next(next_id)
        if params is not None:
            msg["params"] = params
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        return None if is_notification else _read_response(proc, msg["id"])

    def call(name: str, args: dict | None = None) -> dict:
        resp = send("tools/call", {"name": name, "arguments": args or {}})
        result = resp.get("result") or {}
        content = result.get("content") or []
        text = content[0].get("text") if content else ""
        payload = json.loads(text) if text else None
        if result.get("isError"):
            raise RuntimeError(str(payload))
        return payload

    dataset_id = f"hippo2_live_{uuid.uuid4().hex[:8]}"
    marker = uuid.uuid4().hex
    tmp_doc = LIVE_REPO / f"_hippo2_live_{marker}.txt"
    tmp_doc.write_text(
        (
            "Samsung Electronics is headquartered in Seoul.\n"
            "Seoul is in South Korea.\n"
            f"Unique marker: {marker}.\n"
        ),
        encoding="utf-8",
    )

    try:
        init = send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "hippo2-live", "version": "1.0"},
            },
        )
        assert init["result"]["protocolVersion"]
        send("notifications/initialized", {}, is_notification=True)

        up = call(
            "upload_document",
            {
                "dataset_id": dataset_id,
                "file_path": str(tmp_doc),
                "skip_embedding": False,
                "auto_hippo2": True,
                "use_hierarchical": "false",
            },
        )
        doc_id = up["response"]["document_id"]
        hippo = up.get("hippo2") or {}
        assert hippo.get("chunks_processed", 0) >= 1, hippo
        assert hippo.get("triples_written", 0) >= 1, hippo
        print({"upload_document": up["response"], "hippo2": hippo})

        gq = call(
            "graph_query",
            {
                "cypher": "MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk) WHERE d.id = $did RETURN COUNT(c) AS chunks",
                "params": {"did": doc_id},
                "limit": 5,
            },
        )
        assert gq["rows"][0]["chunks"] >= 1, gq
        print({"graph_query": gq["rows"]})

        hs = call(
            "hippo2_search",
            {
                "query": "What city is Samsung Electronics headquartered in?",
                "dataset_ids": [dataset_id],
                "top_n": 3,
            },
        )
        assert hs.get("chunks"), hs
        top = hs["chunks"][0]
        assert top["chunk_id"].startswith(doc_id), top
        print({"hippo2_top_result": top, "result_count": len(hs["chunks"])})
        return 0
    finally:
        try:
            call("delete_dataset", {"dataset_id": dataset_id})
        except Exception:
            pass
        try:
            tmp_doc.unlink(missing_ok=True)
        except Exception:
            pass
        proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
