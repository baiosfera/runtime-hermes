"""
Dynamic PydanticAI Engine with Bifrost Gateway Integration
Zero-hardcoding runtime for structured schema extraction and validation.
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, create_model
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

logger = logging.getLogger("hermes.pydanticai_engine")

BIFROST_URL = os.getenv("HERMES_MODEL_ENDPOINT", "http://bifrost:8080/v1")
BIFROST_VK = os.getenv("BIFROST_VK_PYDANTICAI", "vk-pydanticai")

TYPE_MAPPING = {
    "str": (str, ...),
    "string": (str, ...),
    "int": (int, ...),
    "integer": (int, ...),
    "float": (float, ...),
    "number": (float, ...),
    "bool": (bool, ...),
    "boolean": (bool, ...),
    "list[str]": (List[str], []),
    "list[int]": (List[int], []),
    "list[float]": (List[float], []),
    "dict": (Dict[str, Any], {}),
}

def get_pydantic_model(tier: str = "free"):
    """Returns a configured OpenAIChatModel pointing to Bifrost with vk-pydanticai."""
    model_name = "deepseek-chat" if tier == "pro" else "auto"
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url=BIFROST_URL,
            api_key=BIFROST_VK
        )
    )

async def extract_structured_data(fields_spec: Dict[str, str], user_input: str, tier: str = "free") -> str:
    """
    Dynamically creates a Pydantic model from a field specification dictionary and forces
    the LLM to return strictly validated JSON matching the schema.
    
    Example fields_spec:
      {"product_name": "str", "price": "int", "tags": "list[str]", "in_stock": "bool"}
    """
    try:
        model_fields = {}
        for fname, ftype in fields_spec.items():
            type_clean = ftype.lower().strip()
            model_fields[fname] = TYPE_MAPPING.get(type_clean, (str, ...))
            
        DynamicModel = create_model("DynamicExtractionSchema", **model_fields)
        llm_model = get_pydantic_model(tier=tier)
        agent = Agent(llm_model, output_type=DynamicModel)
        
        result = await agent.run(user_input)
        if hasattr(result.output, "model_dump_json"):
            return result.output.model_dump_json()
        elif hasattr(result.output, "model_dump"):
            return json.dumps(result.output.model_dump(), ensure_ascii=False)
        return str(result.output)
    except Exception as e:
        logger.error(f"Error in dynamic PydanticAI extraction: {e}")
        return f"❌ Error de validación estructurada: {str(e)}"
