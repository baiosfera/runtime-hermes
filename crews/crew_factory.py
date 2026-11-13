"""
Dynamic Crew Factory & Universal CoHaLo Skill Harness Integration
Unified Bifrost LLM Provider ($0 FreeLLMAPI default, DeepSeek failover).
"""
import os
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("hermes.crew_factory")

BIFROST_URL = os.getenv("HERMES_MODEL_ENDPOINT", "http://bifrost:8080/v1")
BIFROST_VK = os.getenv("BIFROST_VK_CREWAI", os.getenv("BIFROST_VIRTUAL_KEY", "vk-crewai"))

def get_bifrost_llm(tier: str = "free"):
    """
    Returns a configured CrewAI LLM pointing to the Bifrost Gateway.
    - tier 'free': Routes to FreeLLMAPI ($0) via Bifrost rule 1.
    - tier 'pro': Injects x-routing-tier: pro to route directly to DeepSeek via Bifrost CEL priority 0.
    """
    try:
        from crewai import LLM
    except ImportError:
        logger.warning("crewai not installed in current environment.")
        return None

    if tier == "pro":
        model_name = "openai/deepseek-chat"
        extra_headers = {"x-routing-tier": "pro", "x-force-deepseek": "true"}
    else:
        model_name = "openai/auto"
        extra_headers = {"x-routing-tier": "free"}

    return LLM(
        model=model_name,
        base_url=BIFROST_URL,
        api_key=BIFROST_VK,
        temperature=0.3,
        extra_headers=extra_headers
    )

class CrewFactory:
    _registry: Dict[str, Any] = {}

    @classmethod
    def register(cls, name: str, builder_fn):
        cls._registry[name.lower()] = builder_fn
        logger.info(f"Registered Crew in factory: {name}")

    @classmethod
    def list_crews(cls) -> List[str]:
        # Return registered crews + available sovereign skills
        base_crews = list(cls._registry.keys())
        try:
            from .universal_harness import UniversalSkillHarness
            skills = UniversalSkillHarness.list_available_skills()
            return sorted(list(set(base_crews + skills)))
        except Exception:
            return base_crews

    @classmethod
    def execute(cls, crew_name: str, topic: str, context: Optional[Dict[str, Any]] = None, tier: str = "free") -> str:
        key = crew_name.lower().strip()
        
        # 1. Registered builder function check
        if key in cls._registry:
            builder = cls._registry[key]
            crew_instance = builder(topic=topic, context=context or {}, tier=tier)
            try:
                result = crew_instance.kickoff()
                return str(result)
            except Exception as e:
                logger.error(f"Error executing crew '{crew_name}': {e}")
                return f"Error ejecutando cuadrilla {crew_name}: {str(e)}"

        # 2. Universal CoHaLo Dynamic Skill Harness check (141 skills)
        try:
            from .universal_harness import UniversalSkillHarness
            available_skills = UniversalSkillHarness.list_available_skills()
            if key in available_skills or key.replace("_", "-") in available_skills:
                actual_skill = key if key in available_skills else key.replace("_", "-")
                logger.info(f"Routing crew execution '{crew_name}' through UniversalSkillHarness for skill '{actual_skill}'")
                return UniversalSkillHarness.create_multi_skill_crew(
                    skill_names=[actual_skill],
                    mission_goal=topic,
                    tier=tier,
                    context=context
                )
        except Exception as e:
            logger.warning(f"UniversalSkillHarness fallback failed for {key}: {e}")

        available = ", ".join(cls.list_crews()[:20]) + "..."
        return f"Error: Crew '{crew_name}' no existe. Opciones disponibles: {available}"

    @classmethod
    def execute_skills_crew(cls, skill_names: List[str], goal: str, tier: str = "free") -> str:
        """Executes a multi-agent crew composed dynamically from 1 to N sovereign skills."""
        try:
            from .universal_harness import UniversalSkillHarness
            return UniversalSkillHarness.create_multi_skill_crew(
                skill_names=skill_names,
                mission_goal=goal,
                tier=tier
            )
        except Exception as e:
            return f"Error instanciando cuadrilla multi-skill: {str(e)}"

    @classmethod
    def create_dynamic_crew(
        cls,
        goal: str,
        roles: List[Dict[str, str]],
        tier: str = "free",
        output_schema: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Dynamically assembles an ad-hoc Crew from natural language roles or skills.
        roles: [{"role": "Investigador", "goal": "Buscar datos", "backstory": "..."}]
        output_schema: Optional schema spec for Pydantic validation (e.g. {"decision": "str", "score": "int"})
        """
        try:
            from crewai import Agent, Task, Crew, Process
        except ImportError:
            return "Error: crewai no está disponible en este entorno."

        llm = get_bifrost_llm(tier=tier)
        agents = []
        tasks = []

        output_model = None
        if output_schema and isinstance(output_schema, dict):
            try:
                from pydantic import create_model
                from pydanticai_engine import TYPE_MAPPING
                model_fields = {
                    k: TYPE_MAPPING.get(v.lower().strip(), (str, ...))
                    for k, v in output_schema.items()
                }
                output_model = create_model("DynamicCrewOutputSchema", **model_fields)
            except Exception as pe:
                logger.warning(f"Could not construct output_pydantic model: {pe}")

        for idx, r in enumerate(roles):
            agent = Agent(
                role=r.get("role", f"Especialista {idx+1}"),
                goal=r.get("goal", goal),
                backstory=r.get("backstory", f"Experto enfocado en {goal}"),
                llm=llm,
                verbose=False
            )
            agents.append(agent)
            
            task_kwargs = {
                "description": f"Contribuir al objetivo general: '{goal}'. Enfoque específico: {r.get('role')}.",
                "expected_output": "Resumen ejecutivo estructurado con hallazgos y recomendaciones.",
                "agent": agent
            }
            if output_model and idx == len(roles) - 1:
                task_kwargs["output_pydantic"] = output_model
                task_kwargs["expected_output"] = f"Estructura JSON estricta validada con Pydantic conformada por: {list(output_schema.keys())}"
            
            tasks.append(Task(**task_kwargs))

        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=False
        )

        try:
            output = crew.kickoff()
            if hasattr(output, "pydantic") and output.pydantic:
                if hasattr(output.pydantic, "model_dump_json"):
                    return output.pydantic.model_dump_json(indent=2)
                elif hasattr(output.pydantic, "model_dump"):
                    return json.dumps(output.pydantic.model_dump(), indent=2, ensure_ascii=False)
            return str(output)
        except Exception as e:
            return f"Error en ejecución de cuadrilla dinámica: {str(e)}"
