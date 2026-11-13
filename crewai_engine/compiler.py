"""
Swarm Compiler for CrewAI Engine (v1.0 SOTA)
Polymorphically compiles DynamicSwarmSpec into executable CrewAI Crew instances.
Abolishes static @CrewBase classes and hardcoded squads in favor of pure dynamic assembly.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from pydantic import BaseModel

from .spec import DynamicSwarmSpec, AgentSpec, TaskSpec
from .skill_bridge import SkillToolBridge
from .knowledge_loader import KnowledgeLoader

logger = logging.getLogger("crewai_engine.compiler")

DEFAULT_BIFROST_URL = os.getenv("HERMES_MODEL_ENDPOINT", "http://bifrost:8080/v1")
DEFAULT_BIFROST_VK = os.getenv("BIFROST_VK_CREWAI", os.getenv("BIFROST_VIRTUAL_KEY", "vk-crewai"))


class SwarmCompiler:
    """
    Polymorphic compiler assembling declarative DynamicSwarmSpec into CrewAI Crew.
    """

    def __init__(
        self,
        bifrost_url: str = DEFAULT_BIFROST_URL,
        bifrost_vk: str = DEFAULT_BIFROST_VK
    ):
        self.bifrost_url = bifrost_url
        self.bifrost_vk = bifrost_vk

    def _build_llm(self, tier: str = "free") -> Any:
        try:
            from crewai import LLM
        except ImportError:
            raise RuntimeError("crewai is not installed in current environment")

        tier_headers = {"x-routing-tier": tier}
        if tier == "pro":
            tier_headers["x-force-deepseek"] = "true"

        return LLM(
            model="openai/auto",
            base_url=self.bifrost_url,
            api_key=self.bifrost_vk,
            temperature=0.2,
            extra_headers=tier_headers
        )

    def validate_spec(self, spec: DynamicSwarmSpec) -> None:
        """Validates agent references and task dependencies in spec before compilation."""
        agent_names = {a.name for a in spec.agents}
        for task in spec.tasks:
            if task.agent_name not in agent_names:
                raise ValueError(
                    f"Agent '{task.agent_name}' specified for task '{task.name}' "
                    f"does not exist in agents list: {list(agent_names)}"
                )

    def compile(self, spec: DynamicSwarmSpec) -> Any:
        """Compiles declarative DynamicSwarmSpec into an executable Crew instance."""
        self.validate_spec(spec)

        try:
            from crewai import Agent, Task, Crew, Process
        except ImportError:
            raise RuntimeError("crewai is not installed in current environment")

        llm = self._build_llm(tier=spec.tier)

        # 1. Assemble Agents
        agents_map: Dict[str, Any] = {}
        for a_spec in spec.agents:
            agent_tools = []
            enriched_backstory = a_spec.backstory

            for skill_name in a_spec.skills:
                try:
                    skill_spec = SkillToolBridge.get_skill(skill_name)
                    # Add reference reader tool
                    ref_tool = SkillToolBridge.create_reference_reader_tool(skill_spec)
                    if ref_tool:
                        agent_tools.append(ref_tool)

                    # Add script tools if present
                    for s in skill_spec.scripts[:2]:
                        s_tool = SkillToolBridge.create_script_tool(skill_spec, s)
                        if s_tool:
                            agent_tools.append(s_tool)

                    # Inject CoHaLo hard rules into backstory if not already present
                    if skill_spec.hard_rules and skill_spec.hard_rules not in enriched_backstory:
                        enriched_backstory += f"\n\n[DIRECTIVAS SOBERANAS: {skill_spec.name}]\n{skill_spec.hard_rules}"

                except Exception as ex:
                    logger.warning(f"Could not bind skill '{skill_name}' to agent '{a_spec.name}': {ex}")

            agent_instance = Agent(
                role=a_spec.role,
                goal=a_spec.goal,
                backstory=enriched_backstory,
                tools=agent_tools,
                llm=llm,
                max_iter=a_spec.max_iter,
                verbose=a_spec.verbose
            )
            agents_map[a_spec.name] = agent_instance

        # 2. Assemble Tasks
        tasks_map: Dict[str, Any] = {}
        tasks_list = []
        for t_spec in spec.tasks:
            assigned_agent = agents_map.get(t_spec.agent_name)
            if not assigned_agent:
                raise ValueError(
                    f"Agent '{t_spec.agent_name}' specified for task '{t_spec.name}' "
                    f"does not exist in agents list: {list(agents_map.keys())}"
                )

            # Resolve context dependencies
            context_tasks = [
                tasks_map[ctx_name]
                for ctx_name in t_spec.context_task_names
                if ctx_name in tasks_map
            ]

            task_instance = Task(
                description=t_spec.description,
                expected_output=t_spec.expected_output,
                agent=assigned_agent,
                context=context_tasks if context_tasks else None
            )
            tasks_map[t_spec.name] = task_instance
            tasks_list.append(task_instance)

        # 3. Assemble Crew
        crew_kwargs: Dict[str, Any] = {
            "agents": list(agents_map.values()),
            "tasks": tasks_list,
            "process": Process.sequential if spec.process == "sequential" else Process.hierarchical,
            "verbose": False
        }

        # 4. Ingest Playbooks via Knowledge Sources if specified
        if spec.playbooks:
            sources = KnowledgeLoader.load_sources(spec.playbooks)
            if sources:
                crew_kwargs["knowledge_sources"] = sources
                crew_kwargs["embedder"] = KnowledgeLoader.build_embedder_config(
                    bifrost_url=self.bifrost_url,
                    api_key=self.bifrost_vk
                )

        return Crew(**crew_kwargs)
