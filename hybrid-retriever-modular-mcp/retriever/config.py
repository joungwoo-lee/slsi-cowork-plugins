"""Local retriever configuration loaded from .env and process env.

Precedence (highest wins):
1. ``.env`` next to the package (``DEFAULT_ENV_PATH``)
2. Process environment variables existing before .env load
3. Hard-coded fallback defaults

We intentionally use ``load_dotenv(..., override=True)`` so editing ``.env``
is the canonical way to change runtime config — stale OS env vars (e.g. an
old ``EMBEDDING_API_KEY`` exported in a parent shell) cannot silently shadow
a fresh ``.env`` value. Any deployment that *needs* OS env to win can
``unset`` the variable in ``.env`` and set it in the process env instead.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = SKILL_ROOT / ".env"
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_LLM_MODEL = "gpt-4o-mini"


def _default_data_root() -> Path:
    """Resolve a platform-appropriate default data directory.

    Honors ``RETRIEVER_DATA_ROOT`` if already in env. Otherwise:
    - Windows: ``%LOCALAPPDATA%\\Retriever_Data`` (or ``~/AppData/Local`` fallback)
    - POSIX:   ``$XDG_DATA_HOME/retriever`` or ``~/.local/share/retriever``
    """
    explicit = os.getenv("RETRIEVER_DATA_ROOT")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Retriever_Data"
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "retriever"


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
    verify_ssl: bool = True

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url) and self.dim > 0


@dataclass
class LLMConfig:
    """Chat-completions LLM endpoint used by Hippo2 OpenIE and query-entity steps."""

    api_url: str
    api_key: str
    model: str
    x_dep_ticket: str = ""
    x_system_name: str = "hybrid-retriever-modular-mcp"
    batch_size: int = 8
    timeout_sec: int = 60
    verify_ssl: bool = True
    temperature: float = 0.0
    max_tokens: int = 1024

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url) and bool(self.model)


@dataclass
class Hippo2Config:
    synonym_threshold: float = 0.85
    synonym_top_k: int = 8
    ppr_alpha: float = 0.85
    ppr_max_iter: int = 50
    ppr_tol: float = 1e-6
    query_top_entities: int = 5
    linking_top_k: int = 5
    passage_node_weight: float = 0.05
    top_chunks: int = 12
    extraction_max_triples: int = 32
    online_filter_enabled: bool = True
    online_filter_candidates: int = 24
    online_filter_min_keep: int = 1


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
    fusion: str = "rrf"
    rrf_k: int = 60
    parent_chunk_replace: bool = True


@dataclass
class Config:
    data_root: Path
    embedding: Optional[EmbeddingConfig] = None
    llm: Optional[LLMConfig] = None
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    hippo2: Hippo2Config = field(default_factory=Hippo2Config)

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


def _int(value: str | None, default: int) -> int:
    if value is None or not str(value).strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float(value: str | None, default: float) -> float:
    if value is None or not str(value).strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def load_config(env_path: str | os.PathLike[str] | None = None) -> Config:
    target = Path(env_path) if env_path else DEFAULT_ENV_PATH
    if target.exists():
        load_dotenv(target, override=False)

    api_url = os.getenv("EMBEDDING_API_URL", "").strip()
    dim = _int(os.getenv("EMBEDDING_DIM"), 0)
    embedding: Optional[EmbeddingConfig] = None
    if api_url and dim > 0:
        embedding = EmbeddingConfig(
            api_url=api_url,
            api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
            model=os.getenv("EMBEDDING_MODEL", "").strip(),
            dim=dim,
            x_dep_ticket=os.getenv("EMBEDDING_API_X_DEP_TICKET", "").strip(),
            x_system_name=os.getenv("EMBEDDING_API_X_SYSTEM_NAME", "hybrid-retriever-modular-mcp").strip(),
            batch_size=_int(os.getenv("EMBEDDING_BATCH_SIZE"), 16),
            timeout_sec=_int(os.getenv("EMBEDDING_TIMEOUT_SEC"), 60),
            verify_ssl=_bool(os.getenv("EMBEDDING_VERIFY_SSL"), True),
        )

    llm_url = os.getenv("LLM_API_URL", "").strip()
    llm_model = os.getenv("LLM_MODEL", "").strip()
    llm_key = os.getenv("LLM_API_KEY", "").strip()
    if not llm_key:
        llm_key = os.getenv("EMBEDDING_API_KEY", "").strip()
    llm_x_dep_ticket = os.getenv("LLM_API_X_DEP_TICKET", "").strip()
    if not llm_x_dep_ticket:
        llm_x_dep_ticket = os.getenv("EMBEDDING_API_X_DEP_TICKET", "").strip()
    llm_x_system_name = os.getenv("LLM_API_X_SYSTEM_NAME", "").strip()
    if not llm_x_system_name:
        llm_x_system_name = os.getenv(
            "EMBEDDING_API_X_SYSTEM_NAME", "hybrid-retriever-modular-mcp"
        ).strip()
    llm_timeout_sec = _int(os.getenv("LLM_TIMEOUT_SEC"), 0) or _int(os.getenv("EMBEDDING_TIMEOUT_SEC"), 60)
    llm_verify_ssl = _bool(
        os.getenv("LLM_VERIFY_SSL") if os.getenv("LLM_VERIFY_SSL") is not None else os.getenv("EMBEDDING_VERIFY_SSL"),
        True,
    )
    if not llm_url and not llm_model and api_url == OPENAI_EMBEDDINGS_URL and llm_key:
        llm_url = OPENAI_CHAT_COMPLETIONS_URL
        llm_model = os.getenv("OPENAI_LLM_MODEL", "").strip() or DEFAULT_OPENAI_LLM_MODEL
    llm: Optional[LLMConfig] = None
    if llm_url and llm_model:
        llm = LLMConfig(
            api_url=llm_url,
            api_key=llm_key,
            model=llm_model,
            x_dep_ticket=llm_x_dep_ticket,
            x_system_name=llm_x_system_name,
            batch_size=_int(os.getenv("LLM_BATCH_SIZE"), 8),
            timeout_sec=llm_timeout_sec,
            verify_ssl=llm_verify_ssl,
            temperature=_float(os.getenv("LLM_TEMPERATURE"), 0.0),
            max_tokens=_int(os.getenv("LLM_MAX_TOKENS"), 1024),
        )

    return Config(
        data_root=_default_data_root(),
        embedding=embedding,
        llm=llm,
        qdrant=QdrantConfig(
            collection=os.getenv("QDRANT_COLLECTION", "retriever_chunks"),
            distance=os.getenv("QDRANT_DISTANCE", "Cosine"),
        ),
        ingest=IngestConfig(
            chunk_chars=_int(os.getenv("RETRIEVER_CHUNK_CHARS"), 512),
            chunk_overlap=_int(os.getenv("RETRIEVER_CHUNK_OVERLAP"), 50),
            max_file_chars=_int(os.getenv("RETRIEVER_MAX_FILE_CHARS"), 2_000_000),
            parent_chunk_chars=_int(os.getenv("PARENT_CHUNK_SIZE"), 1024),
            parent_chunk_overlap=_int(os.getenv("PARENT_CHUNK_OVERLAP"), 100),
            child_chunk_chars=_int(os.getenv("CHILD_CHUNK_SIZE"), 256),
            child_chunk_overlap=_int(os.getenv("CHILD_CHUNK_OVERLAP"), 50),
        ),
        search=SearchConfig(
            hybrid_alpha=_float(os.getenv("HYBRID_ALPHA"), 0.5),
            fusion=os.getenv("RETRIEVER_FUSION", "rrf").strip().lower(),
            rrf_k=_int(os.getenv("RRF_K"), 60),
            parent_chunk_replace=_bool(os.getenv("ENABLE_PARENT_CHILD_CHUNKING"), True),
        ),
        hippo2=Hippo2Config(
            synonym_threshold=_float(os.getenv("HIPPO2_SYNONYM_THRESHOLD"), 0.85),
            synonym_top_k=_int(os.getenv("HIPPO2_SYNONYM_TOP_K"), 8),
            ppr_alpha=_float(os.getenv("HIPPO2_PPR_ALPHA"), 0.85),
            ppr_max_iter=_int(os.getenv("HIPPO2_PPR_MAX_ITER"), 50),
            ppr_tol=_float(os.getenv("HIPPO2_PPR_TOL"), 1e-6),
            query_top_entities=_int(os.getenv("HIPPO2_QUERY_TOP_ENTITIES"), 5),
            linking_top_k=_int(os.getenv("HIPPO2_LINKING_TOP_K"), 5),
            passage_node_weight=_float(os.getenv("HIPPO2_PASSAGE_NODE_WEIGHT"), 0.05),
            top_chunks=_int(os.getenv("HIPPO2_TOP_CHUNKS"), 12),
            extraction_max_triples=_int(os.getenv("HIPPO2_EXTRACTION_MAX_TRIPLES"), 32),
            online_filter_enabled=_bool(os.getenv("HIPPO2_ONLINE_FILTER_ENABLED"), True),
            online_filter_candidates=_int(os.getenv("HIPPO2_ONLINE_FILTER_CANDIDATES"), 24),
            online_filter_min_keep=_int(os.getenv("HIPPO2_ONLINE_FILTER_MIN_KEEP"), 1),
        ),
    )
