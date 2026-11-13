"""
Knowledge Loader for CrewAI Engine (v1.0 SOTA)
Handles RAG ingestion of playbooks and dossiers via TextFileKnowledgeSource.
Enforces explicit pathlib.Path objects and Bifrost embedder configuration.
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("crewai_engine.knowledge_loader")


class KnowledgeLoader:
    """
    RAG Knowledge Source loader for CrewAI 1.15.30+.
    Enforces the explicit Path invariant to bypass the 'knowledge/' prefix bug.
    """

    @staticmethod
    def build_embedder_config(
        bifrost_url: str = "http://bifrost:8080/v1",
        api_key: str = "vk-crewai",
        model_name: str = "text-embedding-3-small"
    ) -> Dict[str, Any]:
        """Configures embedder pointing to Bifrost to prevent OPENAI_API_KEY missing exceptions."""
        return {
            "provider": "openai",
            "config": {
                "model_name": model_name,
                "api_base": bifrost_url,
                "api_key": api_key
            }
        }

    @classmethod
    def load_sources(
        cls,
        playbook_paths: List[Path],
        chunk_size: int = 2000,
        chunk_overlap: int = 200
    ) -> List[Any]:
        """
        Loads markdown playbooks and brand dossiers as TextFileKnowledgeSource instances.
        Guarantees that each path is a pathlib.Path instance.
        """
        try:
            from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource
        except ImportError:
            logger.warning("crewai knowledge sources not available in current environment")
            return []

        sources = []
        for p in playbook_paths:
            path_obj = Path(p) if isinstance(p, str) else p
            if path_obj.is_file():
                try:
                    source = TextFileKnowledgeSource(
                        file_paths=[path_obj],
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap
                    )
                    sources.append(source)
                    logger.info(f"Loaded knowledge source: {path_obj} ({path_obj.stat().st_size} bytes)")
                except Exception as ex:
                    logger.warning(f"Failed to load knowledge source {path_obj}: {ex}")
            else:
                logger.warning(f"Knowledge source file not found: {path_obj}")

        return sources
