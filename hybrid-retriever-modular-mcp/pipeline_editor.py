"""Local web UI for editing hybrid-retriever pipelines.

Run:  py -3.12 pipeline_editor.py

Opens http://127.0.0.1:8765 in the default browser. The page lists the
component catalogue on the left (grouped by pipeline stage), lets you
configure each component's constructor parameters, define connections
between them, and shows the resulting DAG as an SVG graph on the right.

Saving writes:
  * pipelines/<name>_indexing.json (or _retrieval.json) - node-centric topology
  * $RETRIEVER_DATA_ROOT/pipelines.json - profile entry that points to it,
    matching the format used by the MCP ``save_pipeline`` tool.

Dependencies: stdlib only on the server. The browser pulls dagre from
cdn.jsdelivr.net (cached after first load).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from retriever.pipelines import editor_store

ROOT = Path(__file__).resolve().parent
PIPELINES_DIR = editor_store.PIPELINES_DIR
REGISTRY_PATH = editor_store.REGISTRY_PATH

# Resolve the data root the same way retriever.config does, without importing
# the package (so the editor still runs if haystack is not installed).
DATA_ROOT = editor_store.user_profiles_path().parent
USER_PROFILES_PATH = editor_store.user_profiles_path()


# --- Component catalogue ----------------------------------------------------
#
# Each entry mirrors the @component decorator metadata of the underlying
# class: constructor params, input ports, output ports. Kept as static data
# so the editor starts even if importing retriever.* would fail (e.g. when
# haystack is not installed on the editing machine).

CATALOG: list[dict] = [
    {
        "name": "LocalFileLoader",
        "cls": "retriever.components.file_loader.LocalFileLoader",
        "stage": "load",
        "params": [{"name": "max_chars", "type": "int", "default": 2000000}],
        "inputs": [{"name": "path", "type": "str"}],
        "outputs": [
            {"name": "text", "type": "str"},
            {"name": "path", "type": "str"},
            {"name": "size_bytes", "type": "int"},
        ],
    },
    {
        "name": "EmailSourceLoader",
        "cls": "retriever.components.email_loader.EmailSourceLoader",
        "stage": "load",
        "params": [{"name": "worker_path", "type": "str", "default": ""}],
        "inputs": [{"name": "path", "type": "str"}],
        "outputs": [
            {"name": "raw_emails", "type": "List[dict]"},
            {"name": "path", "type": "str"},
        ],
    },
    {
        "name": "EmailMarkdownConverter",
        "cls": "retriever.components.email_markdown_converter.EmailMarkdownConverter",
        "stage": "convert",
        "params": [
            {"name": "max_body_chars", "type": "int", "default": 1000000},
            {"name": "max_attachment_chars", "type": "int", "default": 500000},
        ],
        "inputs": [{"name": "raw_emails", "type": "List[dict]"}],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "HierarchicalSplitter",
        "cls": "retriever.components.hierarchical_splitter.HierarchicalSplitter",
        "stage": "split",
        "params": [
            {"name": "chunk_chars", "type": "int", "default": 512},
            {"name": "chunk_overlap", "type": "int", "default": 50},
            {"name": "parent_chunk_chars", "type": "int", "default": 1024},
            {"name": "parent_chunk_overlap", "type": "int", "default": 100},
            {"name": "child_chunk_chars", "type": "int", "default": 256},
            {"name": "child_chunk_overlap", "type": "int", "default": 50},
        ],
        "inputs": [
            {"name": "text", "type": "str"},
            {"name": "documents", "type": "List[Document]"},
            {"name": "dataset_id", "type": "str"},
            {"name": "document_id", "type": "str"},
            {"name": "document_name", "type": "str"},
            {"name": "use_hierarchical", "type": "Any"},
            {"name": "metadata", "type": "dict"},
        ],
        "outputs": [
            {"name": "documents", "type": "List[Document]"},
            {"name": "chunks_count", "type": "int"},
            {"name": "parent_chunks_count", "type": "int"},
        ],
    },
    {
        "name": "HttpDocumentEmbedder",
        "cls": "retriever.components.document_embedder.HttpDocumentEmbedder",
        "stage": "embed",
        "params": [
            {"name": "api_url", "type": "str", "default": ""},
            {"name": "api_key", "type": "str", "default": ""},
            {"name": "model", "type": "str", "default": ""},
            {"name": "dim", "type": "int", "default": 0},
            {"name": "x_dep_ticket", "type": "str", "default": ""},
            {"name": "x_system_name", "type": "str", "default": "hybrid-retriever-modular-mcp"},
            {"name": "batch_size", "type": "int", "default": 16},
            {"name": "timeout_sec", "type": "int", "default": 60},
            {"name": "verify_ssl", "type": "bool", "default": False},
        ],
        "inputs": [{"name": "documents", "type": "List[Document]"}],
        "outputs": [
            {"name": "documents", "type": "List[Document]"},
            {"name": "has_vector", "type": "bool"},
        ],
    },
    {
        "name": "HttpTextEmbedder",
        "cls": "retriever.components.document_embedder.HttpTextEmbedder",
        "stage": "embed",
        "params": [
            {"name": "api_url", "type": "str", "default": ""},
            {"name": "api_key", "type": "str", "default": ""},
            {"name": "model", "type": "str", "default": ""},
            {"name": "dim", "type": "int", "default": 0},
            {"name": "x_dep_ticket", "type": "str", "default": ""},
            {"name": "x_system_name", "type": "str", "default": "hybrid-retriever-modular-mcp"},
            {"name": "batch_size", "type": "int", "default": 16},
            {"name": "timeout_sec", "type": "int", "default": 60},
            {"name": "verify_ssl", "type": "bool", "default": False},
        ],
        "inputs": [{"name": "text", "type": "str"}],
        "outputs": [{"name": "embedding", "type": "List[float]"}],
    },
    {
        "name": "SqliteFts5Writer",
        "cls": "retriever.components.fts5_writer.SqliteFts5Writer",
        "stage": "write",
        "params": [{"name": "data_root", "type": "str", "default": ""}],
        "inputs": [{"name": "documents", "type": "List[Document]"}],
        "outputs": [{"name": "written", "type": "int"}],
    },
    {
        "name": "LocalQdrantWriter",
        "cls": "retriever.components.vector_retriever.LocalQdrantWriter",
        "stage": "write",
        "params": [
            {"name": "data_root", "type": "str", "default": ""},
            {"name": "collection", "type": "str", "default": "retriever_chunks"},
        ],
        "inputs": [
            {"name": "documents", "type": "List[Document]"},
            {"name": "has_vector", "type": "bool"},
        ],
        "outputs": [{"name": "written", "type": "int"}],
    },
    {
        "name": "LocalQdrantRetriever",
        "cls": "retriever.components.vector_retriever.LocalQdrantRetriever",
        "stage": "retrieve",
        "params": [
            {"name": "data_root", "type": "str", "default": ""},
            {"name": "collection", "type": "str", "default": "retriever_chunks"},
        ],
        "inputs": [
            {"name": "embedding", "type": "List[float]"},
            {"name": "dataset_ids", "type": "List[str]"},
            {"name": "top_k", "type": "int"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "Fts5Retriever",
        "cls": "retriever.components.fts5_retriever.Fts5Retriever",
        "stage": "retrieve",
        "params": [{"name": "data_root", "type": "str", "default": ""}],
        "inputs": [
            {"name": "query", "type": "str"},
            {"name": "dataset_ids", "type": "List[str]"},
            {"name": "top_k", "type": "int"},
            {"name": "enabled", "type": "bool"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "GraphChunkRetriever",
        "cls": "retriever.components.graph_retriever.GraphChunkRetriever",
        "stage": "retrieve",
        "params": [{"name": "data_root", "type": "str", "default": ""}],
        "inputs": [
            {"name": "query", "type": "str"},
            {"name": "dataset_ids", "type": "List[str]"},
            {"name": "top_k", "type": "int"},
            {"name": "enabled", "type": "bool"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "LinearJoiner",
        "cls": "retriever.components.linear_joiner.LinearJoiner",
        "stage": "fuse",
        "params": [
            {"name": "vector_weight", "type": "float", "default": 0.5}
        ],
        "inputs": [
            {"name": "keyword_documents", "type": "List[Document]"},
            {"name": "semantic_documents", "type": "List[Document]"},
            {"name": "graph_documents", "type": "List[Document]"},
            {"name": "vector_weight", "type": "float"},
            {"name": "metadata_condition", "type": "dict"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "RrfJoiner",
        "cls": "retriever.components.rrf_joiner.RrfJoiner",
        "stage": "fuse",
        "params": [
            {"name": "rrf_k", "type": "int", "default": 60}
        ],
        "inputs": [
            {"name": "keyword_documents", "type": "List[Document]"},
            {"name": "semantic_documents", "type": "List[Document]"},
            {"name": "graph_documents", "type": "List[Document]"},
            {"name": "rrf_k", "type": "int"},
            {"name": "metadata_condition", "type": "dict"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "BgeReranker",
        "cls": "retriever.components.bge_reranker.BgeReranker",
        "stage": "rerank",
        "params": [
            {"name": "model", "type": "str", "default": "BAAI/bge-reranker-v2-m3"},
            {"name": "use_fp16", "type": "bool", "default": True},
            {"name": "batch_size", "type": "int", "default": 32},
            {"name": "max_length", "type": "int", "default": 512},
            {"name": "device", "type": "str", "default": ""},
        ],
        "inputs": [
            {"name": "documents", "type": "List[Document]"},
            {"name": "query", "type": "str"},
            {"name": "top_n", "type": "int"},
            {"name": "enabled", "type": "bool"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "ParentChunkReplacer",
        "cls": "retriever.components.parent_replace.ParentChunkReplacer",
        "stage": "post",
        "params": [
            {"name": "enabled", "type": "bool", "default": True},
        ],
        "inputs": [
            {"name": "documents", "type": "List[Document]"},
            {"name": "enabled", "type": "bool"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
]

STAGES = [
    ("load", "Load"),
    ("convert", "Convert"),
    ("split", "Split"),
    ("embed", "Embed"),
    ("write", "Write"),
    ("retrieve", "Retrieve"),
    ("fuse", "Fuse"),
    ("rerank", "Rerank"),
    ("post", "Post-process"),
]


# --- Disk I/O ---------------------------------------------------------------

def _read_json(path: Path) -> dict:
    return editor_store.read_json(path)


def _atomic_write_json(path: Path, data: dict) -> None:
    editor_store.atomic_write_json(path, data)


def _topology_metadata_description(topology_file: str | None) -> str:
    """Pull ``metadata.description`` out of a topology JSON next to PIPELINES_DIR."""
    if not topology_file:
        return ""
    raw = _read_json(PIPELINES_DIR / topology_file)
    meta = raw.get("metadata") if isinstance(raw, dict) else None
    desc = meta.get("description") if isinstance(meta, dict) else None
    return desc if isinstance(desc, str) else ""


def _hydrate_description(entry: dict) -> dict:
    """Fill in ``description`` from the referenced topology if the profile omits it."""
    if entry.get("description"):
        return entry
    topo = (
        entry.get("unified_topology")
        or entry.get("retrieval_topology")
        or entry.get("indexing_topology")
    )
    desc = _topology_metadata_description(topo)
    if desc:
        return {**entry, "description": desc}
    return entry


def load_pipeline_list() -> list[dict]:
    """Return one entry per known pipeline (registry.json + user pipelines.json)."""
    out: dict[str, dict] = {}
    for name, item in _read_json(REGISTRY_PATH).items():
        if isinstance(item, dict):
            out[name] = _hydrate_description({**item, "name": name, "source": "builtin"})
    for name, item in _read_json(USER_PROFILES_PATH).items():
        if isinstance(item, dict):
            out[name] = _hydrate_description({**item, "name": name, "source": "user"})
    return list(out.values())


def load_pipeline_detail(name: str) -> dict:
    """Return profile metadata + the two topology JSON blobs (if any).

    Topology blobs are coerced into the node-centric shape the editor renders,
    regardless of whether the on-disk file uses node-centric or standard
    format.
    """
    profile: dict | None = None
    for entry in load_pipeline_list():
        if entry["name"] == name:
            profile = entry
            break
    if profile is None:
        return {"error": f"pipeline not found: {name}"}

    def _load(topo_name: str | None) -> dict | None:
        if not topo_name:
            return None
        raw = _read_json(PIPELINES_DIR / topo_name)
        if not raw:
            return None
        return editor_store.topology_for_ui(raw)

    topo_indexing = profile.get("indexing_topology")
    topo_retrieval = profile.get("retrieval_topology")
    topo_unified = profile.get("unified_topology")
    out = dict(profile)
    out["indexing"] = _load(topo_indexing)
    out["retrieval"] = _load(topo_retrieval)
    out["unified"] = _load(topo_unified)
    return out


def save_pipeline(payload: dict) -> dict:
    """Persist a pipeline edited in the UI."""
    return editor_store.save_pipeline_payload(
        payload,
        pipelines_dir=PIPELINES_DIR,
        profiles_path=USER_PROFILES_PATH,
    )


def _normalise_topology(raw: dict) -> dict:
    """Coerce a UI topology into the Haystack v2 JSON shape."""
    return editor_store.normalise_topology(raw)


# --- HTTP server ------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet
        return

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._send_html(INDEX_HTML)
        elif url.path == "/api/catalog":
            self._send_json({"components": CATALOG, "stages": STAGES})
        elif url.path == "/api/health":
            self._send_json({"status": "ok"})
        elif url.path == "/api/pipelines":
            self._send_json({"pipelines": load_pipeline_list()})
        elif url.path.startswith("/api/pipelines/"):
            name = url.path[len("/api/pipelines/"):]
            detail = load_pipeline_detail(name)
            self._send_json(detail, status=404 if detail.get("error") else 200)
        else:
            self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"invalid JSON: {exc}"}, status=400)
            return
        if url.path == "/api/pipelines":
            result = save_pipeline(payload)
            self._send_json(result, status=400 if result.get("error") else 200)
        else:
            self.send_error(404)


def _pick_port(preferred: int = 8765) -> int:
    """Bind the preferred port if free, otherwise ask the OS for any free one."""
    for port in (preferred, 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            chosen = s.getsockname()[1]
            s.close()
            return chosen
        except OSError:
            s.close()
            continue
    raise RuntimeError("no free port available")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retriever pipeline editor")
    parser.add_argument("--port", type=int, default=8765, help="Preferred port to bind")
    parser.add_argument("--state-file", type=str, default="", help="Optional JSON state file path")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the editor without opening the browser automatically.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    port = _pick_port(args.port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    state_file = Path(args.state_file) if args.state_file else None
    if state_file:
        _atomic_write_json(state_file, {
            "pid": os.getpid(),
            "port": port,
            "url": url,
            "started_at": time.time(),
        })
    print(f"Pipeline editor: {url}")
    print("Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        if state_file and state_file.exists():
            try:
                current = _read_json(state_file)
                if current.get("pid") == os.getpid():
                    state_file.unlink(missing_ok=True)
            except OSError:
                pass
        httpd.server_close()
    return 0


# --- Inline single-page UI --------------------------------------------------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Retriever Pipeline Editor</title>
<style>
:root {
  --bg: #0f1115;
  --panel: #161a22;
  --panel-2: #1c2230;
  --border: #2a3142;
  --text: #e6e9ef;
  --muted: #8b93a7;
  --accent: #5aa9ff;
  --accent-2: #7c5cff;
  --warn: #ffb454;
  --bad: #ff6b6b;
  --ok: #5fd497;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); font-size: 13px; }
button, input, select, textarea { font: inherit; color: var(--text); }
button {
  background: var(--panel-2); border: 1px solid var(--border); color: var(--text);
  padding: 6px 10px; border-radius: 6px; cursor: pointer;
}
button:hover { border-color: var(--accent); }
button.primary { background: var(--accent); color: #0b1220; border-color: var(--accent); font-weight: 600; }
button.primary:hover { background: #7dbbff; }
input, select, textarea {
  background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 8px; width: 100%;
}
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); }
label { display: block; font-size: 11px; color: var(--muted); margin-bottom: 3px; text-transform: uppercase; letter-spacing: 0.04em; }

#app { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
#main-container { flex: 1; min-height: 0; display: flex; gap: 20px; padding: 20px; overflow: hidden; flex-direction: row; align-items: stretch; }
#settings-panel { flex: 0 0 760px; min-width: 760px; max-width: 760px; overflow-y: auto; }

#right {
  flex: 1 1 auto;
  min-width: 520px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--panel);
  overflow: hidden;
}

#topbar {
  display: flex; gap: 12px; padding: 12px 24px; border-bottom: 1px solid var(--border);
  background: var(--panel); align-items: center; position: sticky; top: 0; z-index: 100;
}
#topbar h1 { margin: 0; font-size: 16px; font-weight: 700; color: var(--accent); }
#topbar .spacer { flex: 1; }
#status { font-size: 11px; color: var(--muted); }

#graph-topbar {
  display: flex; align-items: center; padding: 12px 24px; background: var(--panel); border-bottom: 1px solid var(--border);
}
#graph-topbar h1 { margin: 0; font-size: 16px; font-weight: 700; }

#graph { flex: 1; position: relative; overflow: auto; background: #0b0d12; }
#graph svg { display: block; }
.node-rect { fill: var(--panel); stroke: var(--border); stroke-width: 1.2; rx: 8; ry: 8; cursor: pointer; }
.node-rect.selected { stroke: var(--accent); stroke-width: 2; }
.node-rect.external { fill: #111827; stroke: #4a5470; stroke-dasharray: 5 3; }
.node-title { fill: var(--text); font-size: 12px; font-weight: 600; }
.node-cls { fill: var(--muted); font-size: 10px; }
.port-text { fill: var(--muted); font-size: 10px; }
.port-dot { r: 3.5; }
.port-dot.in { fill: var(--accent); }
.port-dot.out { fill: var(--accent-2); }
.edge-line { fill: none; stroke: #4a5470; stroke-width: 1.4; }
.edge-line:hover { stroke: var(--accent); }

.section { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px; background: var(--panel-2); }
.section > .head { padding: 8px 10px; border-bottom: 1px solid var(--border); font-weight: 600; font-size: 12px; }
.section > .body { padding: 10px; }

.stage-box { border-bottom: 1px solid var(--border); padding: 12px 0; }
.stage-box:last-child { border-bottom: none; }
.stage-box .stage-num { font-size: 10px; font-weight: 700; color: var(--accent); margin-bottom: 4px; }
.stage-box .stage-title { font-size: 13px; font-weight: 600; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }

.module-entry { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 10px; margin-bottom: 8px; position: relative; }
.module-entry.selected { border-color: var(--accent); background: rgba(90,169,255,0.05); }
.module-entry .hdr { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.module-entry .nm { font-weight: 700; font-size: 12px; color: var(--accent); }
.module-entry .cls { font-size: 10px; color: var(--muted); }
.module-entry .del { color: var(--bad); cursor: pointer; font-size: 14px; padding: 0 4px; }

.params-grid { display: grid; grid-template-columns: 1fr; gap: 8px; border-top: 1px solid var(--border); padding-top: 10px; margin-top: 8px; }
.params-grid .p-row { display: grid; grid-template-columns: 100px 1fr; gap: 8px; align-items: center; }
.params-grid label { margin: 0; text-transform: none; color: var(--text); opacity: 0.8; font-size: 11px; }

.add-ctrl { margin-top: 8px; }
.add-ctrl select { font-size: 11px; padding: 4px 6px; height: 28px; }

.tabs { margin: 12px 0; }
.tab { flex: 1; text-align: center; font-weight: 600; }
</style>

</head>
<body>
<div id="app">
  <div id="topbar">
    <h1>Retriever Editor</h1>
    <span id="status"></span>
    <div class="spacer"></div>
    <button id="reset-btn">Reset</button>
    <button class="primary" id="save">Save Pipeline</button>
  </div>

  <div id="main-container">
    <div id="settings-panel">
      <div class="section">
        <div class="head">Step 1: Pipeline Basics</div>
        <div class="body">
          <div class="param-row">
            <label>Load existing</label>
            <select id="existing"><option value="">-- new pipeline --</option></select>
          </div>
          <div class="param-row">
            <label>Name</label>
            <input id="pname" placeholder="my_pipeline">
          </div>
          <div class="param-row">
            <label>Description</label>
            <textarea id="pdesc" rows="2"></textarea>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="head">Pipeline Configuration (Stages 1-8)</div>
        <div class="body">
          <div class="hint">Define modules and their parameters for each stage. These values are saved directly into the pipeline JSON.</div>
          <div id="dynamic-steps"></div>
        </div>
      </div>

      <div class="section">
        <div class="head">Finalise: Connections</div>
        <div class="body">
          <div id="conn-body"></div>
          <div style="margin-top:12px;">
            <button id="auto-wire" style="width:100%">Auto-wire all ports</button>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="head">Statistics</div>
        <div class="body overview-grid" id="overview"></div>
      </div>
    </div>
    <div id="right">
      <div id="graph-topbar">
        <h1>Pipeline Graph</h1>
      </div>
      <div id="graph"><div class="graph-empty" id="graph-empty">Add modules on the left to start building the pipeline graph.</div><svg id="canvas" width="100%" height="100%"></svg></div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script>
// ---------- state ----------
// The editor's in-memory topology is node-centric:
//   topo = { nodes: [{ name, module, params, inputs:[{port, from}], outputs:[{port, to}] }, ...] }
// Connections live inside each node (receiver side: inputs; sender side: outputs).
let CATALOG = [];
let STAGES = [];
let topo = { nodes: [] };
let selectedNode = null;

function currentTopo() { return topo; }
function findComp(cls) { return CATALOG.find(c => c.cls === cls); }

// ---------- topology helpers (node-centric model) ----------
function nodesArr() { return topo.nodes || (topo.nodes = []); }
function findNode(name) { return nodesArr().find(n => n.name === name); }
function nodeNames() { return nodesArr().map(n => n.name); }

function graphExternalSource(node, comp, portName) {
  if (!comp) return null;
  if (comp.stage === "load" && portName === "path") return "path";
  if (node.name === "fts5" && portName === "query") return "query";
  if (node.name === "graph" && portName === "query") return "query";
  if (node.name === "query_embedder" && portName === "text") return "query";
  if (node.name === "reranker" && portName === "query") return "query";
  return null;
}

// Flatten every node's inputs/outputs into {sender, receiver} pairs, deduped.
function allConnections() {
  const out = [];
  const seen = new Set();
  function push(sender, receiver) {
    if (!sender || !receiver) return;
    const key = sender + "->" + receiver;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ sender, receiver });
  }
  for (const n of nodesArr()) {
    for (const e of n.inputs || []) {
      if (e.port && e.from) push(e.from, n.name + "." + e.port);
    }
    for (const e of n.outputs || []) {
      if (e.port && e.to) push(n.name + "." + e.port, e.to);
    }
  }
  return out;
}

function graphConnections() {
  const out = allConnections().slice();
  const seen = new Set(out.map(e => e.sender + "->" + e.receiver));
  const connectedReceivers = new Set(out.map(e => e.receiver));
  for (const node of nodesArr()) {
    const comp = findComp(node.module);
    if (!comp) continue;
    for (const inp of comp.inputs || []) {
      const sourceNode = graphExternalSource(node, comp, inp.name);
      if (!sourceNode) continue;
      const receiver = `${node.name}.${inp.name}`;
      if (connectedReceivers.has(receiver)) continue;
      const sender = `${sourceNode}.${inp.name}`;
      const key = sender + "->" + receiver;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ sender, receiver, synthetic: true });
    }
  }
  return out;
}

function addConnection(sender, receiver) {
  if (!sender || !receiver || !sender.includes(".") || !receiver.includes(".")) return;
  const recvName = receiver.split(".")[0];
  const recvPort = receiver.slice(recvName.length + 1);
  const recv = findNode(recvName);
  if (!recv) return;
  recv.inputs = recv.inputs || [];
  if (recv.inputs.some(e => e.port === recvPort && e.from === sender)) return;
  recv.inputs.push({ port: recvPort, from: sender });
}

function removeConnection(sender, receiver) {
  if (!sender || !receiver) return;
  const recvName = receiver.split(".")[0];
  const recvPort = receiver.slice(recvName.length + 1);
  const recv = findNode(recvName);
  if (recv && recv.inputs) {
    recv.inputs = recv.inputs.filter(e => !(e.port === recvPort && e.from === sender));
  }
  const sendName = sender.split(".")[0];
  const sendPort = sender.slice(sendName.length + 1);
  const send = findNode(sendName);
  if (send && send.outputs) {
    send.outputs = send.outputs.filter(e => !(e.port === sendPort && e.to === receiver));
  }
}

function renameNode(oldName, newName) {
  if (!oldName || !newName || oldName === newName) return;
  if (findNode(newName)) return;
  const n = findNode(oldName);
  if (!n) return;
  n.name = newName;
  for (const m of nodesArr()) {
    for (const e of m.inputs || []) {
      if (e.from && e.from.startsWith(oldName + ".")) e.from = newName + e.from.slice(oldName.length);
    }
    for (const e of m.outputs || []) {
      if (e.to && e.to.startsWith(oldName + ".")) e.to = newName + e.to.slice(oldName.length);
    }
  }
}

// ---------- bootstrap ----------
async function boot() {
  try {
    const [cat, pipes] = await Promise.all([
      fetch("/api/catalog").then(r => r.json()),
      fetch("/api/pipelines").then(r => r.json()),
    ]);
    CATALOG = cat.components;
    STAGES = cat.stages;
    populatePipelineDropdown(pipes.pipelines || []);
    const sel = document.getElementById("existing");
    sel.addEventListener("change", onLoadPipeline);
    document.getElementById("save").addEventListener("click", onSave);
    document.getElementById("reset-btn").addEventListener("click", () => { topo = { nodes: [] }; selectedNode = null; document.getElementById("pname").value=""; document.getElementById("pdesc").value=""; sel.value=""; setStatus(""); redraw(); });
    document.getElementById("auto-wire").addEventListener("click", autoWire);
    redraw();
  } catch (err) {
    setStatus("boot failed: " + err.message, "bad");
    console.error(err);
  }
}

function populatePipelineDropdown(pipelines) {
  const sel = document.getElementById("existing");
  // wipe and rebuild so reloads stay consistent
  sel.innerHTML = '<option value="">-- new pipeline --</option>';
  for (const p of pipelines) {
    const o = document.createElement("option");
    o.value = p.name;
    o.textContent = p.name + " (" + (p.source || "user") + ")";
    sel.appendChild(o);
  }
}

function setStatus(text, cls) {
  const s = document.getElementById("status");
  if (!s) return;
  s.textContent = text || "";
  s.style.color = cls === "bad" ? "var(--bad)" : (cls === "ok" ? "var(--ok)" : "var(--muted)");
}

function bindEditorControl(el) {
  if (!el) return;
  el.addEventListener("mousedown", (e) => e.stopPropagation());
  el.addEventListener("click", (e) => e.stopPropagation());
}

// Map functional stages to standard engine component names
const STAGE_DEFAULTS = {
  load: "loader",
  convert: "converter",
  split: "splitter",
  embed: "embedder",
  write: "writer",
  retrieve: "retriever",
  fuse: "joiner",
  post: "parent"
};

// ---------- stage-based editor ----------
function renderStageEditor() {
  const container = document.getElementById("dynamic-steps");
  container.innerHTML = "";

  const activeStages = STAGES.map(s => s[0]);

  activeStages.forEach((sid, idx) => {
    const stageLabel = STAGES.find(s => s[0] === sid)?.[1] || sid;
    const section = document.createElement("div");
    section.className = "section";
    const pathLabel = (sid === "load" || sid === "convert" || sid === "split" || sid === "write") ? " (Indexing Path)" :
                     (sid === "retrieve" || sid === "fuse" || sid === "rerank" || sid === "post") ? " (Retrieval Path)" : " (Shared Path)";

    section.innerHTML = `
      <div class="head">Step ${idx + 2}: ${stageLabel}${pathLabel}</div>
      <div class="body" id="stage-body-${sid}"></div>
    `;
    container.appendChild(section);
    const body = section.querySelector(".body");

    // 1. Existing modules in this stage
    const stageNodes = nodesArr().filter(n => findComp(n.module)?.stage === sid);
    stageNodes.forEach(node => {
      const comp = findComp(node.module);
      const name = node.name;
      const entry = document.createElement("div");
      entry.className = "module-entry" + (selectedNode === name ? " selected" : "");
      entry.innerHTML = `
        <div class="hdr">
          <div class="nm">${name}</div>
          <div class="del" title="Remove">&times;</div>
        </div>
        <div class="cls">${comp ? comp.name : node.module}</div>

        <div class="p-row" style="margin: 8px 0;">
          <label style="font-size:9px">node name</label>
          <input type="text" value="${name}" class="node-rename-input" style="font-size:11px; padding:2px 6px; height:22px;">
        </div>

        <div class="params-grid" id="pgrid-${name}"></div>
      `;

      // Rename logic
      const renameInp = entry.querySelector(".node-rename-input");
      bindEditorControl(renameInp);
      renameInp.addEventListener("change", () => {
        const newName = renameInp.value.trim();
        if (!newName || newName === name || findNode(newName)) { renameInp.value = name; return; }
        renameNode(name, newName);
        selectedNode = newName;
        redraw();
      });

      entry.querySelector(".del").addEventListener("click", (e) => { e.stopPropagation(); removeNode(name); });
      entry.addEventListener("click", () => { selectedNode = name; redraw(); });

      // Parameters
      const pgrid = entry.querySelector(".params-grid");
      const params = node.params || (node.params = {});
      if (comp && comp.params.length) {
        comp.params.forEach(p => {
          const prow = document.createElement("div");
          prow.className = "p-row";
          prow.innerHTML = `<label>${p.name}</label>`;
          let inp;
          if (p.type === "bool") {
            inp = document.createElement("select");
            inp.innerHTML = `<option value="false">false</option><option value="true">true</option>`;
            inp.value = String(params[p.name] ?? p.default);
            bindEditorControl(inp);
            inp.addEventListener("change", () => { params[p.name] = inp.value === "true"; redraw(); });
          } else {
            inp = document.createElement("input");
            inp.value = params[p.name] ?? p.default ?? "";
            bindEditorControl(inp);
            inp.addEventListener("change", () => {
              let v = inp.value;
              if (p.type === "int") v = parseInt(v, 10) || 0;
              else if (p.type === "float") v = parseFloat(v) || 0;
              params[p.name] = v;
              redraw();
            });
          }
          prow.appendChild(inp);
          pgrid.appendChild(prow);
        });
      } else {
        pgrid.innerHTML = '<div class="hint">No settings.</div>';
      }

      // Answer template — only the LAST node's value is read by the retrieval
      // engine, so flag the active terminal and dim others. Saving still
      // preserves whatever is typed (so reordering doesn't lose work).
      const allNodes = nodesArr();
      const isTerminal = allNodes.length > 0 && allNodes[allNodes.length - 1].name === name;
      const atWrap = document.createElement("div");
      atWrap.className = "answer-template-row";
      atWrap.style.cssText = "margin-top:10px; padding-top:8px; border-top:1px dashed #ccc;";
      const hint = isTerminal
        ? "Answer template (active — sent to agent as answer_instructions on search)"
        : "Answer template (inactive — only the last node's value is read at search time)";
      atWrap.innerHTML = `
        <label style="font-size:9px; display:block; margin-bottom:3px; color:${isTerminal ? '#0a7' : '#888'}">${hint}</label>
        <textarea class="answer-template-input" rows="4"
          style="width:100%; box-sizing:border-box; font-family:inherit; font-size:11px; padding:4px;
                 ${isTerminal ? '' : 'opacity:0.6;'}"
          placeholder="Per-pipeline instructions for the agent (e.g. output format, citation rules)."
        >${(node.answer_template || "").replace(/</g, "&lt;")}</textarea>
      `;
      const atInp = atWrap.querySelector(".answer-template-input");
      bindEditorControl(atInp);
      atInp.addEventListener("input", () => {
        const v = atInp.value;
        if (v) node.answer_template = v;
        else delete node.answer_template;
      });
      entry.appendChild(atWrap);

      body.appendChild(entry);
    });

    // 2. Add module to this stage
    const available = CATALOG.filter(c => c.stage === sid);
    if (available.length) {
      const addCtrl = document.createElement("div");
      addCtrl.className = "add-ctrl";
      const sel = document.createElement("select");
      sel.innerHTML = `<option value="">+ Add module to ${stageLabel}...</option>` +
        available.map(c => `<option value="${c.cls}">${c.name}</option>`).join("");
      bindEditorControl(sel);
      sel.addEventListener("change", () => {
        if (!sel.value) return;
        const comp = available.find(c => c.cls === sel.value);

        let bname = STAGE_DEFAULTS[sid] || sid;
        if (sid === "embed") bname = comp.name.toLowerCase().includes("text") ? "query_embedder" : "embedder";
        if (sid === "retrieve") bname = comp.name.toLowerCase().includes("fts5") ? "fts5" : "vector";
        if (sid === "rerank") bname = "reranker";

        const name = uniqueName(bname);
        const initParams = {};
        for (const p of comp.params) initParams[p.name] = p.default;
        nodesArr().push({ name, module: comp.cls, params: initParams, inputs: [], outputs: [] });
        selectedNode = name;
        redraw();
      });
      addCtrl.appendChild(sel);
      body.appendChild(addCtrl);
    }
  });
}

function uniqueName(base) {
  let n = base;
  let i = 2;
  while (findNode(n)) n = base + "_" + i++;
  return n;
}

function removeNode(name) {
  topo.nodes = nodesArr().filter(n => n.name !== name);
  for (const m of nodesArr()) {
    m.inputs  = (m.inputs  || []).filter(e => !((e.from || "").split(".")[0] === name));
    m.outputs = (m.outputs || []).filter(e => !((e.to   || "").split(".")[0] === name));
  }
  if (selectedNode === name) selectedNode = null;
  redraw();
}

// ---------- load / save ----------
function topoFromJson(j) {
  if (!j || typeof j !== "object") return { nodes: [] };
  return {
    nodes: (j.nodes || []).map(n => {
      const node = {
        name: n.name,
        module: n.module || n.type || n.cls,
        params: { ...(n.params || n.init_parameters || {}) },
        inputs: (n.inputs || []).map(e => ({ port: e.port, from: e.from || e.sender })),
        outputs: (n.outputs || []).map(e => ({ port: e.port, to: e.to || e.receiver })),
      };
      // Preserve answer_template — read by retriever.pipelines.engine on the
      // final search node and forwarded to the agent as answer_instructions.
      if (typeof n.answer_template === "string" && n.answer_template.length > 0) {
        node.answer_template = n.answer_template;
      }
      return node;
    }),
  };
}

async function onLoadPipeline(e) {
  const name = e.target.value;
    if (!name) {
      document.getElementById("pname").value = "";
      document.getElementById("pdesc").value = "";
      topo = { nodes: [] };
      selectedNode = null;
      setStatus("");
      redraw();
    return;
  }
  try {
    const r = await fetch("/api/pipelines/" + encodeURIComponent(name));
    const data = await r.json();
    if (data.error) { setStatus(data.error, "bad"); return; }
    document.getElementById("pname").value = data.name || name;
    document.getElementById("pdesc").value = data.description || "";
    // Built-in pipelines store their graph as `unified_topology`; user pipelines
    // saved through this editor may write indexing/retrieval keys instead.
    const source = data.unified || data.indexing || data.retrieval;
    topo = topoFromJson(source);
    selectedNode = null;
    setStatus("Loaded " + name + " (" + (data.source || "user") + ")", "ok");
    redraw();
  } catch (err) {
    setStatus("load failed: " + err.message, "bad");
  }
}

async function onSave() {
  const name = document.getElementById("pname").value.trim();
  if (!name) { setStatus("Name is required", "bad"); return; }
  const hasComponents = nodesArr().length > 0;
  const payload = {
    name,
    description: document.getElementById("pdesc").value,
    unified_topology: hasComponents ? topo : null,
  };
  try {
    const r = await fetch("/api/pipelines", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (data.error) { setStatus(data.error, "bad"); return; }
    setStatus("Saved " + name, "ok");
    // Refresh dropdown so the new pipeline appears immediately.
    const pipes = await fetch("/api/pipelines").then(r => r.json());
    const sel = document.getElementById("existing");
    const prev = sel.value;
    populatePipelineDropdown(pipes.pipelines || []);
    sel.value = name || prev;
  } catch (err) {
    setStatus("save failed: " + err.message, "bad");
  }
}

// ---------- auto-wire ----------
// Find a sensible connection for each component input by walking earlier stages
// and matching first by exact port name, then by port type. Existing connections
// are left intact.
function autoWire() {
  const t = currentTopo();
  const stageOrder = STAGES.map(s => s[0]);
  const nodes = nodesArr().map(node => {
    const comp = findComp(node.module);
    return { node, comp, stageIdx: comp ? stageOrder.indexOf(comp.stage) : -1 };
  }).filter(n => n.comp);

  const existing = new Set(allConnections().map(e => e.receiver));
  for (const recv of nodes) {
    for (const inp of recv.comp.inputs || []) {
      const target = `${recv.node.name}.${inp.name}`;
      if (existing.has(target)) continue;
      let match = null;
      for (const send of nodes) {
        if (send.node.name === recv.node.name) continue;
        if (send.stageIdx > recv.stageIdx) continue;
        const outByName = (send.comp.outputs || []).find(o => o.name === inp.name);
        if (outByName) { match = `${send.node.name}.${outByName.name}`; break; }
      }
      if (!match) {
        for (const send of nodes) {
          if (send.node.name === recv.node.name) continue;
          if (send.stageIdx > recv.stageIdx) continue;
          const outByType = (send.comp.outputs || []).find(o => o.type === inp.type);
          if (outByType) { match = `${send.node.name}.${outByType.name}`; break; }
        }
      }
      if (match) {
        addConnection(match, target);
        existing.add(target);
      }
    }
  }
  redraw();
}

// ---------- overview / connections / graph ----------
function renderOverview() {
  const box = document.getElementById("overview");
  if (!box) return;
  const compCount = nodesArr().length;
  const connCount = allConnections().length;
  const byStage = {};
  for (const node of nodesArr()) {
    const s = findComp(node.module)?.stage || "?";
    byStage[s] = (byStage[s] || 0) + 1;
  }
  const stageSummary = Object.entries(byStage).map(([s, n]) => `${s}: ${n}`).join(", ") || "no modules";
  box.innerHTML = `<div>Modules: <b>${compCount}</b> &nbsp; Connections: <b>${connCount}</b></div>
                   <div style="color:var(--muted);margin-top:4px;">${stageSummary}</div>`;
}

function renderConnections() {
  const box = document.getElementById("conn-body");
  if (!box) return;
  const connections = allConnections();
  if (!connections.length) {
    box.innerHTML = '<div style="color:var(--muted)">No connections. Add modules and click <b>Auto-wire all ports</b>.</div>';
    return;
  }
  box.innerHTML = "";
  connections.forEach((e) => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px;";
    row.innerHTML = `<span><b>${e.sender}</b> &rarr; <b>${e.receiver}</b></span>
                     <span class="del" style="cursor:pointer;color:var(--bad);">&times;</span>`;
    row.querySelector(".del").addEventListener("click", () => {
      removeConnection(e.sender, e.receiver);
      redraw();
    });
    box.appendChild(row);
  });
}

function renderGraph() {
  const svg = document.getElementById("canvas");
  const empty = document.getElementById("graph-empty");
  if (!svg) return;
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const connections = graphConnections();
  const names = nodeNames();
  const externalNodes = [...new Set(connections.map(e => (e.sender || "").split(".")[0]).filter(n => !findNode(n)))];
  const graphNodes = [...externalNodes, ...names];
  if (!graphNodes.length) { if (empty) empty.style.display = "block"; return; }
  if (empty) empty.style.display = "none";

  if (typeof dagre === "undefined") return;
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", marginx: 20, marginy: 20, nodesep: 30, ranksep: 60 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of graphNodes) g.setNode(n, { label: n, width: 160, height: 50 });
  for (const e of connections) {
    const s = e.sender.split(".")[0];
    const r = e.receiver.split(".")[0];
    if (g.hasNode(s) && g.hasNode(r)) g.setEdge(s, r);
  }
  dagre.layout(g);

  const ns = "http://www.w3.org/2000/svg";
  const w = g.graph().width || 400;
  const h = g.graph().height || 200;
  const pad = 40;
  svg.setAttribute("viewBox", `${-pad} ${-pad} ${w + pad * 2} ${h + pad * 2}`);
  svg.setAttribute("width", w + pad * 2);
  svg.setAttribute("height", h + pad * 2);

  g.edges().forEach(edge => {
    const points = g.edge(edge).points;
    const d = points.map((p, i) => (i === 0 ? "M" : "L") + p.x + "," + p.y).join(" ");
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", "edge-line");
    svg.appendChild(path);
  });

  g.nodes().forEach(n => {
    const node = g.node(n);
    const def = findNode(n);
    const comp = def ? findComp(def.module) : null;
    const isExternal = !def;
    const grp = document.createElementNS(ns, "g");
    grp.setAttribute("transform", `translate(${node.x - node.width / 2}, ${node.y - node.height / 2})`);
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("class", "node-rect" + (isExternal ? " external" : "") + (selectedNode === n ? " selected" : ""));
    rect.setAttribute("width", node.width);
    rect.setAttribute("height", node.height);
    grp.appendChild(rect);
    const title = document.createElementNS(ns, "text");
    title.setAttribute("class", "node-title");
    title.setAttribute("x", 10); title.setAttribute("y", 20);
    title.textContent = n;
    grp.appendChild(title);
    const cls = document.createElementNS(ns, "text");
    cls.setAttribute("class", "node-cls");
    cls.setAttribute("x", 10); cls.setAttribute("y", 38);
    cls.textContent = isExternal ? "runtime entrypoint" : (comp ? comp.name : (def?.module || ""));
    grp.appendChild(cls);
    if (!isExternal) grp.addEventListener("click", () => { selectedNode = n; redraw(); });
    svg.appendChild(grp);
  });
}

// ---------- redraw ----------
function redraw() {
  renderOverview();
  renderStageEditor();
  renderConnections();
  renderGraph();
}

boot();

</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())

