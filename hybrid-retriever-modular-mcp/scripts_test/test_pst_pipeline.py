import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from retriever.config import Config
from retriever.pipelines.indexing import run_indexing
from retriever.pipelines.profiles import get

def test_pst():
    cfg = Config(
        data_root=Path("C:/Users/joung/AppData/Local/Temp/pst_test"),
        default_datasets=["test_pst"]
    )
    cfg.data_root.mkdir(parents=True, exist_ok=True)
    
    # We need a real PST to test pypff. 
    # If one isn't available, we'll just test the component wiring.
    pst_path = "C:/Users/joung/Documents/test.pst" # Adjust if you have a real one
    if not os.path.exists(pst_path):
        print(f"PST not found at {pst_path}, skipping live test")
        return

    profile = get("email")
    result = run_indexing(
        cfg,
        "test_pst",
        pst_path,
        indexing_opts={
            "max_file_chars": 2000000,
            "chunk_chars": 500,
            "chunk_overlap": 50,
            "skip_embedding": True,
            "use_hierarchical": "false"
        },
        builder=profile.build_indexing
    )
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test_pst()
