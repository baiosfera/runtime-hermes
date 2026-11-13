"""
Dynamic Swarm Specification Models for CrewAI Engine (v1.0 SOTA)
Declarative Pydantic v2 schemas defining multi-agent squads, tasks, and knowledge bindings.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field, field_validator


class AgentSpec(BaseModel):
    """Declarative specification for an agent in a dynamic swarm."""
    name: str = Field(description="Unique agent identifier in the swarm")
    role: str = Field(description="Professional role title")
    goal: str = Field(description="Primary objective driving agent decisions")
    backstory: str = Field(description="CoHaLo Hard Rules, context, and domain expertise")
    skills: List[str] = Field(default_factory=list, description="List of sovereign skills to bind")
    max_iter: int = Field(default=15, description="Maximum reasoning loops")
    verbose: bool = Field(default=False, description="Verbose logging")


class TaskSpec(BaseModel):
    """Declarative specification for a task in a dynamic swarm."""
    name: str = Field(description="Unique task identifier")
    agent_name: str = Field(description="Name of the assigned agent")
    description: str = Field(description="Detailed execution prompt and instructions")
    expected_output: str = Field(description="Contract definition of expected output")
    context_task_names: List[str] = Field(default_factory=list, description="Upstream task dependencies")


class DynamicSwarmSpec(BaseModel):
    """Declarative specification for a complete dynamic swarm mission."""
    crew_name: str = Field(description="Canonical squad name")
    mission_goal: str = Field(description="High-level mission objective")
    process: Literal["sequential", "hierarchical"] = Field(default="sequential", description="Execution process")
    tier: Literal["free", "pro"] = Field(default="free", description="Inference tier (free=$0 FreeLLMAPI, pro=DeepSeek)")
    playbooks: List[Path] = Field(default_factory=list, description="Paths to markdown playbooks for RAG ingestion")
    agents: List[AgentSpec] = Field(..., description="List of agent specifications")
    tasks: List[TaskSpec] = Field(..., description="List of task specifications")

    @field_validator("playbooks", mode="before")
    @classmethod
    def coerce_paths(cls, v: Any) -> List[Path]:
        if not v:
            return []
        coerced = []
        for item in v:
            if isinstance(item, (str, Path)):
                coerced.append(Path(item))
            else:
                raise ValueError(f"Invalid playbook path type: {type(item)}")
        return coerced
