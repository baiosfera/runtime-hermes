"""
Comprehensive Unit Test Suite for Sovereign CrewAI Engine (v1.0 SOTA)
Verifies DynamicSwarmSpec, InMemoryPydanticParser, SkillToolBridge, and SwarmCompiler.
"""

import sys
import os
import unittest
from pathlib import Path
from pydantic import BaseModel, Field

# Ensure apps/hermes is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from crewai_engine.spec import DynamicSwarmSpec, AgentSpec, TaskSpec
from crewai_engine.validator import InMemoryPydanticParser
from crewai_engine.skill_bridge import SkillToolBridge, SkillSpec
from crewai_engine.knowledge_loader import KnowledgeLoader
from crewai_engine.compiler import SwarmCompiler


class SampleOutputSchema(BaseModel):
    category: str = Field(description="Category name")
    score: float = Field(ge=0.0, le=10.0, description="Quality score")
    tags: list[str] = Field(default_factory=list, description="Associated tags")


class TestCrewAIEngine(unittest.TestCase):
    """Unit tests for the CrewAI Engine components."""

    def test_spec_instantiation_and_path_coercion(self):
        """Verifies DynamicSwarmSpec correctly instantiates and coerces playbook paths."""
        spec = DynamicSwarmSpec(
            crew_name="test-squad",
            mission_goal="Verify test compilation",
            process="sequential",
            tier="free",
            playbooks=["/var/www/artifacts/research/crewai-engine_dossier.md"],
            agents=[
                AgentSpec(
                    name="agent_1",
                    role="Test Agent",
                    goal="Test things",
                    backstory="Experienced test executor."
                )
            ],
            tasks=[
                TaskSpec(
                    name="task_1",
                    agent_name="agent_1",
                    description="Execute unit test",
                    expected_output="Test passed"
                )
            ]
        )
        self.assertEqual(spec.crew_name, "test-squad")
        self.assertEqual(len(spec.playbooks), 1)
        self.assertIsInstance(spec.playbooks[0], Path)
        self.assertEqual(spec.agents[0].name, "agent_1")
        self.assertEqual(spec.tasks[0].agent_name, "agent_1")

    def test_in_memory_pydantic_parser_clean_json(self):
        """Verifies InMemoryPydanticParser correctly validates clean JSON."""
        raw_json = '{"category": "Apotelos", "score": 9.5, "tags": ["sota", "reverse-causality"]}'
        result = InMemoryPydanticParser.parse(raw_json, SampleOutputSchema)
        self.assertEqual(result.category, "Apotelos")
        self.assertEqual(result.score, 9.5)
        self.assertEqual(len(result.tags), 2)

    def test_in_memory_pydantic_parser_markdown_wrapped(self):
        """Verifies InMemoryPydanticParser strips markdown fences and surrounding commentary."""
        raw_text = """
        Here is the final deliverable for the client:
        ```json
        {
            "category": "Category of One",
            "score": 10.0,
            "tags": ["synthemika", "astrotipia"]
        }
        ```
        Hope this helps! Let me know if you need adjustments.
        """
        result = InMemoryPydanticParser.parse(raw_text, SampleOutputSchema)
        self.assertEqual(result.category, "Category of One")
        self.assertEqual(result.score, 10.0)
        self.assertIn("synthemika", result.tags)

    def test_in_memory_pydantic_parser_invalid_json(self):
        """Verifies InMemoryPydanticParser raises ValueError on corrupted or invalid payloads."""
        invalid_text = "This is pure text with no JSON at all."
        with self.assertRaises(ValueError):
            InMemoryPydanticParser.parse(invalid_text, SampleOutputSchema)

    def test_in_memory_pydantic_format_prompt(self):
        """Verifies format_task_prompt injects JSON Schema cleanly."""
        prompt = InMemoryPydanticParser.format_task_prompt(
            base_prompt="Analyze the competitor landscape.",
            schema_cls=SampleOutputSchema
        )
        self.assertIn("Analyze the competitor landscape.", prompt)
        self.assertIn("FORMATO DE SALIDA OBLIGATORIO (JSON ESTRICTO):", prompt)
        self.assertIn('"category"', prompt)
        self.assertIn('"score"', prompt)

    def test_skill_bridge_resolves_known_skill(self):
        """Verifies SkillToolBridge resolves an installed skill and parses frontmatter."""
        skill_spec = SkillToolBridge.get_skill("crewai-engine")
        self.assertIsNotNone(skill_spec)
        self.assertEqual(skill_spec.name, "crewai-engine")
        self.assertTrue(len(skill_spec.description) > 0)
        self.assertIn("Sovereign Invariants", skill_spec.hard_rules)

    def test_skill_bridge_progressive_disclosure(self):
        """Verifies SkillSpec loads references/usage.md or infra.md."""
        skill_spec = SkillToolBridge.get_skill("crewai-engine")
        usage_doc = skill_spec.get_reference_content("usage.md")
        self.assertIsNotNone(usage_doc)
        self.assertIn("DynamicSwarmSpec", usage_doc)

    def test_knowledge_loader_embedder_config(self):
        """Verifies KnowledgeLoader builds correct Bifrost embedder specification."""
        cfg = KnowledgeLoader.build_embedder_config(
            bifrost_url="http://bifrost:8080/v1",
            api_key="vk-crewai",
            model_name="text-embedding-3-small"
        )
        self.assertEqual(cfg["provider"], "openai")
        self.assertEqual(cfg["config"]["api_base"], "http://bifrost:8080/v1")
        self.assertEqual(cfg["config"]["api_key"], "vk-crewai")

    def test_compiler_invalid_agent_dependency(self):
        """Verifies SwarmCompiler raises ValueError if a task references an unassigned agent."""
        spec = DynamicSwarmSpec(
            crew_name="broken-squad",
            mission_goal="Test broken reference",
            agents=[
                AgentSpec(
                    name="valid_agent",
                    role="Valid",
                    goal="Test",
                    backstory="Test"
                )
            ],
            tasks=[
                TaskSpec(
                    name="broken_task",
                    agent_name="ghost_agent",
                    description="Test ghost",
                    expected_output="Never"
                )
            ]
        )
        compiler = SwarmCompiler()
        with self.assertRaises(ValueError) as ctx:
            compiler.compile(spec)
        self.assertIn("ghost_agent", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
