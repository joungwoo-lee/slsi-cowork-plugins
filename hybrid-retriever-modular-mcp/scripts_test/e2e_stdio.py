"""End-to-end MCP stdio test for the modular retriever.

Spawns ``py -3.12 server.py`` as a child process, drives JSON-RPC through
stdin/stdout, and asserts that every MCP tool returns the legacy response
shape with the new modular pipelines wired in.

Run:    py -3.12 scripts_test/e2e_stdio.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    data_root = Path(tempfile.mkdtemp(prefix="retriever_e2e_"))
    env = os.environ.copy()
    env["RETRIEVER_DATA_ROOT"] = str(data_root)
    env["RETRIEVER_DEFAULT_DATASETS"] = "e2e_docs"
    # No embedding API configured -> keyword-only search path.
    env["EMBEDDING_API_URL"] = ""
    env["EMBEDDING_DIM"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")

    print(f"[e2e] data_root={data_root}")

    server_py = REPO / "server.py"
    proc = subprocess.Popen(
        ["py", "-3.12", str(server_py)],
        cwd=str(REPO),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    next_id = iter(range(1, 10_000))

    def send(method: str, params: dict | None = None, *, is_notification: bool = False):
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if not is_notification:
            msg["id"] = next(next_id)
        if params is not None:
            msg["params"] = params
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        if is_notification:
            return None
        return _read_response(proc, msg["id"])

    def call_tool(name: str, arguments: dict | None = None) -> dict:
        resp = send("tools/call", {"name": name, "arguments": arguments or {}})
        result = resp.get("result")
        assert result is not None, f"tool {name} returned no result: {resp}"
        content = result.get("content") or []
        text = content[0].get("text") if content else ""
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = text
        is_error = bool(result.get("isError"))
        return {"isError": is_error, "payload": payload, "raw": result}

    try:
        # 1. initialize
        init = send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "1.0"},
            },
        )
        assert init["result"]["protocolVersion"], init
        send("notifications/initialized", {}, is_notification=True)
        print("[ok] initialize")

        # 2. tools/list — cold start exposes only top-level entry points.
        # Follow-up tools (get_job, list_documents, ...) are hidden until
        # the parent tool reveals them via tools/list_changed.
        listing = send("tools/list")
        tools = listing["result"]["tools"]
        names = {t["name"] for t in tools}
        for required in ("search", "upload", "list_datasets", "admin_help"):
            assert required in names, f"missing default tool: {required}"
        for hidden in (
            "get_job",
            "get_dataset",
            "list_documents",
            "get_document_content",
            "health",
            "list_chunks",
            "list_pipelines",
            "graph_query",
            "graph_rebuild",
            "create_dataset",
            "delete_dataset",
            "delete_document",
        ):
            assert hidden not in names, f"tool leaked into default catalog: {hidden}"
        print(f"[ok] tools/list cold start ({len(tools)} tools)")

        # 2b. admin_help reveals the full admin + flow follow-up set.
        ah = call_tool("admin_help")
        assert not ah["isError"], ah
        listing2 = send("tools/list")
        names2 = {t["name"] for t in listing2["result"]["tools"]}
        for revealed in (
            "get_job", "get_dataset", "list_documents", "get_document_content",
            "create_dataset", "delete_dataset", "delete_document",
            "list_chunks", "health", "graph_query", "graph_rebuild",
            "list_pipelines",
        ):
            assert revealed in names2, f"admin_help did not reveal {revealed}"
        print(f"[ok] admin_help revealed full catalog ({len(names2)} tools)")

        # 3. create_dataset
        create = call_tool("create_dataset", {"name": "e2e docs"})
        assert not create["isError"], create
        dataset_id = create["payload"]["id"]
        print(f"[ok] create_dataset -> {dataset_id}")

        # 4. upload_document — write a tiny Korean+English text file
        sample = data_root / "sample.md"
        sample.write_text(
            "# 모듈러 RAG 노트\n\n"
            "이 문서는 Haystack 파이프라인과 Hypster 설정 공간을 합쳐 "
            "검색 엔진을 모듈러로 분해한 사례입니다. RRF fusion과 linear "
            "fusion 두 가지 모드를 모두 지원합니다.\n\n"
            "Modular RAG decomposes retrieval into reusable components.",
            encoding="utf-8",
        )
        up = call_tool(
            "upload",
            {
                "dataset_id": dataset_id,
                "path": str(sample),
                "skip_embedding": True,
                "async": False,
            },
        )
        assert not up["isError"], up
        doc = up["payload"]["response"]
        document_id = doc["document_id"]
        assert doc["chunks_count"] >= 1, doc
        print(
            f"[ok] upload (file, sync) -> doc {document_id}, "
            f"chunks={doc['chunks_count']}, has_vector={doc['has_vector']}"
        )

        # 4b. upload async: response must embed a structured next_action so
        #     a small model can call get_job without re-reading tools/list.
        async_sample = data_root / "sample_async.md"
        async_sample.write_text("async test doc.", encoding="utf-8")
        up_async = call_tool(
            "upload",
            {
                "dataset_id": dataset_id,
                "path": str(async_sample),
                "skip_embedding": True,
                "async": True,
            },
        )
        assert not up_async["isError"], up_async
        na = up_async["payload"].get("next_action") or {}
        assert na.get("tool") == "get_job", up_async["payload"]
        assert na.get("arguments", {}).get("job_id"), up_async["payload"]
        print(f"[ok] upload async next_action -> {na['tool']}({na['arguments']})")

        # 5. list_documents
        ld = call_tool("list_documents", {"dataset_id": dataset_id})
        assert not ld["isError"], ld
        assert any(d["document_id"] == document_id for d in ld["payload"]), ld["payload"]
        print(f"[ok] list_documents ({len(ld['payload'])})")

        # 6. list_chunks
        chunks = call_tool(
            "list_chunks", {"dataset_id": dataset_id, "document_id": document_id, "limit": 20}
        )
        assert not chunks["isError"], chunks
        assert chunks["payload"], "expected chunks"
        print(f"[ok] list_chunks ({len(chunks['payload'])})")

        # 7. search — Korean keyword, linear fusion (default)
        s1 = call_tool(
            "search",
            {
                "query": "모듈러",
                "dataset_ids": [dataset_id],
                "top_n": 5,
                "vector_similarity_weight": 0.0,
                "fusion": "linear",
            },
        )
        assert not s1["isError"], s1
        assert s1["payload"]["total"] >= 1, s1["payload"]
        first_ctx = s1["payload"]["contexts"][0]
        assert first_ctx["source"]["chunk_id"].startswith(document_id), first_ctx
        print(
            "[ok] search linear/korean: "
            f"total={s1['payload']['total']}, top_score={first_ctx['source']['similarity']}"
        )

        # 8. search — English keyword, RRF
        s2 = call_tool(
            "search",
            {
                "query": "Modular",
                "dataset_ids": [dataset_id],
                "top_n": 5,
                "vector_similarity_weight": 0.0,
                "fusion": "rrf",
            },
        )
        assert not s2["isError"], s2
        assert s2["payload"]["total"] >= 1, s2["payload"]
        print(f"[ok] search rrf/english: total={s2['payload']['total']}")

        # 9. list_pipelines (now includes registered profiles)
        lp = call_tool("list_pipelines")
        assert not lp["isError"], lp
        assert "default_retrieval" in lp["payload"], lp
        profile_names = [p["name"] for p in lp["payload"].get("profiles", [])]
        assert "default" in profile_names, profile_names
        assert "keyword_only" in profile_names, profile_names
        print(f"[ok] list_pipelines: profiles={profile_names}")

        # 9b. search with explicit pipeline="default" -> equals implicit default
        s_default = call_tool(
            "search",
            {
                "query": "모듈러",
                "dataset_ids": [dataset_id],
                "top_n": 5,
                "vector_similarity_weight": 0.0,
                "fusion": "linear",
                "pipeline": "default",
            },
        )
        assert not s_default["isError"], s_default
        assert s_default["payload"]["total"] == s1["payload"]["total"], (
            s_default["payload"], s1["payload"],
        )
        print(
            f"[ok] search pipeline=default matches implicit default "
            f"(total={s_default['payload']['total']})"
        )

        # 9c. search with pipeline="keyword_only" -> RRF, vector forced off
        s_kw = call_tool(
            "search",
            {
                "query": "모듈러",
                "dataset_ids": [dataset_id],
                "top_n": 5,
                # Try to enable vectors -- the profile must override and force them off.
                "vector_similarity_weight": 0.9,
                "fusion": "linear",
                "pipeline": "keyword_only",
            },
        )
        assert not s_kw["isError"], s_kw
        assert s_kw["payload"]["total"] >= 1, s_kw["payload"]
        ctx_kw = s_kw["payload"]["contexts"][0]["source"]
        # keyword_only forces vector_similarity_weight=0, so vector_similarity stays 0
        assert ctx_kw["vector_similarity"] == 0.0, ctx_kw
        # Forces fusion=rrf -> score collapses to 1/(rrf_k + rank).
        # For rank 1 with rrf_k=60 that's 1/61 ~= 0.0164.
        expected_rrf = 1.0 / (60 + 1)
        assert abs(ctx_kw["similarity"] - expected_rrf) < 1e-3, (ctx_kw, expected_rrf)
        print(
            f"[ok] search pipeline=keyword_only: vec_sim={ctx_kw['vector_similarity']} "
            f"(forced 0), term_sim={ctx_kw['term_similarity']}, "
            f"fused={ctx_kw['similarity']} (RRF rank-1 ~= {expected_rrf:.4f})"
        )

        # 10. health
        h = call_tool("health")
        assert not h["isError"], h
        assert h["payload"]["counts"]["documents"] >= 1, h
        print(f"[ok] health: counts={h['payload']['counts']}")

        # 11. graph_rebuild + graph_query
        gr = call_tool("graph_rebuild")
        assert not gr["isError"], gr
        assert gr["payload"]["chunks"] >= 1, gr
        print(f"[ok] graph_rebuild: {gr['payload']}")

        gq = call_tool(
            "graph_query",
            {"cypher": "MATCH (c:Chunk) RETURN COUNT(c) AS n", "limit": 5},
        )
        assert not gq["isError"], gq
        assert gq["payload"]["rows"], gq
        print(f"[ok] graph_query: rows={gq['payload']['rows']}")

        # 11b. upload_document — larger file + hierarchical chunking
        large_path = data_root / "large.md"
        long_para = (
            "Haystack 컴포넌트는 입력과 출력 타입이 정해진 작은 블록입니다. "
            "Hypster는 이런 블록을 모듈러하게 조합하기 위한 설정 공간을 제공합니다. "
            "RRF fusion, linear fusion, parent-child chunking은 모두 독립 컴포넌트로 분해됩니다.\n\n"
        )
        large_path.write_text((long_para * 12) + "End of doc.", encoding="utf-8")
        up2 = call_tool(
            "upload",
            {
                "dataset_id": dataset_id,
                "path": str(large_path),
                "skip_embedding": True,
                "use_hierarchical": "true",
                "async": False,
            },
        )
        assert not up2["isError"], up2
        doc2 = up2["payload"]["response"]
        assert doc2["chunks_count"] > 1, doc2
        assert doc2["is_hierarchical"], doc2
        assert doc2["parent_chunks_count"] >= 1, doc2
        print(
            f"[ok] upload (file, hierarchical, sync): chunks={doc2['chunks_count']}, "
            f"parents={doc2['parent_chunks_count']}"
        )

        s3 = call_tool(
            "search",
            {
                "query": "fusion",
                "dataset_ids": [dataset_id],
                "top_n": 3,
                "vector_similarity_weight": 0.0,
                "fusion": "linear",
                "parent_chunk_replace": True,
            },
        )
        assert not s3["isError"], s3
        assert s3["payload"]["total"] >= 1, s3["payload"]
        first = s3["payload"]["contexts"][0]
        assert first["source"]["chunk_id"].startswith(doc2["document_id"]) or first["source"]["chunk_id"].startswith(document_id), first
        print(f"[ok] search hierarchical/parent-replace: total={s3['payload']['total']}")

        # 11c. upload_directory bulk path
        bulk_dir = data_root / "bulk"
        bulk_dir.mkdir()
        for i in range(3):
            (bulk_dir / f"note_{i}.md").write_text(
                f"# bulk doc {i}\n\nThis document mentions modular RAG and Haystack.",
                encoding="utf-8",
            )
        ud = call_tool(
            "upload",
            {
                "dataset_id": dataset_id,
                "path": str(bulk_dir),
                "skip_embedding": True,
                "async": False,
            },
        )
        assert not ud["isError"], ud
        assert ud["payload"]["processed_count"] == 3, ud["payload"]
        assert ud["payload"]["error_count"] == 0, ud["payload"]
        print(f"[ok] upload (directory, sync): processed={ud['payload']['processed_count']}")

        # 11d. Email profile: ingest email-mcp-style mail directory (PST ingest requires real .pst)
        email_dir_marker = f"email_dir_marker_{int(time.time())}"
        mail_dir = data_root / "mail_42"
        mail_dir.mkdir()
        (mail_dir / "meta.json").write_text(
            json.dumps(
                {
                    "mail_id": "mail_42",
                    "subject": "Project Kuzu graph",
                    "sender": "carol@example.com",
                    "received": "2026-04-01T10:00:00+09:00",
                    "folder_path": "INBOX/projects",
                }
            )
        )
        (mail_dir / "body.md").write_text(
            f"# Project Kuzu graph\n\nThis is a pre-converted mail body ({email_dir_marker}).",
            encoding="utf-8",
        )
        up_dir = call_tool(
            "upload",
            {
                "dataset_id": dataset_id,
                "path": str(mail_dir),
                "skip_embedding": True,
                "pipeline": "email",
                "async": False,
            },
        )
        assert not up_dir["isError"], up_dir
        print(f"[ok] email-mcp dir ingest: chunks={up_dir['payload']['response']['chunks_count']}")

        s5 = call_tool("search", {"query": email_dir_marker, "dataset_ids": [dataset_id]})
        assert not s5["isError"], s5
        assert s5["payload"]["total"] >= 1, s5["payload"]
        first_email_ctx = s5["payload"]["contexts"][0]
        assert email_dir_marker in first_email_ctx["text"], first_email_ctx
        print(f"[ok] email-mcp dir searchable: total={s5['payload']['total']}")

        # 12. delete_document
        del_doc = call_tool(
            "delete_document", {"dataset_id": dataset_id, "document_id": document_id}
        )
        assert not del_doc["isError"], del_doc
        print("[ok] delete_document")

        # 13. delete_dataset
        del_ds = call_tool("delete_dataset", {"dataset_id": dataset_id})
        assert not del_ds["isError"], del_ds
        print("[ok] delete_dataset")

        print("\nALL OK")
        return 0
    finally:
        try:
            proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        try:
            err_tail = proc.stderr.read()
            if err_tail:
                print("\n[server stderr tail]", err_tail[-2000:])
        except Exception:
            pass
        shutil.rmtree(data_root, ignore_errors=True)


def _read_response(proc: subprocess.Popen, req_id: int, timeout: float = 90.0) -> dict:
    """Read JSON-RPC responses from the server until we see one with req_id.

    Tolerates intermediate notifications/logs (per spec, those go to stderr,
    but be defensive in case anything else slips out).
    """
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
