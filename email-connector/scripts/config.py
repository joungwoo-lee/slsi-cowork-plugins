"""Config loaded from a .env file (python-dotenv) — drop-in compatible with the
retriever_engine project's environment variable names."""
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
    x_system_name: str = "email-connector"
    batch_size: int = 16
    timeout_sec: int = 60
    # Minimum spacing between batch calls (seconds). Mirrors the
    # retriever_engine upload script's `time.sleep(1)` rate-limit guard:
    # one batch per second is the sustained pace embedding endpoints
    # in our environments tolerate without 429.
    min_interval_sec: float = 1.0
    # SSL cert verification is OFF by default to accommodate corporate
    # MITM proxies / private CAs. Set EMBEDDING_VERIFY_SSL=true in .env to
    # enforce strict verification (e.g. against api.openai.com).
    verify_ssl: bool = False


@dataclass
class QdrantConfig:
    collection: str = "emails"
    distance: str = "Cosine"


@dataclass
class IngestConfig:
    max_attachment_chars: int = 200000
    max_body_chars: int = 200000


@dataclass
class SearchConfig:
    hybrid_alpha: float = 0.5


@dataclass
class Config:
    data_root: Path
    pst_path: str
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

    def mail_dir(self, mail_id: str) -> Path:
        return self.files_root / mail_id

    def attachments_dir(self, mail_id: str) -> Path:
        return self.mail_dir(mail_id) / "attachments"

    def body_md_path(self, mail_id: str) -> Path:
        return self.mail_dir(mail_id) / "body.md"

    def ensure_dirs(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.files_root.mkdir(parents=True, exist_ok=True)
        self.vector_db_path.mkdir(parents=True, exist_ok=True)


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config(env_path: str | os.PathLike[str] | None = None) -> Config:
    """Load .env (default <skill_root>/.env) into the Config dataclass.

    Pre-existing process env vars take precedence over .env values, so a user
    can override anything via shell env without editing the file.
    """
    target = Path(env_path) if env_path else DEFAULT_ENV_PATH
    if target.exists():
        load_dotenv(target, override=False)

    return Config(
        data_root=Path(os.getenv("DATA_ROOT", r"C:\Outlook_Data")),
        pst_path=os.getenv("PST_PATH", "").strip(),
        embedding=EmbeddingConfig(
            api_url=os.getenv("EMBEDDING_API_URL", "").strip(),
            api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
            model=os.getenv("EMBEDDING_MODEL", "").strip(),
            dim=int(os.getenv("EMBEDDING_DIM", "0") or "0"),
            x_dep_ticket=os.getenv("EMBEDDING_API_X_DEP_TICKET", "").strip(),
            x_system_name=os.getenv("EMBEDDING_API_X_SYSTEM_NAME", "email-connector").strip(),
            batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "16")),
            timeout_sec=int(os.getenv("EMBEDDING_TIMEOUT_SEC", "60")),
            min_interval_sec=float(os.getenv("EMBEDDING_MIN_INTERVAL_SEC", "1.0")),
            verify_ssl=_bool(os.getenv("EMBEDDING_VERIFY_SSL"), False),
        ),
        qdrant=QdrantConfig(
            collection=os.getenv("QDRANT_COLLECTION", "emails"),
            distance=os.getenv("QDRANT_DISTANCE", "Cosine"),
        ),
        ingest=IngestConfig(
            max_attachment_chars=int(os.getenv("MAX_ATTACHMENT_CHARS", "200000")),
            max_body_chars=int(os.getenv("MAX_BODY_CHARS", "200000")),
        ),
        search=SearchConfig(
            hybrid_alpha=float(os.getenv("HYBRID_ALPHA", "0.5")),
        ),
    )
