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
    if "error" in res:
        return {"isError": True, "payload": res["error"]}
    
    # MCP tool response is in res["result"]["content"]
    content = res.get("result", {}).get("content", [])
    text = "".join([c.get("text", "") for c in content if c.get("type") == "text"])
    is_error = res.get("result", {}).get("isError", False)
    
    try:
        payload = json.loads(text)
    except:
        payload = text
        
    return {"isError": is_error, "payload": payload}

def test_email_mcp_e2e():
    project_root = Path(__file__).parent.parent
    server_py = project_root / "server.py"
    
    # Setup temp data root
    data_root = Path("C:/Users/joung/AppData/Local/Temp/mcp_email_test_data")
    if data_root.exists():
        import shutil
        shutil.rmtree(data_root)
    data_root.mkdir(parents=True)
    
    # Start MCP server
    env = {**dict(subprocess.os.environ), "RETRIEVER_DATA_ROOT": str(data_root)}
    proc = subprocess.Popen(
        ["py", "-3.12", str(server_py)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )
    
    try:
        print("[1] Initializing dataset...")
        res = call_tool(proc, "create_dataset", {"name": "email_test"})
        assert not res["isError"], res
        
        # Create a dummy email-mcp style directory (since we can't easily create a .pst on the fly without pypff)
        print("[2] Preparing email-mcp style directory...")
        mail_id = "test_mail_123"
        mail_dir = data_root / "inputs" / mail_id
        mail_dir.mkdir(parents=True)
        (mail_dir / "meta.json").write_text(json.dumps({
            "mail_id": mail_id,
            "subject": "E2E MCP Test",
            "sender": "tester@example.com",
            "received": "2026-05-15T12:00:00Z",
            "folder_path": "INBOX"
        }), encoding="utf-8")
        (mail_dir / "body.md").write_text("# E2E MCP Test\n\nThis is a body for MCP verification.", encoding="utf-8")
        
        print("[3] Calling upload_document with pipeline='email'...")
        res = call_tool(proc, "upload_document", {
            "dataset_id": "email_test",
            "file_path": str(mail_dir),
            "pipeline": "email",
            "skip_embedding": True
        })
        
        if res["isError"]:
            print(f"FAILED: {res['payload']}")
            # Read stderr for traceback
            import os
            subprocess.os.set_blocking(proc.stderr.fileno(), False)
            err = proc.stderr.read()
            print(f"Server Traceback:\n{err}")
            return
        
        print(f"SUCCESS: Uploaded chunks={res['payload']['response']['chunks_count']}")
        
        print("[4] Verifying search metadata...")
        # Add a small delay for FTS5 indexing if needed (though SQLite is sync)
        time.sleep(1)
        res = call_tool(proc, "search", {
            "query": "verification",
            "dataset_ids": ["email_test"]
        })
        if res["isError"] or res["payload"]["total"] == 0:
            print(f"Search failed or empty: {res}")
            # Try listing documents to see what's there
            print("Listing documents in email_test:")
            list_res = call_tool(proc, "list_documents", {"dataset_id": "email_test"})
            print(json.dumps(list_res, indent=2))
            return
            
        assert res["payload"]["total"] > 0
        
        ctx = res["payload"]["contexts"][0]
        meta = ctx["source"].get("metadata", {})
        print(f"Metadata found: {json.dumps(meta, indent=2)}")
        
        assert meta.get("subject") == "E2E MCP Test"
        assert meta.get("sender") == "tester@example.com"
        print("ALL E2E CHECKS PASSED")

    finally:
        proc.terminate()

if __name__ == "__main__":
    test_email_mcp_e2e()
