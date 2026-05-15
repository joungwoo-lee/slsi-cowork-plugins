"""Tests for retriever.config — env override semantics + Optional embedding."""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.config import EmbeddingConfig, load_config
from retriever import storage


_ENV_KEYS = (
    "RETRIEVER_DATA_ROOT", "RETRIEVER_DEFAULT_DATASETS",
    "EMBEDDING_API_URL", "EMBEDDING_API_KEY", "EMBEDDING_MODEL", "EMBEDDING_DIM",
    "EMBEDDING_VERIFY_SSL", "EMBEDDING_BATCH_SIZE", "EMBEDDING_TIMEOUT_SEC",
    "LLM_API_URL", "LLM_API_KEY", "LLM_MODEL", "OPENAI_LLM_MODEL",
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

    def test_shell_env_wins_over_dotenv(self) -> None:
        """Shell environment variables should take precedence over .env."""
        os.environ["EMBEDDING_API_KEY"] = "shell-key"
        self.env_path.write_text(
            "EMBEDDING_API_URL=https://example.test/embed\n"
            "EMBEDDING_API_KEY=dotenv-key\n"
            "EMBEDDING_MODEL=test-model\n"
            "EMBEDDING_DIM=8\n",
            encoding="utf-8",
        )
        cfg = load_config(self.env_path)
        self.assertIsNotNone(cfg.embedding)
        assert cfg.embedding is not None
        self.assertEqual(cfg.embedding.api_key, "shell-key")
        self.assertEqual(cfg.embedding.dim, 8)

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

    def test_llm_falls_back_to_openai_embedding_key_and_defaults(self) -> None:
        self.env_path.write_text(
            "EMBEDDING_API_URL=https://api.openai.com/v1/embeddings\n"
            "EMBEDDING_API_KEY=embed-key\n"
            "EMBEDDING_MODEL=text-embedding-3-small\n"
            "EMBEDDING_DIM=1536\n",
            encoding="utf-8",
        )
        cfg = load_config(self.env_path)
        self.assertIsNotNone(cfg.llm)
        assert cfg.llm is not None
        self.assertEqual(cfg.llm.api_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(cfg.llm.api_key, "embed-key")
        self.assertEqual(cfg.llm.model, "gpt-4o-mini")

    def test_explicit_llm_key_still_wins(self) -> None:
        self.env_path.write_text(
            "EMBEDDING_API_URL=https://api.openai.com/v1/embeddings\n"
            "EMBEDDING_API_KEY=embed-key\n"
            "EMBEDDING_MODEL=text-embedding-3-small\n"
            "EMBEDDING_DIM=1536\n"
            "LLM_API_URL=https://example.test/chat\n"
            "LLM_MODEL=custom-mini\n"
            "LLM_API_KEY=llm-key\n",
            encoding="utf-8",
        )
        cfg = load_config(self.env_path)
        self.assertIsNotNone(cfg.llm)
        assert cfg.llm is not None
        self.assertEqual(cfg.llm.api_url, "https://example.test/chat")
        self.assertEqual(cfg.llm.api_key, "llm-key")
        self.assertEqual(cfg.llm.model, "custom-mini")


class EmbeddingConfigTest(unittest.TestCase):
    def test_is_configured(self) -> None:
        self.assertTrue(EmbeddingConfig(api_url="x", api_key="", model="m", dim=8).is_configured)
        self.assertFalse(EmbeddingConfig(api_url="", api_key="", model="m", dim=8).is_configured)
        self.assertFalse(EmbeddingConfig(api_url="x", api_key="", model="m", dim=0).is_configured)


class SqliteThreadingTest(unittest.TestCase):
    def test_sqlite_session_connection_is_cross_thread_usable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="retriever_cfg_thread_") as td:
            env_path = Path(td) / ".env"
            env_path.write_text("", encoding="utf-8")
            cfg = load_config(env_path)
            cfg.data_root = Path(td) / "data"
            errors: list[Exception] = []
            with storage.sqlite_session(cfg) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS t(x INTEGER)")

                def worker() -> None:
                    try:
                        conn.execute("INSERT INTO t(x) VALUES(1)")
                    except Exception as exc:  # noqa: BLE001
                        errors.append(exc)

                t = threading.Thread(target=worker)
                t.start()
                t.join()
                self.assertFalse(errors, errors)


if __name__ == "__main__":
    unittest.main()
