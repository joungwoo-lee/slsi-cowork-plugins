"""Tests for retriever.config — env override semantics + Optional embedding."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.config import EmbeddingConfig, load_config


_ENV_KEYS = (
    "RETRIEVER_DATA_ROOT", "RETRIEVER_DEFAULT_DATASETS",
    "EMBEDDING_API_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL", "EMBEDDING_DIM",
    "EMBEDDING_VERIFY_SSL", "EMBEDDING_BATCH_SIZE", "EMBEDDING_TIMEOUT_SEC",
    "RETRIEVER_CHUNK_CHARS", "HYBRID_ALPHA", "RETRIEVER_FUSION", "RRF_K",
)


def _snapshot_env() -> dict[str, str | None]:
    return {k: os.environ.get(k) for k in _ENV_KEYS}


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class ConfigLoadTest(unittest.TestCase):
    def setUp(self) -> None:
        self._snapshot = _snapshot_env()
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        self._tmpdir = tempfile.mkdtemp(prefix="retriever_cfg_")
        self.env_path = Path(self._tmpdir) / ".env"

    def tearDown(self) -> None:
        _restore_env(self._snapshot)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_dotenv_overrides_existing_os_env(self) -> None:
        """The whole reason override=True exists: stale OS env must lose."""
        os.environ["EMBEDDING_API_KEY"] = "stale-key"
        self.env_path.write_text(
            "EMBEDDING_API_URL=https://example.test/embed\n"
            "EMBEDDING_API_KEY=fresh-key\n"
            "EMBEDDING_MODEL=test-model\n"
            "EMBEDDING_DIM=8\n",
            encoding="utf-8",
        )
        cfg = load_config(self.env_path)
        self.assertIsNotNone(cfg.embedding)
        assert cfg.embedding is not None
        self.assertEqual(cfg.embedding.api_key, "fresh-key")
        self.assertEqual(cfg.embedding.dim, 8)
        self.assertTrue(cfg.embedding.verify_ssl)
        self.assertTrue(cfg.embedding.is_configured)

    def test_embedding_optional_when_unconfigured(self) -> None:
        # No EMBEDDING_API_URL -> embedding stays None, search degrades to FTS5
        self.env_path.write_text("RETRIEVER_DEFAULT_DATASETS=foo\n", encoding="utf-8")
        cfg = load_config(self.env_path)
        self.assertIsNone(cfg.embedding)

    def test_platform_default_data_root(self) -> None:
        self.env_path.write_text("", encoding="utf-8")
        cfg = load_config(self.env_path)
        # Default must be absolute, exist or be creatable, and not the legacy
        # hardcoded C:\Retriever_Data.
        self.assertTrue(cfg.data_root.is_absolute(), cfg.data_root)
        self.assertNotEqual(str(cfg.data_root).lower(), r"c:\retriever_data".lower())

    def test_verify_ssl_default_true(self) -> None:
        self.env_path.write_text(
            "EMBEDDING_API_URL=https://example.test/embed\n"
            "EMBEDDING_DIM=4\n",
            encoding="utf-8",
        )
        cfg = load_config(self.env_path)
        assert cfg.embedding is not None
        self.assertTrue(cfg.embedding.verify_ssl)

    def test_invalid_int_falls_back_to_default(self) -> None:
        self.env_path.write_text(
            "RETRIEVER_CHUNK_CHARS=notanint\n", encoding="utf-8"
        )
        cfg = load_config(self.env_path)
        self.assertEqual(cfg.ingest.chunk_chars, 512)


class EmbeddingConfigTest(unittest.TestCase):
    def test_is_configured(self) -> None:
        self.assertTrue(EmbeddingConfig(api_url="x", api_key="", model="m", dim=8).is_configured)
        self.assertFalse(EmbeddingConfig(api_url="", api_key="", model="m", dim=8).is_configured)
        self.assertFalse(EmbeddingConfig(api_url="x", api_key="", model="m", dim=0).is_configured)


if __name__ == "__main__":
    unittest.main()
