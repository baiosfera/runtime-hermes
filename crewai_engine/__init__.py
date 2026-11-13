"""
CrewAI Engine: Sovereign Polymorphic Swarm Compiler & Skill Bridge (v1.0 SOTA)
"""

from .spec import DynamicSwarmSpec, AgentSpec, TaskSpec
from .compiler import SwarmCompiler
from .skill_bridge import SkillToolBridge, SkillSpec
from .validator import InMemoryPydanticParser
from .knowledge_loader import KnowledgeLoader

__all__ = [
    "DynamicSwarmSpec",
    "AgentSpec",
    "TaskSpec",
    "SwarmCompiler",
    "SkillToolBridge",
    "SkillSpec",
    "InMemoryPydanticParser",
    "KnowledgeLoader",
]
