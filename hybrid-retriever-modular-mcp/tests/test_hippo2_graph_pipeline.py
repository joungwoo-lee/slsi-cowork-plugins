import unittest
import tempfile
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock FlagEmbedding before any imports that might use it
mock_flag_embedding = MagicMock()
sys.modules["FlagEmbedding"] = mock_flag_embedding

from retriever.config import Config, EmbeddingConfig, Hippo2Config
from retriever.pipelines import profiles, run_retrieval

class TestHippo2GraphPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp_dir.name)
        self.cfg = Config(data_root=self.data_root)
        self.cfg.ensure_dirs()
        # Mock embedding config
        self.cfg.embedding = EmbeddingConfig(api_url="http://fake", api_key="key", model="fake", dim=4)
        self.cfg.hippo2 = Hippo2Config()
        
        # Setup mock flag reranker
        mock_flag_embedding.FlagReranker.return_value.compute_score.return_value = [0.95]

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("retriever.hippo2.query.search")
    @patch("retriever.components.fts5_retriever.storage.fts_search")
    @patch("retriever.components.fts5_retriever.storage.fetch_chunks")
    @patch("retriever.components.vector_retriever.storage.vector_search")
    @patch("retriever.components.vector_retriever.storage.open_qdrant")
    @patch("retriever.components.vector_retriever.storage.ensure_collection")
    @patch("retriever.components.document_embedder.EmbeddingClient")
    @patch("retriever.components.graph_retriever.graph.open_graph")
    def test_pipeline_execution(self, mock_graph, mock_emb_client, mock_ensure, mock_qdrant, mock_vsearch, mock_fetch_chunks, mock_fts_search, mock_hippo_search):
        # Mock FTS
        mock_fts_search.return_value = [{"chunk_id": "c1", "score": 10.0}]
        mock_fetch_chunks.return_value = {
            "c1": {"chunk_id": "c1", "content": "text1", "dataset_id": "d", "document_id": "doc1", "document_name": "n1", "position": 0}
        }
        
        # Mock Vector
        mock_vsearch.return_value = [{"chunk_id": "c1", "score": 0.8}]
        mock_emb_client.return_value.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
        
        # Mock Hippo2
        hippo_result = MagicMock()
        hippo_result.chunks = [{"chunk_id": "c1", "content": "text1", "dataset_id": "d", "document_id": "doc1", "document_name": "n1", "position": 0, "score": 0.9}]
        mock_hippo_search.return_value = hippo_result
        
        # Mock Graph
        mock_graph.return_value.execute.return_value.has_next.return_value = False

        # Run retrieval using the new profile
        profile = profiles.get("hippo2_graph_rrf")
        
        from retriever.hypster_config import select_retrieval
        opts = select_retrieval(self.cfg, profile.retrieval_overrides)
        
        result = run_retrieval(
            self.cfg,
            "query",
            ["demo"],
            retrieval_opts=opts,
            profile=profile
        )
        
        self.assertIn("items", result)
        self.assertTrue(len(result["items"]) > 0)
        self.assertEqual(result["items"][0]["chunk_id"], "c1")
        # Check that we got results fused from multiple sources (via similarity score)
        self.assertGreater(result["items"][0]["similarity"], 0)

if __name__ == "__main__":
    unittest.main()
