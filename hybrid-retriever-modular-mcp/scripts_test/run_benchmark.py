"""Run benchmark_pipelines MCP tool directly."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault(
    "RETRIEVER_DATA_ROOT",
    r"C:\Users\joung\slsi-cowork-plugins\hybrid-retriever-modular-mcp\data",
)

from mcp_server.handlers import tool_benchmark_pipelines
from mcp_server.job_manager import get_job
from retriever.config import load_config

# 1. Start benchmark asynchronously
result = tool_benchmark_pipelines({
    "pipelines": ["default", "keyword_only"],
    "dataset_id_prefix": "beir_nf",
    "top_n": 10,
    "cleanup": True,
    "async": True,
})

job_info = json.loads(result["content"][0]["text"])
job_id = job_info["job_id"]
print(f"Started job {job_id}. Polling for completion...")

cfg = load_config()

# 2. Poll job status
while True:
    job = get_job(cfg, job_id)
    if not job:
        print("Job not found!")
        break
    
    status = job.get("status")
    prog = job.get("progress", 0)
    msg = job.get("message", "")
    
    print(f"Status: {status} | Progress: {prog}% | {msg}")
    
    if status == "completed":
        print("\n--- Benchmark Completed! ---")
        
        result_data = job.get("result", {})
        report_md = result_data.get("markdown", "")
        summary = result_data.get("summary", {})
        
        print("\n" + report_md)
        print("\n=== JSON summary ===")
        print(json.dumps(summary, indent=2))
        
        with open("benchmark_report.md", "w", encoding="utf-8") as f:
            f.write(report_md)
        break
        
    elif status == "failed":
        print(f"\nBenchmark Failed: {job.get('error')}")
        break
        
    time.sleep(5)


