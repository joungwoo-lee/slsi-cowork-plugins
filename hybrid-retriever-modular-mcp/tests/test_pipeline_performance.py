"""Pipeline performance benchmark: ingestion, search speed, and accuracy comparison."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server import handlers
from retriever import storage
from retriever.config import Config


def _payload(tool_result: dict) -> dict:
    text = tool_result["content"][0]["text"]
    return json.loads(text)


SAMPLE_DOCS = {
    "doc1.txt": "Python is a programming language. It is widely used for web development and data science.",
    "doc2.txt": "Machine learning is a subset of artificial intelligence. Deep learning uses neural networks.",
    "doc3.txt": "JavaScript runs in web browsers. React is a popular JavaScript framework for UI development.",
    "doc4.txt": "Database systems store data. SQL is used to query relational databases.",
    "doc5.txt": "Cloud computing provides on-demand resources. AWS and Azure are major cloud providers.",
    "doc6.txt": "DevOps practices improve software delivery. CI/CD pipelines automate testing and deployment.",
    "doc7.txt": "API design is crucial for backend services. REST and GraphQL are popular API styles.",
    "doc8.txt": "Security is important for applications. Encryption protects sensitive data.",
    "doc9.txt": "Version control systems track code changes. Git is the most popular version control tool.",
    "doc10.txt": "Testing ensures code quality. Unit tests, integration tests, and E2E tests are common types.",
}

TEST_QUERIES = [
    "What is machine learning?",
    "JavaScript and React development",
    "Database and SQL",
    "Cloud computing platforms",
    "Python programming",
]

PIPELINES = [
    "default",
    "keyword_only",
    "hippo2",
    "rrf_rerank",
    "rrf_llm_rerank",
    "rrf_graph_rerank",
    "hippo2_graph_rrf",
]


class PipelinePerformanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self._tmp.name)
        self.cfg = Config(data_root=self.data_root)
        self.cfg.ensure_dirs()

        self._old_load_config = handlers.load_config
        self._old_data_root_env = os.environ.get("RETRIEVER_DATA_ROOT")
        os.environ["RETRIEVER_DATA_ROOT"] = str(self.cfg.data_root)
        handlers.load_config = lambda: self.cfg

        self.results = {}

    def tearDown(self) -> None:
        handlers.load_config = self._old_load_config
        if self._old_data_root_env is None:
            os.environ.pop("RETRIEVER_DATA_ROOT", None)
        else:
            os.environ["RETRIEVER_DATA_ROOT"] = self._old_data_root_env
        self._tmp.cleanup()

    def test_pipeline_performance_comparison(self) -> None:
        """Test and compare performance metrics across all pipelines."""
        for pipeline in PIPELINES:
            dataset_id = f"perf_test_{pipeline}"
            self._run_pipeline_benchmark(dataset_id, pipeline)

        self._print_results()

    def _run_pipeline_benchmark(self, dataset_id: str, pipeline: str) -> None:
        """Run ingestion and search benchmark for a single pipeline."""
        # Skip pipelines requiring external APIs
        if pipeline in ["rrf_rerank", "rrf_llm_rerank", "rrf_graph_rerank", "hippo2_graph_rrf"]:
            print(f"\n⊘ Skipping {pipeline} (requires external APIs or dependencies)")
            self.results[pipeline] = {"status": "skipped"}
            return

        print(f"\n{'='*60}")
        print(f"Testing Pipeline: {pipeline}")
        print(f"{'='*60}")

        # Create dataset
        with storage.sqlite_session(self.cfg) as conn:
            storage.ensure_dataset(conn, dataset_id, pipeline)
            storage.update_dataset_metadata(
                conn, dataset_id, {"preferred_search_pipeline": pipeline}
            )

        # Create temp docs
        docs_dir = self.data_root / f"docs_{pipeline}"
        docs_dir.mkdir(exist_ok=True, parents=True)
        for filename, content in SAMPLE_DOCS.items():
            (docs_dir / filename).write_text(content)

        # 1. Measure ingestion time
        print(f"Ingesting {len(SAMPLE_DOCS)} documents...")
        ingest_start = time.time()

        try:
            result = handlers.tool_upload(
                {
                    "dataset_id": dataset_id,
                    "path": str(docs_dir),
                    "pipeline": pipeline,
                    "async": False,
                }
            )
            ingest_time = time.time() - ingest_start
            print(f"✓ Completed in {ingest_time:.3f}s")
        except Exception as e:
            print(f"✗ Failed: {str(e)[:100]}")
            self.results[pipeline] = {"status": "failed", "error": str(e)[:100]}
            return

        # 2. Measure search time and collect results
        print(f"Searching ({len(TEST_QUERIES)} queries)...")
        search_times = []
        total_results = 0

        for query in TEST_QUERIES:
            search_start = time.time()
            try:
                result = handlers.tool_search(
                    {
                        "query": query,
                        "dataset_ids": [dataset_id],
                        "pipeline": pipeline,
                        "top_n": 5,
                    }
                )
                search_time = time.time() - search_start
                search_times.append(search_time)

                body = _payload(result)
                contexts = body.get("contexts", [])
                total_results += len(contexts)
            except Exception as e:
                print(f"  ⚠ Query failed: {str(e)[:80]}")

        if not search_times:
            print("✗ No successful searches")
            self.results[pipeline] = {"status": "failed", "error": "no successful searches"}
            return

        avg_search_time = sum(search_times) / len(search_times)

        self.results[pipeline] = {
            "ingest_time": ingest_time,
            "avg_search_time": avg_search_time,
            "total_results": total_results,
        }

        print(f"✓ Avg search: {avg_search_time:.3f}s, {total_results} results across queries")

    def _print_results(self) -> None:
        """Print performance comparison table."""
        if not self.results:
            print("No results to display")
            return

        print("\n" + "="*80)
        print("PIPELINE PERFORMANCE COMPARISON")
        print("="*80)
        print(f"{'Pipeline':<20} {'Ingestion (s)':<15} {'Avg Search (s)':<15} {'Status':<15}")
        print("-"*80)

        for pipeline, metrics in self.results.items():
            status = metrics.get("status", "")

            if status == "skipped":
                print(f"{pipeline:<20} {'—':<15} {'—':<15} {'SKIPPED':<15}")
            elif status == "failed":
                error = metrics.get("error", "unknown")[:30]
                print(f"{pipeline:<20} {'—':<15} {'—':<15} {f'FAILED: {error}':<15}")
            else:
                ingest = metrics.get("ingest_time")
                search = metrics.get("avg_search_time")

                ingest_str = f"{ingest:.3f}" if ingest else "ERROR"
                search_str = f"{search:.3f}" if search else "ERROR"

                print(f"{pipeline:<20} {ingest_str:<15} {search_str:<15} {'✓':<15}")

        print("="*80)


if __name__ == "__main__":
    unittest.main()
