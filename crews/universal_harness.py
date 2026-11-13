"""
Universal CoHaLo Dynamic Skill Harness for CrewAI (v2.0 SOTA)
Connects any of the 141 sovereign skills (.atl/skill-registry.md) to CrewAI agents,
hydrating Positive Guidance, Hard Rules, and Output Contracts dynamically at runtime.
Operates 24/7 on Bifrost (:8080) -> FreeLLMAPI (:3001) at $0 cost by default.
"""

import os
import re
import yaml
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Type
from pydantic import BaseModel, Field

logger = logging.getLogger("crewai.universal_harness")

# Search paths for skills in priority order:
# 1. /mnt/localstorage/skills (Shared persistent NVMe volume across Zerops containers 24/7)
# 2. Local packaged ./skills
# 3. Local repository /var/www/zerops-astro-skills or /var/www/.agents/skills
SKILL_SEARCH_PATHS = [
    Path("/mnt/localstorage/skills"),
    Path(__file__).parent.parent / "skills",
    Path("/var/www/zerops-astro-skills"),
    Path("/var/www/.agents/skills"),
    Path("/var/www/.claude/skills"),
]

BIFROST_URL = os.getenv("HERMES_MODEL_ENDPOINT", "http://bifrost:8080/v1")
BIFROST_VK = os.getenv("BIFROST_VK_CREWAI", os.getenv("BIFROST_VIRTUAL_KEY", "vk-crewai"))


class SkillSpec:
    """Represents parsed skill metadata and rules from SKILL.md under CoHaLo."""
    def __init__(self, name: str, skill_dir: Path):
        self.name = name
        self.skill_dir = skill_dir
        self.skill_md_path = skill_dir / "SKILL.md"
        self.metadata: Dict[str, Any] = {}
        self.description: str = ""
        self.content: str = ""
        self.hard_rules: str = ""
        self.activation_contract: str = ""
        self.output_contract: str = ""
        self.scripts: List[Path] = []
        self._load()

    def _load(self):
        if not self.skill_md_path.exists():
            raise FileNotFoundError(f"SKILL.md not found at {self.skill_md_path}")
        
        raw_text = self.skill_md_path.read_text(encoding="utf-8", errors="replace")
        parts = re.split(r"^---\s*$", raw_text, flags=re.MULTILINE)
        
        if len(parts) >= 3:
            try:
                self.metadata = yaml.safe_load(parts[1]) or {}
            except Exception as e:
                logger.warning(f"Error parsing YAML frontmatter in {self.name}: {e}")
            self.content = parts[2].strip()
        else:
            self.content = raw_text.strip()

        self.description = self.metadata.get("description", "")

        # Extract CoHaLo sections via regex
        rules_match = re.search(r"## (?:Hard Rules|Sovereign Invariants).*?(?=\n## |\Z)", self.content, re.DOTALL | re.IGNORECASE)
        self.hard_rules = rules_match.group(0).strip() if rules_match else ""

        activation_match = re.search(r"## Activation Contract.*?(?=\n## |\Z)", self.content, re.DOTALL | re.IGNORECASE)
        self.activation_contract = activation_match.group(0).strip() if activation_match else ""

        output_match = re.search(r"## Output Contract.*?(?=\n## |\Z)", self.content, re.DOTALL | re.IGNORECASE)
        self.output_contract = output_match.group(0).strip() if output_match else ""

        # Scan for physical scripts
        scripts_dir = self.skill_dir / "scripts"
        if scripts_dir.is_dir():
            self.scripts = [p for p in scripts_dir.iterdir() if p.suffix in (".py", ".sh", ".ts")]

    def get_reference_content(self, ref_name: str = "usage.md") -> Optional[str]:
        """Progressive disclosure: loads usage.md or infra.md on demand."""
        ref_path = self.skill_dir / "references" / ref_name
        if ref_path.is_file():
            return ref_path.read_text(encoding="utf-8", errors="replace")
        return None


class UniversalSkillHarness:
    """
    CoHaLo Master Harness connecting all 141 sovereign skills to CrewAI.
    Zero hardcoded skills; 100% dynamic discovery and execution.
    """
    _skills_cache: Dict[str, SkillSpec] = {}

    @classmethod
    def resolve_skill_path(cls, skill_name: str) -> Path:
        """Finds skill directory across priority search paths."""
        slug = skill_name.lower().strip()
        for root in SKILL_SEARCH_PATHS:
            candidate = root / slug
            if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                return candidate
        raise FileNotFoundError(f"Skill '{skill_name}' could not be located in any search path: {SKILL_SEARCH_PATHS}")

    @classmethod
    def get_skill(cls, skill_name: str) -> SkillSpec:
        slug = skill_name.lower().strip()
        if slug not in cls._skills_cache:
            path = cls.resolve_skill_path(slug)
            cls._skills_cache[slug] = SkillSpec(slug, path)
        return cls._skills_cache[slug]

    @classmethod
    def list_available_skills(cls) -> List[str]:
        found = set()
        for root in SKILL_SEARCH_PATHS:
            if root.is_dir():
                for item in root.iterdir():
                    if item.is_dir() and (item / "SKILL.md").is_file():
                        found.add(item.name)
        return sorted(list(found))

    @classmethod
    def create_skill_reference_tool(cls, skill_spec: SkillSpec):
        """CrewAI tool allowing an agent to consult deep references JIT."""
        try:
            from crewai.tools import BaseTool
        except ImportError:
            return None

        class SkillReferenceInput(BaseModel):
            reference_type: str = Field(default="usage", description="Type of reference doc: 'usage' or 'infra'")

        class SkillReferenceReaderTool(BaseTool):
            name: str = f"read_{skill_spec.name.replace('-', '_')}_reference"
            description: str = f"Consulta las especificaciones tecnicas avanzadas (usage/infra) del skill '{skill_spec.name}'."
            args_schema: Type[BaseModel] = SkillReferenceInput

            def _run(self, reference_type: str = "usage") -> str:
                filename = f"{reference_type}.md" if not reference_type.endswith(".md") else reference_type
                content = skill_spec.get_reference_content(filename)
                if content:
                    return f"=== REFERENCIA {skill_spec.name}/{filename} ===\n{content[:4000]}"
                return f"No se encontró referencia '{filename}' para el skill '{skill_spec.name}'."

        return SkillReferenceReaderTool()

    @classmethod
    def create_script_tool(cls, skill_spec: SkillSpec, script_path: Path):
        """Constructs a deterministic BaseTool executing a local script."""
        try:
            from crewai.tools import BaseTool
        except ImportError:
            return None

        clean_tool_name = f"run_{skill_spec.name.replace('-', '_')}_{script_path.stem.replace('-', '_')}"

        class ScriptInput(BaseModel):
            args: List[str] = Field(default_factory=list, description="Lista de argumentos de linea de comando para el script")

        class DynamicScriptExecutionTool(BaseTool):
            name: str = clean_tool_name
            description: str = f"Ejecuta el script {script_path.name} del skill '{skill_spec.name}' de forma determinista."
            args_schema: Type[BaseModel] = ScriptInput

            def _run(self, args: List[str] = None) -> str:
                cmd = ["python3" if script_path.suffix == ".py" else "bash", str(script_path)]
                if args:
                    cmd.extend(args)
                logger.info(f"DynamicScriptTool executing: {' '.join(cmd)}")
                try:
                    res = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=180,
                        cwd=str(script_path.parent)
                    )
                    if res.returncode != 0:
                        return f"Error ({script_path.name} code {res.returncode}):\n{res.stderr[:2000]}"
                    return res.stdout[:8000] or f"Ejecución exitosa de {script_path.name} (exit code 0)."
                except subprocess.TimeoutExpired:
                    return f"Error: {script_path.name} superó el timeout de 180s."
                except Exception as ex:
                    return f"Error de ejecución: {str(ex)}"

        return DynamicScriptExecutionTool()

    @classmethod
    def create_agent_for_skill(
        cls,
        skill_name: str,
        role: Optional[str] = None,
        goal: Optional[str] = None,
        tier: str = "free",
        include_script_tools: bool = True
    ):
        """
        Dynamically instantiates a CrewAI Agent hydrated with CoHaLo Hard Rules
        from any of the 141 skills.
        """
        try:
            from crewai import Agent, LLM
        except ImportError:
            raise RuntimeError("crewai is not installed in current environment.")

        spec = cls.get_skill(skill_name)

        agent_role = role or f"Especialista Soberano en {spec.name.replace('-', ' ').title()}"
        agent_goal = goal or f"Aplicar con maestría técnica los contratos del skill '{spec.name}'."

        backstory = (
            f"Sos el especialista técnico líder en la disciplina '{spec.name}'.\n"
            f"Tu propósito y directiva principal:\n{spec.description}\n\n"
            f"REGLAS INVIOLABLES DE DOMINIO (Positive Guidance):\n"
            f"{spec.hard_rules or 'Operá con estricta adherencia a buenas prácticas y verificación física.'}\n\n"
            f"Alineás cada entregable a la arquitectura soberana de Zerops con rigor matemático."
        )

        # Routing tier setup: free uses $0 FreeLLMAPI pool; pro injects headers for DeepSeek
        if tier == "pro":
            model_name = "openai/deepseek-chat"
            headers = {"x-routing-tier": "pro", "x-force-deepseek": "true"}
        else:
            model_name = "openai/auto"
            headers = {"x-routing-tier": "free"}

        llm = LLM(
            model=model_name,
            base_url=BIFROST_URL,
            api_key=BIFROST_VK,
            temperature=0.2,
            extra_headers=headers
        )

        tools = []
        ref_tool = cls.create_skill_reference_tool(spec)
        if ref_tool:
            tools.append(ref_tool)

        if include_script_tools and spec.scripts:
            for s in spec.scripts[:3]:  # Top 3 scripts as tools
                script_tool = cls.create_script_tool(spec, s)
                if script_tool:
                    tools.append(script_tool)

        return Agent(
            role=agent_role,
            goal=agent_goal,
            backstory=backstory,
            tools=tools,
            llm=llm,
            verbose=False
        )

    @classmethod
    def create_task_for_skill(
        cls,
        agent: Any,
        skill_name: str,
        objective: str,
        expected_output: Optional[str] = None,
        output_pydantic: Optional[Type[BaseModel]] = None
    ):
        """Creates a CrewAI Task hydrated with Activation, Output Contracts, and PydanticAI Schema Governor."""
        try:
            from crewai import Task
        except ImportError:
            raise RuntimeError("crewai is not installed")

        spec = cls.get_skill(skill_name)

        desc = (
            f"Objetivo de la misión: {objective}\n\n"
            f"Contrato de Activación y Pautas de Ejecución:\n"
            f"{spec.activation_contract or 'Ejecutar conforme al estándar técnico de la disciplina.'}\n"
        )

        output = expected_output or (
            f"Entregable conforme al Output Contract del skill:\n"
            f"{spec.output_contract or 'Informe técnico exhaustivo, estructurado y físicamente validado.'}"
        )

        task_kwargs: Dict[str, Any] = {
            "description": desc,
            "expected_output": output,
            "agent": agent
        }
        if output_pydantic is not None:
            task_kwargs["output_pydantic"] = output_pydantic

        return Task(**task_kwargs)

    @classmethod
    def create_multi_skill_crew(
        cls,
        skill_names: List[str],
        mission_goal: str,
        tier: str = "free",
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Dynamically assembles a collaborative Crew from multiple skills (e.g. ['bknd', 'frnt', 'seo-aeo-geo']).
        """
        try:
            from crewai import Crew, Process
        except ImportError:
            return "Error: crewai no está instalado en este entorno."

        agents = []
        tasks = []

        for skill_name in skill_names:
            try:
                agent = cls.create_agent_for_skill(skill_name, tier=tier)
                agents.append(agent)
                task = cls.create_task_for_skill(
                    agent=agent,
                    skill_name=skill_name,
                    objective=f"Contribuir al objetivo general '{mission_goal}' desde la especialidad de {skill_name}."
                )
                tasks.append(task)
            except Exception as e:
                logger.warning(f"Error hydrating agent for skill {skill_name}: {e}")

        if not agents:
            return f"Error: No se pudo instanciar ningún agente para las skills solicitadas: {skill_names}"

        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=False
        )

        try:
            result = crew.kickoff()
            return str(result)
        except Exception as ex:
            logger.error(f"Error executing multi-skill crew: {ex}")
            return f"Error ejecutando cuadrilla multi-skill: {str(ex)}"
