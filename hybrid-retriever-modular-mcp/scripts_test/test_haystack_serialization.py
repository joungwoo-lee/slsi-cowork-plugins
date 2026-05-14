import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from retriever.config import Config, load_config
from retriever.pipelines.indexing import build_indexing_pipeline
from retriever.pipelines.retrieval import build_retrieval_pipeline
from retriever.hypster_config import select_indexing, select_retrieval

def test_serialization():
    cfg = load_config()
    cfg.data_root = Path("C:/Users/joung/AppData/Local/Temp/serialize_test")
    
    # 1. Test Retrieval Pipeline
    retrieval_pipe = build_retrieval_pipeline(cfg)
    try:
        # Haystack 2.x native serialization
        retrieval_json = retrieval_pipe.dumps()
        print("Retrieval pipeline serialized successfully.")
        
        # Verify it can be loaded back
        from haystack import Pipeline
        reloaded = Pipeline.loads(retrieval_json)
        print("Retrieval pipeline de-serialized successfully.")
    except Exception as e:
        print(f"Retrieval serialization failed: {e}")
        import traceback
        traceback.print_exc()

    # 2. Test Indexing Pipeline
    # Indexing pipeline depends on opts, so we pick a default set
    opts = select_indexing(cfg, {"use_hierarchical": "false"})
    indexing_pipe = build_indexing_pipeline(cfg, opts)
    try:
        indexing_json = indexing_pipe.dumps()
        print("Indexing pipeline serialized successfully.")
        
        reloaded_idx = Pipeline.loads(indexing_json)
        print("Indexing pipeline de-serialized successfully.")
    except Exception as e:
        print(f"Indexing serialization failed: {e}")

if __name__ == "__main__":
    test_serialization()
