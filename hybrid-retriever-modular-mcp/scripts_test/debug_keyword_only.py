"""Debug keyword_only pipeline returning 0 results for English text."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault(
    "RETRIEVER_DATA_ROOT",
    r"C:\Users\joung\slsi-cowork-plugins\hybrid-retriever-modular-mcp\data",
)

from retriever import storage, api as retriever_api
from retriever.config import load_config
from mcp_server.handlers import _run_upload_directory, silenced_stdout

cfg = load_config()

with storage.sqlite_session(cfg) as conn:
    storage.ensure_dataset(conn, "kw_debug", "kw debug", "")

_run_upload_directory(cfg, {
    "dataset_id": "kw_debug",
    "dir_path": str(Path(__file__).parent.parent / "test_data" / "benchmark_docs"),
    "pipeline": "keyword_only",
})

with storage.sqlite_session(cfg) as conn:
    n = conn.execute("SELECT COUNT(*) FROM chunks WHERE dataset_id=?", ("kw_debug",)).fetchone()[0]
    fts_n = conn.execute("SELECT COUNT(*) FROM chunk_fts WHERE dataset_id=?", ("kw_debug",)).fetchone()[0]
    print(f"chunks: {n}, fts rows: {fts_n}")

    rows_rag = conn.execute(
        "SELECT content FROM chunk_fts WHERE dataset_id='kw_debug' AND chunk_fts MATCH 'RAG' LIMIT 3"
    ).fetchall()
    print(f"FTS5 'RAG' hits: {len(rows_rag)}")

    rows_ret = conn.execute(
        "SELECT content FROM chunk_fts WHERE dataset_id='kw_debug' AND chunk_fts MATCH 'retrieval' LIMIT 3"
    ).fetchall()
    print(f"FTS5 'retrieval' hits: {len(rows_ret)}")

    rows_vec = conn.execute(
        "SELECT content FROM chunk_fts WHERE dataset_id='kw_debug' AND chunk_fts MATCH 'vector' LIMIT 3"
    ).fetchall()
    print(f"FTS5 'vector' hits: {len(rows_vec)}")

# Try search via API
with silenced_stdout():
    result = retriever_api.hybrid_search(
        cfg,
        "RAG retrieval vector database",
        ["kw_debug"],
        pipeline="keyword_only",
        top=5,
        top_k=50,
    )
print(f"API search results: {result['total']}")
for item in result["items"][:2]:
    print(f"  score={item['similarity']:.3f} term={item['term_similarity']:.3f}: {item['content'][:60]}")

# Cleanup
with storage.sqlite_session(cfg) as conn:
    conn.execute("DELETE FROM chunk_fts WHERE dataset_id='kw_debug'")
    conn.execute("DELETE FROM chunks WHERE dataset_id='kw_debug'")
    conn.execute("DELETE FROM documents WHERE dataset_id='kw_debug'")
    conn.execute("DELETE FROM datasets WHERE dataset_id='kw_debug'")
import shutil
shutil.rmtree(cfg.dataset_dir("kw_debug"), ignore_errors=True)
print("Cleanup done")
