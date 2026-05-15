"""Local web UI for editing hybrid-retriever pipelines.

Run:  py -3.12 pipeline_editor.py

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

#app { display: flex; flex-direction: column; height: 100vh; background: var(--bg); }
#main-container { flex: 1; overflow-y: auto; display: flex; justify-content: center; padding: 20px; }
#settings-panel { width: 100%; max-width: 700px; }

#right { 
  display: none; 
  position: fixed; 
  inset: 0; 
  background: var(--bg); 
  z-index: 2000; 
  flex-direction: column; 
}
#right.open { display: flex; }

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
    <button id="view-graph-btn" class="primary">View Graph</button>
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
        </div>
      </div>

      <div class="section">
        <div class="head">Pipeline Configuration (Stages 1-8)</div>
        <div class="body">
          <div class="hint">Define the complete flow from ingestion to search.</div>
          <div id="dynamic-steps"></div>
        </div>
      </div>

      <div class="section">
        <div class="head">Advanced: JSON Overrides</div>
        <div class="body">
          <label>indexing_overrides</label>
          <textarea id="ovr-idx" rows="2">{}</textarea>
          <label style="margin-top:6px">retrieval_overrides</label>
          <textarea id="ovr-ret" rows="2">{}</textarea>
          <label style="margin-top:6px">search_kwargs</label>
          <textarea id="ovr-sk" rows="2">{}</textarea>
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
  </div>

  <div id="right">
    <div id="graph-topbar">
      <h1>Pipeline Graph</h1>
      <div class="spacer"></div>
      <button id="close-graph-btn">Close Graph</button>
    </div>
    <div id="graph"><div class="graph-empty" id="graph-empty">Add modules on the left to start building the pipeline graph.</div><svg id="canvas" width="100%" height="100%"></svg></div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script>
// ---------- state ----------
let CATALOG = [];
let STAGES = [];
let topo = { components: {}, connections: [] };
let selectedNode = null;
let counter = 0;

function currentTopo() { return topo; }
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
  document.getElementById("save").addEventListener("click", onSave);
  document.getElementById("reset-btn").addEventListener("click", () => { topo = { components: {}, connections: [] }; selectedNode = null; redraw(); });
  document.getElementById("auto-wire").addEventListener("click", autoWire);
  document.getElementById("view-graph-btn").addEventListener("click", () => { document.getElementById("right").classList.add("open"); redraw(); });
  document.getElementById("close-graph-btn").addEventListener("click", () => { document.getElementById("right").classList.remove("open"); });
  redraw();
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
  const t = currentTopo();

  const activeStages = ["load", "convert", "split", "embed", "write", "retrieve", "fuse", "post"];

  activeStages.forEach((sid, idx) => {
    const stageLabel = STAGES.find(s => s[0] === sid)?.[1] || sid;
    const section = document.createElement("div");
    section.className = "section";
    const pathLabel = sid === "load" || sid === "convert" || sid === "split" || sid === "write" ? " (Indexing Path)" : 
                     (sid === "retrieve" || sid === "fuse" || sid === "post" ? " (Retrieval Path)" : " (Shared Path)");
    
    section.innerHTML = `
      <div class="head">Step ${idx + 2}: ${stageLabel}${pathLabel}</div>
      <div class="body" id="stage-body-${sid}"></div>
    `;
    container.appendChild(section);
    const body = section.querySelector(".body");

    // 1. Existing modules in this stage
    const nodes = Object.entries(t.components).filter(([_, def]) => findComp(def.type)?.stage === sid);
    nodes.forEach(([name, def]) => {
      const comp = findComp(def.type);
      const entry = document.createElement("div");
      entry.className = "module-entry" + (selectedNode === name ? " selected" : "");
      entry.innerHTML = `
        <div class="hdr">
          <div class="nm">${name}</div>
          <div class="del" title="Remove">✕</div>
        </div>
        <div class="cls">${comp ? comp.name : def.type}</div>
        
        <div class="p-row" style="margin: 8px 0;">
          <label style="font-size:9px">node name</label>
          <input type="text" value="${name}" class="node-rename-input" style="font-size:11px; padding:2px 6px; height:22px;">
        </div>

        <div class="params-grid" id="pgrid-${name}"></div>
      `;

      // Rename logic
      const renameInp = entry.querySelector(".node-rename-input");
      renameInp.addEventListener("change", () => {
        const newName = renameInp.value.trim();
        if (!newName || newName === name || t.components[newName]) { renameInp.value = name; return; }
        t.components[newName] = t.components[name];
        delete t.components[name];
        t.connections = t.connections.map(e => ({
          sender: e.sender.startsWith(name + ".") ? newName + e.sender.slice(name.length) : e.sender,
          receiver: e.receiver.startsWith(name + ".") ? newName + e.receiver.slice(name.length) : e.receiver,
        }));
        selectedNode = newName;
        redraw();
      });

      entry.querySelector(".del").addEventListener("click", (e) => { e.stopPropagation(); removeNode(name); });
      entry.addEventListener("click", () => { selectedNode = name; redraw(); });

      // Parameters
      const pgrid = entry.querySelector(".params-grid");
      if (comp && comp.params.length) {
        comp.params.forEach(p => {
          const prow = document.createElement("div");
          prow.className = "p-row";
          prow.innerHTML = `<label>${p.name}</label>`;
          let inp;
          if (p.type === "bool") {
            inp = document.createElement("select");
            inp.innerHTML = `<option value="false">false</option><option value="true">true</option>`;
            inp.value = String(def.init_parameters[p.name] ?? p.default);
            inp.addEventListener("change", () => { def.init_parameters[p.name] = inp.value === "true"; redraw(); });
          } else {
            inp = document.createElement("input");
            inp.value = def.init_parameters[p.name] ?? p.default ?? "";
            inp.addEventListener("change", () => {
              let v = inp.value;
              if (p.type === "int") v = parseInt(v, 10) || 0;
              else if (p.type === "float") v = parseFloat(v) || 0;
              def.init_parameters[p.name] = v;
              redraw();
            });
          }
          prow.appendChild(inp);
          pgrid.appendChild(prow);
        });
      } else {
        pgrid.innerHTML = '<div class="hint">No settings.</div>';
      }
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
      sel.addEventListener("change", () => {
        if (!sel.value) return;
        const comp = available.find(c => c.cls === sel.value);
        
        // Suggest standard name
        let bname = STAGE_DEFAULTS[sid] || sid;
        if (sid === "embed") {
            bname = comp.name.toLowerCase().includes("text") ? "query_embedder" : "embedder";
        }
        if (sid === "retrieve") bname = comp.name.toLowerCase().includes("fts5") ? "fts5" : "vector";
        
        const name = uniqueName(bname);
        const initParams = {};
        for (const p of comp.params) initParams[p.name] = p.default;
        t.components[name] = { type: comp.cls, init_parameters: initParams };
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
