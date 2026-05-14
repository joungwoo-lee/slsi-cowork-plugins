import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from haystack import Pipeline

# Import components so Haystack can find them during de-serialization
from retriever import components

def convert_to_json():
    pipelines_dir = Path("retriever/pipelines")
    for p in pipelines_dir.glob("*.json"):
        if p.name == "registry.json":
            continue
        print(f"Converting {p} to JSON...")
        content = p.read_text(encoding="utf-8")
        try:
            # Load (handles YAML/JSON)
            pipe = Pipeline.loads(content)
            # Dump to dict and then JSON
            p.write_text(json.dumps(pipe.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"Failed to convert {p}: {e}")

if __name__ == "__main__":
    convert_to_json()
