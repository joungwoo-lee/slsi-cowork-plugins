import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .profiles import PipelineProfile, register, get as get_profile
from ..config import Config

logger = logging.getLogger(__name__)

def save_all_profiles(json_path: Path):
    """Save all currently registered profiles to a JSON file."""
    from .profiles import _REGISTRY
    data = {}
    for name, profile in _REGISTRY.items():
        data[name] = {
            "description": profile.description,
            "indexing_overrides": profile.indexing_overrides,
            "retrieval_overrides": profile.retrieval_overrides,
            "search_kwargs": profile.search_kwargs,
        }
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(data)} profiles to {json_path}")

def load_and_register_profiles(json_path: Path):
    """Load profiles from a JSON file and register them."""
    if not json_path.exists():
        return
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        count = 0
        if isinstance(data, dict):
            for name, item in data.items():
                profile = PipelineProfile(
                    name=name,
                    description=item.get("description", ""),
                    indexing_overrides=item.get("indexing_overrides", {}),
                    retrieval_overrides=item.get("retrieval_overrides", {}),
                    search_kwargs=item.get("search_kwargs", {}),
                )
                register(profile)
                count += 1
        logger.info(f"Loaded {count} profiles from {json_path}")
    except Exception as e:
        logger.error(f"Failed to load profiles from {json_path}: {e}")

def export_pipeline_json(pipeline_name: str, cfg: Config, output_path: Path, is_indexing: bool = True):
    """Export a specific Haystack pipeline (topology + state) to JSON."""
    from .indexing import build_indexing_pipeline
    from .retrieval import build_retrieval_pipeline
    from ..hypster_config import select_indexing, select_retrieval
    
    profile = get_profile(pipeline_name)
    
    if is_indexing:
        opts = select_indexing(cfg, profile.indexing_overrides)
        builder = profile.build_indexing or build_indexing_pipeline
        pipeline = builder(cfg, opts)
    else:
        # For retrieval, we don't have per-call opts here, use defaults
        # Retrieval overrides usually apply at run time in our current setup
        builder = profile.build_retrieval or build_retrieval_pipeline
        pipeline = builder(cfg)
        
    # Note: This might still fail if components aren't serializable.
    # We'll try-catch it.
    try:
        json_data = pipeline.dumps()
        output_path.write_text(json_data, encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Failed to export pipeline {pipeline_name} to JSON: {e}")
        return False
