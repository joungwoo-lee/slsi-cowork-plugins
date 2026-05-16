"""Per-pipeline ``answer_template`` lives on the last node of each topology.

These tests verify three guarantees:

1. Every shipped retrieval/unified topology declares an ``answer_template`` on
   its final node — otherwise an agent would silently lose formatting guidance
   for that pipeline.
2. ``engine.get_answer_template`` resolves the right template per profile.
3. ``handlers._answer_instructions_for`` surfaces the template under the
   ``answer_instructions`` key for the corresponding pipeline name.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.pipelines import engine, get_answer_template

PIPELINES_DIR = Path(__file__).resolve().parent.parent / "retriever" / "pipelines"

SHIPPED_TOPOLOGIES = [
    "default_unified.json",
    "email_unified.json",
    "keyword_only_unified.json",
    "rrf_rerank_unified.json",
    "rrf_llm_rerank_unified.json",
    "rrf_graph_rerank_unified.json",
    "hippo_graph_rrf_unified.json",
    "rrf_rerank_retrieval.json",
    "rrf_llm_rerank_retrieval.json",
]


class AnswerTemplateOnLastNodeTest(unittest.TestCase):
    def test_every_shipped_topology_carries_template_on_last_node(self) -> None:
        for fname in SHIPPED_TOPOLOGIES:
            with self.subTest(topology=fname):
                raw = json.loads((PIPELINES_DIR / fname).read_text("utf-8"))
                nodes = raw["nodes"]
                last = nodes[-1]
                self.assertIn("answer_template", last,
                              f"{fname}: last node {last.get('name')!r} missing answer_template")
                self.assertIsInstance(last["answer_template"], str)
                self.assertTrue(last["answer_template"].strip(),
                                f"{fname}: answer_template is blank")


class EngineGetAnswerTemplateTest(unittest.TestCase):
    def test_default_profile_returns_default_template(self) -> None:
        profile = engine.get_profile("default")
        template = get_answer_template(profile)
        self.assertIn("contexts", template)
        self.assertIn("[document_name:position]", template)

    def test_email_profile_returns_email_specific_template(self) -> None:
        profile = engine.get_profile("email")
        template = get_answer_template(profile)
        self.assertIn("이메일", template)
        self.assertIn("From", template)

    def test_keyword_only_profile_returns_keyword_only_template(self) -> None:
        profile = engine.get_profile("keyword_only")
        template = get_answer_template(profile)
        self.assertIn("키워드", template)

    def test_none_profile_falls_back_to_default(self) -> None:
        template = get_answer_template(None)
        # default profile uses default_unified.json which has a template
        self.assertTrue(template)

    def test_templates_differ_by_pipeline(self) -> None:
        templates = {
            name: get_answer_template(engine.get_profile(name))
            for name in ("default", "email", "keyword_only", "rrf_rerank",
                         "rrf_llm_rerank", "rrf_graph_rerank", "hippo_graph_rrf")
        }
        # Each pipeline should expose a non-empty template
        for name, t in templates.items():
            self.assertTrue(t, f"{name} has empty answer_template")
        # email + keyword_only must differ from default
        self.assertNotEqual(templates["email"], templates["default"])
        self.assertNotEqual(templates["keyword_only"], templates["default"])


class HandlersAnswerInstructionsTest(unittest.TestCase):
    def test_lookup_returns_template_for_known_pipeline(self) -> None:
        from mcp_server import handlers

        self.assertIn("이메일", handlers._answer_instructions_for("email"))
        self.assertIn("contexts", handlers._answer_instructions_for("default"))
        self.assertIn("키워드", handlers._answer_instructions_for("keyword_only"))

    def test_lookup_falls_back_for_unknown_pipeline(self) -> None:
        from mcp_server import handlers

        # Unknown name → profile registry falls back to default → default template
        template = handlers._answer_instructions_for("nonexistent_pipeline_xyz")
        self.assertTrue(template)
        self.assertEqual(template, handlers._answer_instructions_for("default"))


if __name__ == "__main__":
    unittest.main()
