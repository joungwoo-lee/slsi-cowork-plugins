"""Config loader and path helpers for email-connector."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EmbeddingConfig:
    endpoint: str
    api_key: str
    model: str
    dim: int
    batch_size: int = 16
    timeout_sec: int = 60


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


def load_config(path: str | os.PathLike[str]) -> Config:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    emb = raw["embedding"]
    return Config(
        data_root=Path(raw.get("data_root", r"C:\Outlook_Data")),
        embedding=EmbeddingConfig(
            endpoint=emb["endpoint"],
            api_key=emb["api_key"],
            model=emb["model"],
            dim=int(emb["dim"]),
            batch_size=int(emb.get("batch_size", 16)),
            timeout_sec=int(emb.get("timeout_sec", 60)),
        ),
        qdrant=QdrantConfig(**raw.get("qdrant", {})),
        ingest=IngestConfig(**raw.get("ingest", {})),
        search=SearchConfig(**raw.get("search", {})),
    )
