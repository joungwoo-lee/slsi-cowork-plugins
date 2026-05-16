"""Run benchmark_pipelines MCP tool directly."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault(
    "RETRIEVER_DATA_ROOT",
    r"C:\Users\joung\slsi-cowork-plugins\hybrid-retriever-modular-mcp\data",
)

from mcp_server.handlers import tool_benchmark_pipelines

result = tool_benchmark_pipelines({
    "pipelines": ["default", "keyword_only"],
    "dataset_id_prefix": "bm",
    "top_n": 5,
    "cleanup": True,
})

body = json.loads(result["content"][0]["text"])
print(body["markdown"])
print()
print("=== JSON summary ===")
print(json.dumps(body["summary"], indent=2))
