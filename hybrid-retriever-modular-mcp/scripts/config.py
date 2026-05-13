"""Local retriever configuration loaded from .env and process env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = SKILL_ROOT / ".env"


@dataclass
class EmbeddingConfig:
    api_url: str
    api_key: str
    model: str
    dim: int
    x_dep_ticket: str = ""
    x_system_name: str = "hybrid-retriever-modular-mcp"
    batch_size: int = 16
    timeout_sec: int = 60
    verify_ssl: bool = False


@dataclass
class QdrantConfig:
    collection: str = "retriever_chunks"
    distance: str = "Cosine"


@dataclass
class IngestConfig:
    chunk_chars: int = 512
    chunk_overlap: int = 50
    max_file_chars: int = 2_000_000
    parent_chunk_chars: int = 1024
    parent_chunk_overlap: int = 100
    child_chunk_chars: int = 256
    child_chunk_overlap: int = 50


@dataclass
class SearchConfig:
    hybrid_alpha: float = 0.5
    fusion: str = "linear"
    rrf_k: int = 60
    parent_chunk_replace: bool = True


@dataclass
class Config:
    data_root: Path
    embedding: EmbeddingConfig
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    search: SearchConfig = field(default_factory=SearchConfig)

    @property
    def files_root(self) -> Path:
        return self.data_root / "Files"

    @property
    def db_path(self) -> Path:
        return self.data_root / "metadata.db"

    @property
    def vector_db_path(self) -> Path:
        return self.data_root / "VectorDB"

    def dataset_dir(self, dataset_id: str) -> Path:
        return self.files_root / dataset_id

    def document_dir(self, dataset_id: str, document_id: str) -> Path:
        return self.dataset_dir(dataset_id) / document_id

    def content_path(self, dataset_id: str, document_id: str) -> Path:
        return self.document_dir(dataset_id, document_id) / "content.txt"

    def source_path(self, dataset_id: str, document_id: str, filename: str) -> Path:
        return self.document_dir(dataset_id, document_id) / filename

    def ensure_dirs(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        self.vector_db_path.mkdir(parents=True, exist_ok=True)


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config(env_path: str | os.PathLike[str] | None = None) -> Config:
    target = Path(env_path) if env_path else DEFAULT_ENV_PATH
    if target.exists():
        load_dotenv(target, override=False)

    return Config(
        data_root=Path(os.getenv("RETRIEVER_DATA_ROOT", r"C:\Retriever_Data")),
        embedding=EmbeddingConfig(
            api_url=os.getenv("EMBEDDING_API_URL", "").strip(),
            api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
            model=os.getenv("EMBEDDING_MODEL", "").strip(),
            dim=int(os.getenv("EMBEDDING_DIM", "0") or "0"),
            x_dep_ticket=os.getenv("EMBEDDING_API_X_DEP_TICKET", "").strip(),
            x_system_name=os.getenv("EMBEDDING_API_X_SYSTEM_NAME", "hybrid-retriever-modular-mcp").strip(),
            batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
            timeout_sec=int(os.getenv("EMBEDDING_TIMEOUT_SEC", "60")),
            verify_ssl=_bool(os.getenv("EMBEDDING_VERIFY_SSL"), False),
        ),
        qdrant=QdrantConfig(
            collection=os.getenv("QDRANT_COLLECTION", "retriever_chunks"),
            distance=os.getenv("QDRANT_DISTANCE", "Cosine"),
        ),
        ingest=IngestConfig(
            chunk_chars=int(os.getenv("RETRIEVER_CHUNK_CHARS", "512")),
            chunk_overlap=int(os.getenv("RETRIEVER_CHUNK_OVERLAP", "50")),
            max_file_chars=int(os.getenv("RETRIEVER_MAX_FILE_CHARS", "2000000")),
            parent_chunk_chars=int(os.getenv("PARENT_CHUNK_SIZE", "1024")),
            parent_chunk_overlap=int(os.getenv("PARENT_CHUNK_OVERLAP", "100")),
            child_chunk_chars=int(os.getenv("CHILD_CHUNK_SIZE", "256")),
            child_chunk_overlap=int(os.getenv("CHILD_CHUNK_OVERLAP", "50")),
        ),
        search=SearchConfig(
            hybrid_alpha=float(os.getenv("HYBRID_ALPHA", "0.5")),
            fusion=os.getenv("RETRIEVER_FUSION", "linear").strip().lower(),
            rrf_k=int(os.getenv("RRF_K", "60")),
            parent_chunk_replace=_bool(os.getenv("ENABLE_PARENT_CHILD_CHUNKING"), True),
        ),
    )
