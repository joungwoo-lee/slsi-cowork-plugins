import json
import subprocess
import sys
import time
from pathlib import Path

def call_tool(process, method, arguments=None):
    request = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
        "method": f"tools/call",
        "params": {
            "name": method,
            "arguments": arguments or {}
        }
    }
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    
    line = process.stdout.readline()
    if not line:
        return {"isError": True, "payload": "No response from server"}
    res = json.loads(line)
    
    content = res.get("result", {}).get("content", [])
    text = "".join([c.get("text", "") for c in content if c.get("type") == "text"])
    is_error = res.get("result", {}).get("isError", False)
    
    try:
        payload = json.loads(text)
    except:
        payload = text
        
    return {"isError": is_error, "payload": payload}

def test_json_pipeline_e2e():
    project_root = Path(__file__).parent.parent
    server_py = project_root / "server.py"
    
    # Setup temp data root
    data_root = Path("C:/Users/joung/AppData/Local/Temp/json_pipeline_test")
    if data_root.exists():
        import shutil
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True)
    
    # Start MCP server
    env = {**dict(subprocess.os.environ), "RETRIEVER_DATA_ROOT": str(data_root)}
    proc = subprocess.Popen(
        ["py", "-3.11", str(server_py)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    
    try:
        print("[1] Saving new pipeline 'json_test'...")
        res = call_tool(proc, "save_pipeline", {
            "name": "json_test",
            "description": "JSON serialized test pipeline",
            "retrieval_overrides": {"fusion": "rrf"},
            "search_kwargs": {"vector_similarity_weight": 0.0}
        })
        assert not res["isError"], res
        print(f"Result: {res['payload']}")
        
        # Verify file exists on disk
        json_path = data_root / "pipelines.json"
        assert json_path.exists()
        print(f"File created: {json_path}")
        
        print("[2] Listing pipelines to verify registration...")
        res = call_tool(proc, "list_pipelines")
        assert not res["isError"], res
        profiles = res["payload"].get("profiles", [])
        profile_names = [p["name"] for p in profiles]
        print(f"Registered profiles: {profile_names}")
        assert "json_test" in profile_names
        
        print("[3] Testing 'json_test' pipeline with search...")
        # First ingest a doc
        call_tool(proc, "create_dataset", {"name": "test_ds"})
        doc_path = data_root / "test.txt"
        doc_path.write_text("This is a test document for JSON pipeline.", encoding="utf-8")
        call_tool(proc, "upload_document", {"dataset_id": "test_ds", "file_path": str(doc_path)})
        
        res = call_tool(proc, "search", {
            "query": "document",
            "dataset_ids": ["test_ds"],
            "pipeline": "json_test"
        })
        assert not res["isError"], res
        assert res["payload"]["total"] > 0
        
        # Check if vector weight was indeed 0 (forced by json_test)
        item = res["payload"]["contexts"][0]["source"]
        print(f"Search result metadata: vector_sim={item.get('vector_similarity')}")
        # In RRF mode with vector_weight=0, vector_similarity should be 0.0
        assert item.get("vector_similarity") == 0.0
        
        print("ALL JSON PIPELINE E2E CHECKS PASSED")

    finally:
        proc.terminate()

if __name__ == "__main__":
    test_json_pipeline_e2e()
