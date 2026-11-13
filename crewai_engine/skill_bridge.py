"""
Dynamic Skill Tool Bridge for CrewAI Engine (v1.0 SOTA)
Polymorphically binds any of the 166 sovereign skills as CrewAI BaseTool instances.
Supports progressive disclosure doc readers and deterministic script execution.
"""

import os
import re
import yaml
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Type
from pydantic import BaseModel, Field

logger = logging.getLogger("crewai_engine.skill_bridge")

# Priority search paths for sovereign skills
SKILL_SEARCH_PATHS = [
    Path("/mnt/localstorage/skills"),
    Path("/var/www/localstorage/skills"),
    Path("/var/www/skills"),
    Path(__file__).parent.parent / "skills",
    Path("/var/www/zerops-astro-skills"),
    Path("/var/www/.agents/skills"),
    Path("/var/www/.claude/skills"),
]


class SkillSpec:
    """Parsed skill metadata and CoHaLo contracts from SKILL.md."""
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

        rules_match = re.search(r"## (?:Hard Rules|Sovereign Invariants).*?(?=\n## |\Z)", self.content, re.DOTALL | re.IGNORECASE)
        self.hard_rules = rules_match.group(0).strip() if rules_match else ""

        activation_match = re.search(r"## Activation Contract.*?(?=\n## |\Z)", self.content, re.DOTALL | re.IGNORECASE)
        self.activation_contract = activation_match.group(0).strip() if activation_match else ""

        output_match = re.search(r"## Output Contract.*?(?=\n## |\Z)", self.content, re.DOTALL | re.IGNORECASE)
        self.output_contract = output_match.group(0).strip() if output_match else ""

        scripts_dir = self.skill_dir / "scripts"
        if scripts_dir.is_dir():
            self.scripts = [p for p in scripts_dir.iterdir() if p.suffix in (".py", ".sh", ".ts")]

    def get_reference_content(self, ref_name: str = "usage.md") -> Optional[str]:
        ref_path = self.skill_dir / "references" / (f"{ref_name}.md" if not ref_name.endswith(".md") else ref_name)
        if ref_path.is_file():
            return ref_path.read_text(encoding="utf-8", errors="replace")
        return None


class SkillReferenceInput(BaseModel):
    reference_type: str = Field(default="usage", description="Type of reference doc: 'usage' or 'infra'")


class ScriptInput(BaseModel):
    args: List[str] = Field(default_factory=list, description="Command-line arguments for the script")


class SkillToolBridge:
    """
    Polymorphic bridge connecting sovereign skills to CrewAI BaseTool instances.
    """
    _cache: Dict[str, SkillSpec] = {}

    @classmethod
    def resolve_skill_path(cls, skill_name: str) -> Path:
        slug = skill_name.lower().strip()
        for root in SKILL_SEARCH_PATHS:
            candidate = root / slug
            if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                return candidate
        raise FileNotFoundError(f"Skill '{skill_name}' not found across paths: {SKILL_SEARCH_PATHS}")

    @classmethod
    def get_skill(cls, skill_name: str) -> SkillSpec:
        slug = skill_name.lower().strip()
        if slug not in cls._cache:
            path = cls.resolve_skill_path(slug)
            cls._cache[slug] = SkillSpec(slug, path)
        return cls._cache[slug]

    @classmethod
    def create_reference_reader_tool(cls, skill_spec: SkillSpec) -> Optional[Any]:
        """Creates a CrewAI BaseTool allowing an agent to consult deep usage/infra references."""
        try:
            from crewai.tools import BaseTool
        except ImportError:
            return None

        clean_name = f"read_{skill_spec.name.replace('-', '_')}_reference"

        class DynamicReferenceReader(BaseTool):
            name: str = clean_name
            description: str = f"Consulta especificaciones avanzadas (usage/infra) de '{skill_spec.name}'."
            args_schema: Type[BaseModel] = SkillReferenceInput

            def _run(self, reference_type: str = "usage") -> str:
                content = skill_spec.get_reference_content(reference_type)
                if content:
                    return f"=== REFERENCIA {skill_spec.name}/{reference_type} ===\n{content[:4000]}"
                return f"No se encontró documento de referencia '{reference_type}' para la skill '{skill_spec.name}'."

        return DynamicReferenceReader()

    @classmethod
    def create_script_tool(cls, skill_spec: SkillSpec, script_path: Path) -> Optional[Any]:
        """Creates a CrewAI BaseTool wrapping a deterministic Python/Bash/Bun script."""
        try:
            from crewai.tools import BaseTool
        except ImportError:
            return None

        clean_name = f"run_{skill_spec.name.replace('-', '_')}_{script_path.stem.replace('-', '_')}"
        suffix = script_path.suffix

        if suffix == ".ts":
            interpreter = "bun"
        elif suffix == ".py":
            interpreter = "python3"
        elif suffix == ".sh":
            interpreter = "bash"
        else:
            return None

        class DynamicScriptTool(BaseTool):
            name: str = clean_name
            description: str = f"Ejecuta el script {script_path.name} ({interpreter}) de '{skill_spec.name}'."
            args_schema: Type[BaseModel] = ScriptInput

            def _run(self, args: List[str] = None) -> str:
                cmd = [interpreter, str(script_path)]
                if args:
                    cmd.extend(args)
                try:
                    res = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=120,
                        cwd=str(script_path.parent)
                    )
                    if res.returncode != 0:
                        return f"Error ({script_path.name} exit {res.returncode}):\n{res.stderr[:2000]}"
                    return res.stdout[:8000] or f"Ejecución exitosa de {script_path.name} (exit code 0)."
                except subprocess.TimeoutExpired:
                    return f"Timeout: {script_path.name} superó 120s."
                except Exception as ex:
                    return f"Error ejecutando {script_path.name}: {str(ex)}"

        return DynamicScriptTool()
