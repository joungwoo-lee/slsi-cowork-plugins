from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import job_manager
from retriever.config import Config


class JobManagerTest(unittest.TestCase):
    def test_completed_job_persists_result(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            job = job_manager.start_job(
                cfg,
                job_type="test_ok",
                args={"x": 1},
                runner=lambda _job_id: {"ok": True},
            )
            result = self._wait(cfg, job["job_id"])
            self.assertIn("next_step", job)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["result"], {"ok": True})
            self.assertEqual(result["args"], {"x": 1})

    def test_failed_job_persists_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()

            def boom(_job_id: str):
                raise RuntimeError("boom")

            job = job_manager.start_job(
                cfg,
                job_type="test_fail",
                args={},
                runner=boom,
            )
            result = self._wait(cfg, job["job_id"])
            self.assertEqual(result["status"], "failed")
            self.assertIn("boom", result["error"])

    def test_list_jobs_returns_recent_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_root=Path(td))
            cfg.ensure_dirs()
            first = job_manager.start_job(cfg, job_type="a", args={}, runner=lambda _job_id: {"n": 1})
            second = job_manager.start_job(cfg, job_type="b", args={}, runner=lambda _job_id: {"n": 2})
            self._wait(cfg, first["job_id"])
            self._wait(cfg, second["job_id"])
            rows = job_manager.list_jobs(cfg, limit=10, offset=0)
            ids = [row["job_id"] for row in rows]
            self.assertIn(first["job_id"], ids)
            self.assertIn(second["job_id"], ids)

    def _wait(self, cfg: Config, job_id: str) -> dict:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            row = job_manager.get_job(cfg, job_id)
            if row and row["status"] in {"completed", "failed"}:
                return row
            time.sleep(0.05)
        self.fail(f"job did not finish in time: {job_id}")


if __name__ == "__main__":
    unittest.main()
