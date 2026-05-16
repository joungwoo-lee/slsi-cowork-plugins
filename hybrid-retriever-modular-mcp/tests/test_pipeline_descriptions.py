"""Description lives on each topology JSON, not in registry.json.

Covers the three call sites that need to round-trip a pipeline description:
- ``editor_store.save_pipeline_payload`` writes it into topology metadata
- ``pipeline_editor.load_pipeline_list`` reads it back when the profile omits it
- ``mcp_server.catalog.build_tools`` exposes the per-pipeline blurbs on the
  ``search`` tool's ``pipeline`` parameter so an agent can route without first
  calling ``list_pipelines``.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline_editor
from retriever.pipelines import editor_store


class SavePipelineWritesDescriptionToTopologyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="pipeline_desc_"))
        self.pipelines_dir = self.tmpdir / "pipelines"
        self.profiles_path = self.tmpdir / "data" / "pipelines.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _save(self, payload: dict) -> dict:
        return editor_store.save_pipeline_payload(
            payload,
            pipelines_dir=self.pipelines_dir,
            profiles_path=self.profiles_path,
        )

    def test_description_lands_in_unified_topology_metadata(self) -> None:
        result = self._save({
            "name": "demo",
            "description": "Use when: routing test",
            "unified_topology": {
                "nodes": [{"name": "loader", "module": "x.Y", "params": {}}],
            },
        })
        self.assertEqual(result["status"], "ok")

        topology = json.loads((self.pipelines_dir / "demo_unified.json").read_text("utf-8"))
        self.assertEqual(topology["metadata"]["description"], "Use when: routing test")

        profile = json.loads(self.profiles_path.read_text("utf-8"))["demo"]
        # Description should not be duplicated onto the profile when the
        # topology already carries it.
        self.assertNotIn("description", profile)

    def test_description_lands_in_split_topologies(self) -> None:
        self._save({
            "name": "split",
            "description": "Use when: ingest != retrieve",
            "indexing_topology": {
                "nodes": [{"name": "loader", "module": "x.Y", "params": {}}],
            },
            "retrieval_topology": {
                "nodes": [{"name": "fts5", "module": "x.Z", "params": {}}],
            },
        })
        idx = json.loads((self.pipelines_dir / "split_indexing.json").read_text("utf-8"))
        ret = json.loads((self.pipelines_dir / "split_retrieval.json").read_text("utf-8"))
        self.assertEqual(idx["metadata"]["description"], "Use when: ingest != retrieve")
        self.assertEqual(ret["metadata"]["description"], "Use when: ingest != retrieve")

    def test_description_preserved_on_profile_when_no_topology(self) -> None:
        """Override-only profiles have no topology to host the description, so it
        falls back to the profile entry — otherwise it would be lost."""
        self._save({
            "name": "tweak_only",
            "description": "Use when: tweaks only",
            "search_kwargs": {"fusion": "rrf"},
        })
        profile = json.loads(self.profiles_path.read_text("utf-8"))["tweak_only"]
        self.assertEqual(profile["description"], "Use when: tweaks only")


class LoadPipelineListHydratesDescriptionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="pipeline_desc_load_"))
        self._orig_pipelines_dir = pipeline_editor.PIPELINES_DIR
        self._orig_user_profiles_path = pipeline_editor.USER_PROFILES_PATH
        self._orig_registry_path = pipeline_editor.REGISTRY_PATH
        pipeline_editor.PIPELINES_DIR = self.tmpdir / "pipelines"
        pipeline_editor.USER_PROFILES_PATH = self.tmpdir / "data" / "pipelines.json"
        pipeline_editor.REGISTRY_PATH = pipeline_editor.PIPELINES_DIR / "registry.json"

    def tearDown(self) -> None:
        pipeline_editor.PIPELINES_DIR = self._orig_pipelines_dir
        pipeline_editor.USER_PROFILES_PATH = self._orig_user_profiles_path
        pipeline_editor.REGISTRY_PATH = self._orig_registry_path
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_list_pulls_description_from_topology_metadata(self) -> None:
        pipeline_editor._atomic_write_json(
            pipeline_editor.PIPELINES_DIR / "demo_unified.json",
            {
                "metadata": {"description": "Use when: pulled from topology"},
                "nodes": [{"name": "loader", "module": "x.Y", "params": {}}],
            },
        )
        pipeline_editor._atomic_write_json(
            pipeline_editor.REGISTRY_PATH,
            {"demo": {"unified_topology": "demo_unified.json", "indexing_overrides": {}}},
        )

        entries = {e["name"]: e for e in pipeline_editor.load_pipeline_list()}
        self.assertEqual(entries["demo"]["description"], "Use when: pulled from topology")

    def test_profile_description_wins_over_topology_metadata(self) -> None:
        pipeline_editor._atomic_write_json(
            pipeline_editor.PIPELINES_DIR / "demo_unified.json",
            {"metadata": {"description": "topology blurb"}, "nodes": []},
        )
        pipeline_editor._atomic_write_json(
            pipeline_editor.REGISTRY_PATH,
            {"demo": {
                "unified_topology": "demo_unified.json",
                "description": "profile blurb",
            }},
        )
        entries = {e["name"]: e for e in pipeline_editor.load_pipeline_list()}
        self.assertEqual(entries["demo"]["description"], "profile blurb")


class BuiltInProfilesReadDescriptionFromTopologyTest(unittest.TestCase):
    """Sanity check: the shipped registry.json has no description fields, yet
    ``profiles.describe()`` still surfaces them via topology metadata."""

    def test_default_profile_has_topology_sourced_description(self) -> None:
        from retriever.pipelines import profiles

        described = {entry["name"]: entry for entry in profiles.describe()}
        self.assertIn("default", described)
        self.assertIn("keyword_only", described)
        self.assertTrue(described["default"]["description"])
        self.assertTrue(described["keyword_only"]["description"])
        # The two share component graphs but must keep distinct descriptions.
        self.assertNotEqual(
            described["default"]["description"],
            described["keyword_only"]["description"],
        )


class BuildToolsEnrichesPipelineParamTest(unittest.TestCase):
    def test_upload_pipeline_param_lists_registered_profiles(self) -> None:
        from mcp_server.catalog import build_tools

        tools = {tool["name"]: tool for tool in build_tools()}
        upload = tools["upload"]
        param = upload["inputSchema"]["properties"]["pipeline"]
        for name in ("default", "keyword_only", "email", "hippo2rag", "rrf_rerank"):
            self.assertIn(name, param["description"])
        self.assertIn("enum", param)
        for name in ("default", "keyword_only", "email", "hippo2rag"):
            self.assertIn(name, param["enum"])


if __name__ == "__main__":
    unittest.main()
