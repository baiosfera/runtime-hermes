"""
In-Memory Pydantic v2 Validation Governor for CrewAI Engine (v1.0 SOTA)
Bypasses crewai's output_pydantic to eliminate redundant LLM converter calls and 429 rate limits.
"""

import re
import json
import logging
from typing import Type, TypeVar, Optional
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("crewai_engine.validator")
T = TypeVar("T", bound=BaseModel)


class InMemoryPydanticParser:
    """
    Extracts and validates structured JSON outputs in memory in microseconds.
    Prevents redundant secondary HTTP converter calls from LiteLLM / InternalInstructor.
    """

    @staticmethod
    def format_task_prompt(base_prompt: str, schema_cls: Type[BaseModel]) -> str:
        """Injects JSON Schema into task description to instruct clean output."""
        schema_dict = schema_cls.model_json_schema()
        schema_str = json.dumps(schema_dict, indent=2)
        return (
            f"{base_prompt.strip()}\n\n"
            f"FORMATO DE SALIDA OBLIGATORIO (JSON ESTRICTO):\n"
            f"Debes responder ÚNICAMENTE con un objeto JSON válido que cumpla estrictamente este esquema:\n"
            f"```json\n{schema_str}\n```\n"
            f"REGLA CRÍTICA: Devuelve SOLO el bloque JSON sin texto conversacional previo ni explicaciones posteriores."
        )

    @staticmethod
    def extract_json_string(raw_text: str) -> str:
        """Strips markdown code fences and isolates outermost JSON object or array."""
        text = raw_text.strip()
        # Remove markdown code blocks if wrapped
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        
        # Locate outermost JSON object {...} or array [...]
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if match:
            return match.group(0).strip()
        return cleaned

    @classmethod
    def parse(cls, raw_output: str, schema_cls: Type[T]) -> T:
        """
        Validates raw LLM text against Pydantic schema in memory.
        Fast-path uses model_validate_json(); fallback uses json.loads(strict=False).
        """
        candidate = cls.extract_json_string(raw_output)

        # 1. Fast-path: Direct C/Rust parsing via model_validate_json
        try:
            return schema_cls.model_validate_json(candidate)
        except (ValidationError, ValueError) as primary_err:
            logger.debug(f"Fast-path validation failed, attempting tolerant fallback: {primary_err}")

        # 2. Tolerant fallback: json.loads with relaxed parsing
        try:
            parsed_dict = json.loads(candidate, strict=False)
            return schema_cls.model_validate(parsed_dict)
        except Exception as fallback_err:
            preview = candidate[:200] if len(candidate) > 200 else candidate
            raise ValueError(
                f"Failed to validate output against {schema_cls.__name__}.\n"
                f"Candidate JSON preview: {preview}\n"
                f"Error: {fallback_err}"
            ) from fallback_err
