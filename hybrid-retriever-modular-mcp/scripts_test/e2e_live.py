"""Live-install E2E: drive the *installed* MCP server with a fresh dataset.

Targets ``C:/Users/joung/slsi-cowork-plugins/hybrid-retriever-modular-mcp/server.py``
so we exercise exactly the binary Claude Desktop / Code uses, with the live
``.env`` (real embedding API). Each run uses a unique dataset id so it never
collides with the user's real data.

Run:    py -3 scripts_test/e2e_live.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

LIVE_REPO = Path(r"C:/Users/joung/slsi-cowork-plugins/hybrid-retriever-modular-mcp")


def main() -> int:
    server_py = LIVE_REPO / "server.py"
    if not server_py.is_file():
        print(f"[fatal] live server.py not found at {server_py}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # No PYTHONPATH override: live install reads its own .env via server.py.

    print(f"[live] server={server_py}")
    proc = subprocess.Popen(
        [sys.executable, str(server_py)],
        cwd=str(LIVE_REPO),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    next_id = iter(range(1, 10_000))

    def send(method, params=None, *, is_notification=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if not is_notification:
            msg["id"] = next(next_id)
        if params is not None:
            msg["params"] = params
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        return None if is_notification else _read_response(proc, msg["id"])

    def call(name, args=None):
        resp = send("tools/call", {"name": name, "arguments": args or {}})
        result = resp.get("result")
        content = (result or {}).get("content") or []
        text = content[0].get("text") if content else ""
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = text
        return {"isError": bool((result or {}).get("isError")), "payload": payload}

    dataset_id = f"e2e_live_{uuid.uuid4().hex[:8]}"
    tmp_doc: Path | None = None
    try:
        # 1) initialize
        init = send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "live-e2e", "version": "1.0"},
            },
        )
        assert init["result"]["protocolVersion"], init
        send("notifications/initialized", {}, is_notification=True)
        print(f"[ok] initialize -> {init['result']['serverInfo']}")

        # 2) health BEFORE ingest
        h0 = call("health")
        assert not h0["isError"], h0
        print(f"[ok] health pre: counts={h0['payload']['counts']}, "
              f"embedding_configured={h0['payload']['embedding_configured']}")

        # 3) Create fresh dataset
        cd = call("create_dataset", {"name": dataset_id})
        assert not cd["isError"], cd
        print(f"[ok] create_dataset -> {cd['payload']['id']}")

        # 4) Write a brand-new document with content unique to this run
        marker = uuid.uuid4().hex
        tmp_doc = LIVE_REPO / f"_e2e_doc_{marker}.md"
        body = (
            f"# 모듈러 리트리버 라이브 E2E ({marker})\n\n"
            "이 문서는 푸시된 modular Haystack + Hypster 파이프라인이 "
            "실제 설치된 MCP 서버에서 동작하는지 검증하기 위한 인공 문서입니다.\n\n"
            "- Haystack 컴포넌트로 분해된 retrieval 파이프라인\n"
            "- Hypster로 정의된 indexing/retrieval 설정 공간\n"
            "- SQLite FTS5 키워드 백엔드 + Qdrant 벡터 백엔드 + Kuzu 그래프\n\n"
            f"unique marker: {marker}\n"
            "Modular RAG decomposes retrieval into reusable Haystack components, "
            "which Hypster then wires into a single configuration space.\n"
        )
        tmp_doc.write_text(body, encoding="utf-8")
        print(f"[step] wrote test doc {tmp_doc.name}, marker={marker}")

        # 5) Ingest WITH embedding (live OpenAI key present in .env)
        up = call(
            "upload_document",
            {
                "dataset_id": dataset_id,
                "file_path": str(tmp_doc),
                "use_hierarchical": "true",
                "skip_embedding": False,
            },
        )
        assert not up["isError"], up
        doc_resp = up["payload"]["response"]
        document_id = doc_resp["document_id"]
        assert doc_resp["chunks_count"] >= 1, doc_resp
        print(
            f"[ok] upload_document: doc={document_id} "
            f"chunks={doc_resp['chunks_count']} parents={doc_resp['parent_chunks_count']} "
            f"has_vector={doc_resp['has_vector']} hierarchical={doc_resp['is_hierarchical']}"
        )

        # 6) list_chunks confirms chunks present
        lc = call("list_chunks", {"dataset_id": dataset_id, "document_id": document_id, "limit": 50})
        assert not lc["isError"], lc
        assert lc["payload"], lc
        print(f"[ok] list_chunks: {len(lc['payload'])} chunks")

        # 7) Keyword-only search by Korean unique term
        s_kw = call(
            "search",
            {
                "query": "Hypster",
                "dataset_ids": [dataset_id],
                "top_n": 5,
                "vector_similarity_weight": 0.0,
                "fusion": "linear",
            },
        )
        assert not s_kw["isError"], s_kw
        assert s_kw["payload"]["total"] >= 1, s_kw["payload"]
        first = s_kw["payload"]["contexts"][0]
        assert first["source"]["chunk_id"].startswith(document_id), first
        print(
            f"[ok] search keyword: total={s_kw['payload']['total']} "
            f"top_chunk={first['source']['chunk_id']} score={first['source']['similarity']}"
        )

        # 8) Hybrid search (with vector — exercises live OpenAI embedding path)
        s_hy = call(
            "search",
            {
                "query": "Haystack components Hypster configuration",
                "dataset_ids": [dataset_id],
                "top_n": 5,
                "vector_similarity_weight": 0.6,
                "fusion": "linear",
                "parent_chunk_replace": True,
            },
        )
        assert not s_hy["isError"], s_hy
        assert s_hy["payload"]["total"] >= 1, s_hy["payload"]
        top = s_hy["payload"]["contexts"][0]
        sim = top["source"]
        assert sim["chunk_id"].startswith(document_id), sim
        print(
            f"[ok] search hybrid: total={s_hy['payload']['total']} "
            f"top_chunk={sim['chunk_id']} "
            f"term={sim['term_similarity']} vec={sim['vector_similarity']} "
            f"fused={sim['similarity']}"
        )

        # 9) RRF
        s_rrf = call(
            "search",
            {
                "query": "modular retriever",
                "dataset_ids": [dataset_id],
                "top_n": 5,
                "vector_similarity_weight": 0.5,
                "fusion": "rrf",
            },
        )
        assert not s_rrf["isError"], s_rrf
        assert s_rrf["payload"]["total"] >= 1, s_rrf["payload"]
        print(f"[ok] search rrf: total={s_rrf['payload']['total']} "
              f"top_score={s_rrf['payload']['contexts'][0]['source']['similarity']}")

        # 10) Unique-marker search (proves the *new* document is what we found)
        s_marker = call(
            "search",
            {"query": marker, "dataset_ids": [dataset_id], "top_n": 1, "vector_similarity_weight": 0.0},
        )
        assert not s_marker["isError"], s_marker
        assert s_marker["payload"]["total"] >= 1, s_marker
        marker_ctx = s_marker["payload"]["contexts"][0]
        assert marker in (marker_ctx["text"] or ""), marker_ctx
        print(f"[ok] marker search: found unique marker '{marker}' in returned text")

        # 10b) Profile registry surfaces in list_pipelines
        lp = call("list_pipelines")
        assert not lp["isError"], lp
        registered = [p["name"] for p in lp["payload"].get("profiles", [])]
        assert "default" in registered, registered
        assert "keyword_only" in registered, registered
        print(f"[ok] list_pipelines: profiles={registered}")

        # 10c) search via pipeline="keyword_only" -> vector forced off, RRF forced
        s_kw_profile = call(
            "search",
            {
                "query": "Hypster",
                "dataset_ids": [dataset_id],
                "top_n": 3,
                # Try to enable vectors -- profile must force them off.
                "vector_similarity_weight": 0.9,
                "fusion": "linear",
                "pipeline": "keyword_only",
            },
        )
        assert not s_kw_profile["isError"], s_kw_profile
        assert s_kw_profile["payload"]["total"] >= 1, s_kw_profile
        kw_src = s_kw_profile["payload"]["contexts"][0]["source"]
        assert kw_src["vector_similarity"] == 0.0, kw_src
        expected_rrf = 1.0 / (60 + 1)
        assert abs(kw_src["similarity"] - expected_rrf) < 1e-3, (kw_src, expected_rrf)
        print(
            f"[ok] search pipeline=keyword_only (live): vec_sim={kw_src['vector_similarity']} "
            f"(forced 0), term_sim={kw_src['term_similarity']}, "
            f"fused={kw_src['similarity']} (RRF rank-1 ~= {expected_rrf:.4f})"
        )

        # 10d) Same query via pipeline="default" -> hybrid path still uses vectors
        s_def_profile = call(
            "search",
            {
                "query": "Hypster",
                "dataset_ids": [dataset_id],
                "top_n": 3,
                "vector_similarity_weight": 0.6,
                "fusion": "linear",
                "pipeline": "default",
            },
        )
        assert not s_def_profile["isError"], s_def_profile
        def_src = s_def_profile["payload"]["contexts"][0]["source"]
        # The default profile keeps vector path on -- vec_sim must be > 0 here
        # since the live embedding API is configured.
        assert def_src["vector_similarity"] > 0.0, def_src
        print(
            f"[ok] search pipeline=default (live): vec_sim={def_src['vector_similarity']} "
            f"(active), term_sim={def_src['term_similarity']}, fused={def_src['similarity']}"
        )

        # 10e) Email profile (live OpenAI embedding path)
        import tempfile

        eml_marker = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="e2e_live_email_") as tmpdir:
            tmp_path = Path(tmpdir)
            eml = tmp_path / "live_alice.eml"
            eml.write_bytes(
                (
                    "From: Alice Lee <alice.live@example.com>\r\n"
                    "To: Bob Live <bob.live@example.com>\r\n"
                    "Subject: Live email pipeline check\r\n"
                    "Date: Wed, 14 May 2026 11:00:00 +0900\r\n"
                    f"Message-ID: <{eml_marker}@example.com>\r\n"
                    "MIME-Version: 1.0\r\n"
                    "Content-Type: text/plain; charset=utf-8\r\n"
                    "\r\n"
                    f"Live retriever modular pipeline marker {eml_marker}. "
                    "Haystack 기반 email profile이 동작합니다.\r\n"
                ).encode("utf-8")
            )
            up_eml = call(
                "upload_document",
                {
                    "dataset_id": dataset_id,
                    "file_path": str(eml),
                    "pipeline": "email",
                    "skip_embedding": False,
                },
            )
            assert not up_eml["isError"], up_eml
            eml_doc = up_eml["payload"]["response"]
            assert eml_doc["has_vector"], eml_doc
            print(
                f"[ok] live email .eml ingest: doc={eml_doc['document_id']} "
                f"chunks={eml_doc['chunks_count']} has_vector={eml_doc['has_vector']}"
            )

            s_eml = call(
                "search",
                {
                    "query": "live email pipeline",
                    "dataset_ids": [dataset_id],
                    "top_n": 3,
                    "vector_similarity_weight": 0.5,
                    "pipeline": "email",
                },
            )
            assert not s_eml["isError"], s_eml
            assert s_eml["payload"]["total"] >= 1, s_eml
            src = s_eml["payload"]["contexts"][0]["source"]
            assert src["chunk_id"].startswith(eml_doc["document_id"]), src
            # Live OpenAI embedding must produce a real vector similarity
            assert src["vector_similarity"] > 0.0, src
            print(
                f"[ok] live email search: vec_sim={src['vector_similarity']:.3f} "
                f"term_sim={src['term_similarity']:.3f} fused={src['similarity']:.3f}"
            )

            # metadata_condition filter on email sender
            s_filter = call(
                "search",
                {
                    "query": "marker",
                    "dataset_ids": [dataset_id],
                    "top_n": 3,
                    "vector_similarity_weight": 0.0,
                    "metadata_condition": {"sender": "Alice Lee <alice.live@example.com>"},
                },
            )
            assert not s_filter["isError"], s_filter
            assert s_filter["payload"]["total"] >= 1, s_filter
            print(
                f"[ok] live email metadata filter: total={s_filter['payload']['total']}"
            )

        # 11) graph_rebuild + Cypher
        gr = call("graph_rebuild")
        assert not gr["isError"], gr
        print(f"[ok] graph_rebuild: {gr['payload']}")
        gq = call(
            "graph_query",
            {
                "cypher": "MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk) WHERE d.id = $did RETURN COUNT(c) AS chunks",
                "params": {"did": document_id},
                "limit": 5,
            },
        )
        assert not gq["isError"], gq
        chunks_in_graph = gq["payload"]["rows"][0]["chunks"]
        assert chunks_in_graph == doc_resp["chunks_count"], (gq["payload"], doc_resp)
        print(f"[ok] graph_query: doc {document_id[:10]} has {chunks_in_graph} chunks in graph")

        # 12) health AFTER ingest
        h1 = call("health")
        assert not h1["isError"], h1
        print(f"[ok] health post: counts={h1['payload']['counts']}")

        # 13) cleanup
        dd = call("delete_dataset", {"dataset_id": dataset_id})
        assert not dd["isError"], dd
        print(f"[ok] delete_dataset {dataset_id}")

        print("\nLIVE E2E ALL OK")
        return 0
    finally:
        try:
            if tmp_doc and tmp_doc.exists():
                tmp_doc.unlink()
        except Exception:
            pass
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        try:
            err = proc.stderr.read()
            if err:
                print("\n[server stderr tail]\n" + err[-2500:])
        except Exception:
            pass


def _read_response(proc, req_id: int, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            err_tail = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(
                f"server closed stdout before responding to id={req_id}.\nstderr:\n{err_tail}"
            )
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") == req_id:
            if "error" in msg:
                raise RuntimeError(f"JSON-RPC error for id={req_id}: {msg['error']}")
            return msg
    raise RuntimeError(f"timeout waiting for id={req_id}")


if __name__ == "__main__":
    sys.exit(main())
