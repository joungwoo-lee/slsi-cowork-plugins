"""Local web UI for editing hybrid-retriever pipelines.

Run:  py -3.11 pipeline_editor.py

Opens http://127.0.0.1:8765 in the default browser. The page lists the
component catalogue on the left (grouped by pipeline stage), lets you
configure each component's constructor parameters, define connections
between them, and shows the resulting DAG as an SVG graph on the right.

Saving writes:
  * pipelines/<name>_indexing.json (or _retrieval.json) — Haystack topology
  * $RETRIEVER_DATA_ROOT/pipelines.json — profile entry that points to it,
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
        "name": "HybridJoiner",
        "cls": "retriever.components.hybrid_joiner.HybridJoiner",
        "stage": "fuse",
        "params": [],
        "inputs": [
            {"name": "keyword_documents", "type": "List[Document]"},
            {"name": "semantic_documents", "type": "List[Document]"},
            {"name": "fusion", "type": "str"},
            {"name": "vector_weight", "type": "float"},
            {"name": "rrf_k", "type": "int"},
            {"name": "metadata_condition", "type": "dict"},
        ],
        "outputs": [{"name": "documents", "type": "List[Document]"}],
    },
    {
        "name": "ParentChunkReplacer",
        "cls": "retriever.components.parent_replace.ParentChunkReplacer",
        "stage": "post",
        "params": [],
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
    ("post", "Post-process"),
]


# --- Disk I/O ---------------------------------------------------------------

def _read_json(path: Path) -> dict:
    return editor_store.read_json(path)


def _atomic_write_json(path: Path, data: dict) -> None:
    editor_store.atomic_write_json(path, data)


def load_pipeline_list() -> list[dict]:
    """Return one entry per known pipeline (registry.json + user pipelines.json)."""
    out: dict[str, dict] = {}
    for name, item in _read_json(REGISTRY_PATH).items():
        if isinstance(item, dict):
            out[name] = {**item, "name": name, "source": "builtin"}
    for name, item in _read_json(USER_PROFILES_PATH).items():
        if isinstance(item, dict):
            out[name] = {**item, "name": name, "source": "user"}
    return list(out.values())


def load_pipeline_detail(name: str) -> dict:
    """Return profile metadata + the two topology JSON blobs (if any)."""
    profile: dict | None = None
    for entry in load_pipeline_list():
        if entry["name"] == name:
            profile = entry
            break
    if profile is None:
        return {"error": f"pipeline not found: {name}"}

    topo_indexing = profile.get("indexing_topology")
    topo_retrieval = profile.get("retrieval_topology")
    out = dict(profile)
    out["indexing"] = _read_json(PIPELINES_DIR / topo_indexing) if topo_indexing else None
    out["retrieval"] = _read_json(PIPELINES_DIR / topo_retrieval) if topo_retrieval else None
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

#app { display: grid; grid-template-columns: 380px 1fr; height: 100vh; }
#left { background: var(--panel); border-right: 1px solid var(--border); overflow-y: auto; padding: 12px; }
#right { display: flex; flex-direction: column; }
#topbar {
  display: flex; gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--border);
  background: var(--panel); align-items: center;
}
#topbar h1 { margin: 0; font-size: 14px; font-weight: 600; }
#topbar .spacer { flex: 1; }
#status { font-size: 11px; color: var(--muted); margin-left: 8px; }
#status.ok { color: var(--ok); }
#status.bad { color: var(--bad); }

#graph { flex: 1; position: relative; overflow: auto; background: #0b0d12; }
#graph svg { display: block; }
.node-rect { fill: var(--panel); stroke: var(--border); stroke-width: 1.2; rx: 8; ry: 8; cursor: pointer; }
.node-rect.selected { stroke: var(--accent); stroke-width: 2; }
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

.stage-group { margin-bottom: 8px; }
.stage-group .stage-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 4px 2px; }
.comp-card {
  display: flex; justify-content: space-between; align-items: center;
  background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
  padding: 6px 8px; margin-bottom: 4px; cursor: pointer;
}
.comp-card:hover { border-color: var(--accent); }
.comp-card .nm { font-weight: 600; }
.comp-card .add { font-size: 11px; color: var(--accent); }
.comp-card .stage-pill {
  display: inline-block; margin-top: 4px; font-size: 10px; color: #0b1220; background: var(--accent);
  border-radius: 999px; padding: 2px 6px; font-weight: 600;
}

.node-list .row {
  display: flex; justify-content: space-between; align-items: center;
  padding: 5px 6px; border-radius: 5px; cursor: pointer;
}
.node-list .row:hover { background: var(--panel); }
.node-list .row.selected { background: rgba(90,169,255,0.12); }
.node-list .row .nm { font-weight: 600; }
.node-list .row .cls { color: var(--muted); font-size: 10px; }
.node-list .row .del { color: var(--bad); font-size: 11px; opacity: 0.7; }
.node-list .row .del:hover { opacity: 1; }

.param-row { margin-bottom: 8px; }
.param-row .type { font-size: 10px; color: var(--muted); margin-left: 4px; }
.param-row .help { margin-top: 4px; color: var(--muted); font-size: 10px; }

.conn-row { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; align-items: center; margin-bottom: 4px; }
.conn-row .arrow { color: var(--muted); }
.conn-row .del { color: var(--bad); cursor: pointer; padding: 2px 6px; }

.tabs { display: flex; gap: 4px; margin-bottom: 8px; }
.tabs .tab {
  padding: 5px 10px; background: var(--panel); border: 1px solid var(--border);
  border-radius: 5px; cursor: pointer; font-size: 12px;
}
.tabs .tab.active { background: var(--accent); color: #0b1220; border-color: var(--accent); font-weight: 600; }

.hint { font-size: 11px; color: var(--muted); padding: 4px 0; }
.overview-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.metric { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
.metric .v { font-size: 18px; font-weight: 700; }
.metric .k { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.graph-empty {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  color: var(--muted); font-size: 14px; pointer-events: none;
}
</style>
</head>
<body>
<div id="app">
  <div id="left">
    <div class="section">
      <div class="head">Pipeline</div>
      <div class="body">
        <div class="param-row">
          <label>Existing</label>
          <select id="existing"><option value="">— new pipeline —</option></select>
        </div>
        <div class="param-row">
          <label>Name</label>
          <input id="pname" placeholder="my_pipeline">
        </div>
        <div class="param-row">
          <label>Description</label>
          <textarea id="pdesc" rows="2"></textarea>
        </div>
        <div class="tabs">
          <div class="tab active" data-kind="indexing">Indexing</div>
          <div class="tab" data-kind="retrieval">Retrieval</div>
        </div>
        <div class="hint" id="kind-hint"></div>
      </div>
    </div>

    <div class="section">
      <div class="head">Overview</div>
      <div class="body overview-grid" id="overview"></div>
    </div>

    <div class="section">
      <div class="head">Add module</div>
      <div class="body" id="catalog"></div>
    </div>

    <div class="section">
      <div class="head">Modules on graph</div>
      <div class="body node-list" id="node-list"></div>
    </div>

    <div class="section" id="config-section" style="display:none">
      <div class="head" id="config-head">Module settings</div>
      <div class="body" id="config-body"></div>
    </div>

    <div class="section">
      <div class="head">Connections</div>
      <div class="body" id="conn-body"></div>
    </div>

    <div class="section">
      <div class="head">Overrides &amp; search_kwargs</div>
      <div class="body">
        <label>indexing_overrides (JSON)</label>
        <textarea id="ovr-idx" rows="2">{}</textarea>
        <label style="margin-top:6px">retrieval_overrides (JSON)</label>
        <textarea id="ovr-ret" rows="2">{}</textarea>
        <label style="margin-top:6px">search_kwargs (JSON)</label>
        <textarea id="ovr-sk" rows="2">{}</textarea>
      </div>
    </div>
  </div>

  <div id="right">
    <div id="topbar">
      <h1>Retriever Pipeline Editor</h1>
      <span id="status"></span>
      <div class="spacer"></div>
      <button id="auto-wire">Auto-wire</button>
      <button id="reset">Reset</button>
      <button class="primary" id="save">Save pipeline</button>
    </div>
    <div id="graph"><div class="graph-empty" id="graph-empty">Add modules on the left to start building the pipeline graph.</div><svg id="canvas" width="100%" height="100%"></svg></div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script>
// ---------- state ----------
let CATALOG = [];
let STAGES = [];
let kind = "indexing";  // or "retrieval"
let topo = { indexing: emptyTopo(), retrieval: emptyTopo() };
let selectedNode = null;
let counter = 0;

function emptyTopo() { return { components: {}, connections: [] }; }
function currentTopo() { return topo[kind]; }
function findComp(cls) { return CATALOG.find(c => c.cls === cls); }

// ---------- bootstrap ----------
async function boot() {
  const [cat, pipes] = await Promise.all([
    fetch("/api/catalog").then(r => r.json()),
    fetch("/api/pipelines").then(r => r.json()),
  ]);
  CATALOG = cat.components;
  STAGES = cat.stages;
  renderCatalog();
  const sel = document.getElementById("existing");
  for (const p of pipes.pipelines) {
    const o = document.createElement("option");
    o.value = p.name; o.textContent = p.name + " (" + p.source + ")";
    sel.appendChild(o);
  }
  sel.addEventListener("change", onLoadPipeline);
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    kind = t.dataset.kind;
    selectedNode = null;
    redraw();
  }));
  document.getElementById("save").addEventListener("click", onSave);
  document.getElementById("reset").addEventListener("click", () => { topo[kind] = emptyTopo(); selectedNode = null; redraw(); });
  document.getElementById("auto-wire").addEventListener("click", autoWire);
  redraw();
}

// ---------- catalog UI ----------
function renderCatalog() {
  const box = document.getElementById("catalog");
  box.innerHTML = "";
  for (const [stage, label] of STAGES) {
    const comps = CATALOG.filter(c => c.stage === stage);
    if (!comps.length) continue;
    const group = document.createElement("div");
    group.className = "stage-group";
    group.innerHTML = `<div class="stage-label">${label}</div>`;
    for (const c of comps) {
      const row = document.createElement("div");
      row.className = "comp-card";
      row.innerHTML = `<div><div class="nm">${c.name}</div><div class="cls" style="font-size:10px;color:var(--muted)">${c.cls}</div><div class="stage-pill">${label}</div></div><div class="add">+ add</div>`;
      row.addEventListener("click", () => addNode(c));
      group.appendChild(row);
    }
    box.appendChild(group);
  }
}

function uniqueName(base) {
  let n = base;
  let i = 2;
  while (currentTopo().components[n]) n = base + "_" + i++;
  return n;
}

function addNode(comp) {
  const t = currentTopo();
  const base = comp.name.replace(/^Http|Local/g, "").replace(/^[A-Z]/, c => c.toLowerCase()).replace(/[A-Z]/g, m => "_" + m.toLowerCase());
  const name = uniqueName(base.replace(/^_/, ""));
  const initParams = {};
  for (const p of comp.params) initParams[p.name] = p.default;
  t.components[name] = { type: comp.cls, init_parameters: initParams };
  selectedNode = name;
  redraw();
}

function removeNode(name) {
  const t = currentTopo();
  delete t.components[name];
  t.connections = t.connections.filter(e => !e.sender.startsWith(name + ".") && !e.receiver.startsWith(name + "."));
  if (selectedNode === name) selectedNode = null;
  redraw();
}

// ---------- node list + config ----------
function renderNodeList() {
  const box = document.getElementById("node-list");
  box.innerHTML = "";
  const t = currentTopo();
  for (const [name, def] of Object.entries(t.components)) {
    const comp = findComp(def.type);
    const row = document.createElement("div");
    row.className = "row" + (selectedNode === name ? " selected" : "");
    row.innerHTML = `<div><div class="nm">${name}</div><div class="cls">${comp ? comp.name : def.type}</div></div><div class="del">✕</div>`;
    row.addEventListener("click", e => {
      if (e.target.classList.contains("del")) { removeNode(name); return; }
      selectedNode = name; redraw();
    });
    box.appendChild(row);
  }
  if (Object.keys(t.components).length === 0) {
    box.innerHTML = `<div class="hint">No modules yet. Pick one above.</div>`;
  }
}

function renderConfig() {
  const sec = document.getElementById("config-section");
  const head = document.getElementById("config-head");
  const body = document.getElementById("config-body");
  if (!selectedNode) { sec.style.display = "none"; return; }
  const t = currentTopo();
  const def = t.components[selectedNode];
  if (!def) { sec.style.display = "none"; return; }
  const comp = findComp(def.type);
  sec.style.display = "";
  head.textContent = selectedNode + "  ·  " + (comp ? comp.name : def.type);
  body.innerHTML = "";

  // Rename
  const renameRow = document.createElement("div");
  renameRow.className = "param-row";
  renameRow.innerHTML = `<label>node name</label>`;
  const nameInp = document.createElement("input");
  nameInp.value = selectedNode;
  nameInp.addEventListener("change", () => {
    const newName = nameInp.value.trim();
    if (!newName || newName === selectedNode || t.components[newName]) { nameInp.value = selectedNode; return; }
    t.components[newName] = t.components[selectedNode];
    delete t.components[selectedNode];
    t.connections = t.connections.map(e => ({
      sender: e.sender.startsWith(selectedNode + ".") ? newName + e.sender.slice(selectedNode.length) : e.sender,
      receiver: e.receiver.startsWith(selectedNode + ".") ? newName + e.receiver.slice(selectedNode.length) : e.receiver,
    }));
    selectedNode = newName;
    redraw();
  });
  renameRow.appendChild(nameInp);
  const renameHelp = document.createElement("div");
  renameHelp.className = "help";
  renameHelp.textContent = "Node names become connection endpoints like loader.text or joiner.documents.";
  renameRow.appendChild(renameHelp);
  body.appendChild(renameRow);

  if (!comp || !comp.params.length) {
    body.appendChild(hint("No constructor parameters."));
    return;
  }
  for (const p of comp.params) {
    const row = document.createElement("div");
    row.className = "param-row";
    row.innerHTML = `<label>${p.name}<span class="type">${p.type}</span></label>`;
    let inp;
    if (p.type === "bool") {
      inp = document.createElement("select");
      inp.innerHTML = `<option value="false">false</option><option value="true">true</option>`;
      inp.value = String(def.init_parameters[p.name] ?? p.default);
      inp.addEventListener("change", () => { def.init_parameters[p.name] = inp.value === "true"; });
    } else {
      inp = document.createElement("input");
      inp.value = def.init_parameters[p.name] ?? p.default ?? "";
      inp.addEventListener("change", () => {
        let v = inp.value;
        if (p.type === "int") v = parseInt(v, 10) || 0;
        else if (p.type === "float") v = parseFloat(v) || 0;
        def.init_parameters[p.name] = v;
      });
    }
    row.appendChild(inp);
    body.appendChild(row);
  }
}

function hint(text) {
  const d = document.createElement("div");
  d.className = "hint"; d.textContent = text; return d;
}

// ---------- connections UI ----------
function renderConnections() {
  const box = document.getElementById("conn-body");
  box.innerHTML = "";
  const t = currentTopo();
  for (let i = 0; i < t.connections.length; i++) {
    const e = t.connections[i];
    const row = document.createElement("div");
    row.className = "conn-row";
    row.innerHTML = `<div>${e.sender}</div><div>→ ${e.receiver}</div><div class="del">✕</div>`;
    row.querySelector(".del").addEventListener("click", () => { t.connections.splice(i, 1); redraw(); });
    box.appendChild(row);
  }

  // Adder
  const adder = document.createElement("div");
  adder.style.marginTop = "8px";
  adder.innerHTML = `
    <label>Add connection</label>
    <div class="conn-row">
      <select id="add-from"></select>
      <select id="add-to"></select>
      <button id="add-btn">+</button>
    </div>
    <div class="hint" id="conn-hint">Choose an output port → input port</div>
  `;
  box.appendChild(adder);

  const fromSel = adder.querySelector("#add-from");
  const toSel = adder.querySelector("#add-to");
  for (const [name, def] of Object.entries(t.components)) {
    const comp = findComp(def.type);
    if (!comp) continue;
    for (const o of comp.outputs) {
      const opt = document.createElement("option");
      opt.value = `${name}.${o.name}`;
      opt.textContent = `${name}.${o.name}  (${o.type})`;
      opt.dataset.type = o.type;
      fromSel.appendChild(opt);
    }
    for (const i of comp.inputs) {
      const opt = document.createElement("option");
      opt.value = `${name}.${i.name}`;
      opt.textContent = `${name}.${i.name}  (${i.type})`;
      opt.dataset.type = i.type;
      toSel.appendChild(opt);
    }
  }
  const hintEl = adder.querySelector("#conn-hint");
  function checkTypes() {
    const a = fromSel.selectedOptions[0]?.dataset.type;
    const b = toSel.selectedOptions[0]?.dataset.type;
    if (!a || !b) { hintEl.textContent = ""; return; }
    if (a === b || a === "Any" || b === "Any") {
      hintEl.style.color = "var(--ok)"; hintEl.textContent = "Types match.";
    } else {
      hintEl.style.color = "var(--warn)"; hintEl.textContent = `Type mismatch: ${a} → ${b}`;
    }
  }
  fromSel.addEventListener("change", checkTypes); toSel.addEventListener("change", checkTypes);
  checkTypes();
  adder.querySelector("#add-btn").addEventListener("click", () => {
    if (!fromSel.value || !toSel.value) return;
    if (t.connections.some(e => e.sender === fromSel.value && e.receiver === toSel.value)) return;
    t.connections.push({ sender: fromSel.value, receiver: toSel.value });
    redraw();
  });
}

function renderOverview() {
  const box = document.getElementById("overview");
  const t = currentTopo();
  const nodeCount = Object.keys(t.components).length;
  const edgeCount = t.connections.length;
  const stages = new Set();
  for (const def of Object.values(t.components)) {
    const comp = findComp(def.type);
    if (comp) stages.add(comp.stage);
  }
  box.innerHTML = `
    <div class="metric"><div class="v">${nodeCount}</div><div class="k">Modules</div></div>
    <div class="metric"><div class="v">${edgeCount}</div><div class="k">Connections</div></div>
    <div class="metric"><div class="v">${stages.size}</div><div class="k">Stages used</div></div>
  `;
}

// ---------- auto-wire ----------
// Connects compatible output→input ports by greedy type match.
function autoWire() {
  const t = currentTopo();
  const nodes = Object.entries(t.components);
  const made = new Set(t.connections.map(e => e.sender + "|" + e.receiver));
  for (const [an, ad] of nodes) {
    const aComp = findComp(ad.type); if (!aComp) continue;
    for (const out of aComp.outputs) {
      for (const [bn, bd] of nodes) {
        if (bn === an) continue;
        const bComp = findComp(bd.type); if (!bComp) continue;
        for (const inp of bComp.inputs) {
          if (inp.name !== out.name) continue;          // match by name first
          if (inp.type !== out.type && inp.type !== "Any" && out.type !== "Any") continue;
          const key = `${an}.${out.name}|${bn}.${inp.name}`;
          if (made.has(key)) continue;
          // skip if this input port already has a sender
          if (t.connections.some(e => e.receiver === `${bn}.${inp.name}`)) continue;
          t.connections.push({ sender: `${an}.${out.name}`, receiver: `${bn}.${inp.name}` });
          made.add(key);
        }
      }
    }
  }
  redraw();
}

// ---------- graph rendering (dagre + SVG) ----------
function renderGraph() {
  const svg = document.getElementById("canvas");
  const empty = document.getElementById("graph-empty");
  svg.innerHTML = "";
  const t = currentTopo();
  const entries = Object.entries(t.components);
  if (!entries.length) {
    empty.style.display = "flex";
    svg.setAttribute("viewBox", "0 0 800 400");
    return;
  }
  empty.style.display = "none";

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 30, ranksep: 60, marginx: 30, marginy: 30 });
  g.setDefaultEdgeLabel(() => ({}));

  const NODE_W = 200;
  for (const [name, def] of entries) {
    const comp = findComp(def.type);
    const inN = comp ? comp.inputs.length : 0;
    const outN = comp ? comp.outputs.length : 0;
    const h = 50 + Math.max(inN, outN) * 14;
    g.setNode(name, { width: NODE_W, height: h, comp, def, name });
  }
  for (const e of t.connections) {
    const s = e.sender.split(".")[0], r = e.receiver.split(".")[0];
    if (g.hasNode(s) && g.hasNode(r)) g.setEdge(s, r, e);
  }
  dagre.layout(g);

  const w = g.graph().width || 800;
  const h = g.graph().height || 400;
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("width", w);
  svg.setAttribute("height", h);

  // edges
  for (const eid of g.edges()) {
    const edge = g.edge(eid);
    const pts = edge.points;
    const d = pts.map((p, i) => (i === 0 ? "M" : "L") + p.x + "," + p.y).join(" ");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    path.setAttribute("class", "edge-line");
    path.setAttribute("marker-end", "url(#arrow)");
    svg.appendChild(path);
  }

  // marker
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.innerHTML = `<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 Z" fill="#4a5470"/></marker>`;
  svg.appendChild(defs);

  // nodes
  for (const name of g.nodes()) {
    const n = g.node(name);
    const x = n.x - n.width / 2, y = n.y - n.height / 2;
    const grp = document.createElementNS("http://www.w3.org/2000/svg", "g");
    grp.setAttribute("transform", `translate(${x},${y})`);
    grp.addEventListener("click", () => { selectedNode = name; redraw(); });

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", n.width); rect.setAttribute("height", n.height);
    rect.setAttribute("class", "node-rect" + (selectedNode === name ? " selected" : ""));
    grp.appendChild(rect);

    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("class", "node-title"); title.setAttribute("x", 10); title.setAttribute("y", 18);
    title.textContent = name; grp.appendChild(title);

    const cls = document.createElementNS("http://www.w3.org/2000/svg", "text");
    cls.setAttribute("class", "node-cls"); cls.setAttribute("x", 10); cls.setAttribute("y", 32);
    cls.textContent = n.comp ? n.comp.name : n.def.type;
    grp.appendChild(cls);

    // ports
    if (n.comp) {
      n.comp.inputs.forEach((p, i) => {
        const py = 45 + i * 14;
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("cx", 0); dot.setAttribute("cy", py); dot.setAttribute("class", "port-dot in"); dot.setAttribute("r", 3.5);
        grp.appendChild(dot);
        const lbl = document.createElementNS("http://www.w3.org/2000/svg", "text");
        lbl.setAttribute("class", "port-text"); lbl.setAttribute("x", 8); lbl.setAttribute("y", py + 3);
        lbl.textContent = p.name; grp.appendChild(lbl);
      });
      n.comp.outputs.forEach((p, i) => {
        const py = 45 + i * 14;
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("cx", n.width); dot.setAttribute("cy", py); dot.setAttribute("class", "port-dot out"); dot.setAttribute("r", 3.5);
        grp.appendChild(dot);
        const lbl = document.createElementNS("http://www.w3.org/2000/svg", "text");
        lbl.setAttribute("class", "port-text"); lbl.setAttribute("text-anchor", "end");
        lbl.setAttribute("x", n.width - 8); lbl.setAttribute("y", py + 3);
        lbl.textContent = p.name; grp.appendChild(lbl);
      });
    }
    svg.appendChild(grp);
  }
}

// ---------- load / save ----------
async function onLoadPipeline(e) {
  const name = e.target.value;
  if (!name) {
    document.getElementById("pname").value = "";
    document.getElementById("pdesc").value = "";
    topo = { indexing: emptyTopo(), retrieval: emptyTopo() };
    selectedNode = null; setStatus(""); redraw(); return;
  }
  const r = await fetch("/api/pipelines/" + encodeURIComponent(name));
  const data = await r.json();
  if (data.error) { setStatus(data.error, "bad"); return; }
  document.getElementById("pname").value = data.name;
  document.getElementById("pdesc").value = data.description || "";
  document.getElementById("ovr-idx").value = JSON.stringify(data.indexing_overrides || {}, null, 2);
  document.getElementById("ovr-ret").value = JSON.stringify(data.retrieval_overrides || {}, null, 2);
  document.getElementById("ovr-sk").value = JSON.stringify(data.search_kwargs || {}, null, 2);
  topo.indexing = data.indexing ? topoFromJson(data.indexing) : emptyTopo();
  topo.retrieval = data.retrieval ? topoFromJson(data.retrieval) : emptyTopo();
  selectedNode = null;
  setStatus("Loaded " + name + " (" + data.source + ")", "ok");
  redraw();
}

function topoFromJson(j) {
  return {
    components: j.components || {},
    connections: (j.connections || []).map(e => ({ sender: e.sender, receiver: e.receiver })),
  };
}

function safeJson(s) { try { const v = JSON.parse(s); return (v && typeof v === "object") ? v : {}; } catch { return null; } }

async function onSave() {
  const name = document.getElementById("pname").value.trim();
  if (!name) { setStatus("Name is required", "bad"); return; }
  const ovrIdx = safeJson(document.getElementById("ovr-idx").value);
  const ovrRet = safeJson(document.getElementById("ovr-ret").value);
  const sk = safeJson(document.getElementById("ovr-sk").value);
  if (ovrIdx === null || ovrRet === null || sk === null) { setStatus("Override JSON invalid", "bad"); return; }

  const payload = {
    name,
    description: document.getElementById("pdesc").value,
    indexing_overrides: ovrIdx,
    retrieval_overrides: ovrRet,
    search_kwargs: sk,
    indexing_topology: Object.keys(topo.indexing.components).length ? topo.indexing : null,
    retrieval_topology: Object.keys(topo.retrieval.components).length ? topo.retrieval : null,
  };
  const r = await fetch("/api/pipelines", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload) });
  const data = await r.json();
  if (data.error) { setStatus(data.error, "bad"); return; }
  setStatus("Saved → " + (data.indexing_topology || data.retrieval_topology || data.profile_path), "ok");
}

function setStatus(text, cls) {
  const s = document.getElementById("status");
  s.textContent = text; s.className = cls || "";
}

// ---------- redraw ----------
function redraw() {
  document.getElementById("kind-hint").textContent =
    kind === "indexing"
      ? "Indexing pipeline: load → split → embed → write."
      : "Retrieval pipeline: query_embedder + fts5 → joiner → parent.";
  renderOverview();
  renderNodeList();
  renderConfig();
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
