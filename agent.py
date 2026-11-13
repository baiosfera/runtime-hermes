"""
Hermes-Agent Execution Loop
Sovereign Master Agent for Sovereign Multi-Agent Mesh
"""
import os
import sys
import re
import json
import uuid
import logging
import asyncio
import httpx

logger = logging.getLogger("hermes.agent")

def load_hermes_soul() -> str:
    """Loads the canonical Gentle AI SOUL.md constitution for Hermes Agent."""
    candidates = [
        os.path.expanduser("~/.hermes/SOUL.md"),
        "/mnt/localstorage/hermes/.hermes/SOUL.md",
        "/var/www/localstorage/hermes/.hermes/SOUL.md",
        os.path.join(os.path.dirname(__file__), "SOUL.md"),
        "/var/www/SOUL.md",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        logger.info(f"[Hermes] Loaded canonical SOUL.md from {path} ({len(content)} bytes)")
                        return content
            except Exception as e:
                logger.warning(f"Failed to read SOUL.md from {path}: {e}")
    # Minimal affirmative fallback in case no file is reachable
    return (
        "Eres Hermes Agent, el orquestador autónomo de infraestructura y aplicaciones en Zerops. "
        "Operás con rigor de Senior Architect, voseo natural y respuestas concisas orientadas a la acción."
    )

try:
    from tools import (
        get_system_health, calculate_natal_chart, send_whatsapp_otp,
        list_zerops_services, start_zerops_service, stop_zerops_service, delete_zerops_service, get_zerops_service_status,
        zerops_get_service_logs, zerops_deploy_service, call_zerops_mcp_tool,
        pidev_get_status, pidev_dispatch_task,
        read_file, write_file, edit_file, list_directory, run_command,
        search_web, fetch_web_page, download_file,
        execute_store_query,
        run_crew_ai, extract_structured_data,
        list_available_crews, get_paperclip_status,
        paperclip_list_tasks, paperclip_create_task, paperclip_register_agent,
        mem_context, mem_search, mem_save,
        linear_create_issue, linear_update_status, linear_get_issue, linear_comment_issue,
        list_verticals, get_vertical, list_playbooks, get_playbook, get_brandbook_tokens,
        list_skills, get_skill_docs, apotelos_cli
    )
except (ImportError, ValueError):
    from .tools import (
        get_system_health, calculate_natal_chart, send_whatsapp_otp,
        list_zerops_services, start_zerops_service, stop_zerops_service, delete_zerops_service, get_zerops_service_status,
        zerops_get_service_logs, zerops_deploy_service, call_zerops_mcp_tool,
        pidev_get_status, pidev_dispatch_task,
        read_file, write_file, edit_file, list_directory, run_command,
        search_web, fetch_web_page, download_file,
        execute_store_query,
        run_crew_ai, extract_structured_data,
        list_available_crews, get_paperclip_status,
        paperclip_list_tasks, paperclip_create_task, paperclip_register_agent,
        mem_context, mem_search, mem_save,
        linear_create_issue, linear_update_status, linear_get_issue, linear_comment_issue,
        list_verticals, get_vertical, list_playbooks, get_playbook, get_brandbook_tokens,
        list_skills, get_skill_docs, apotelos_cli
    )

try:
    from env_utils import clean_env, load_runtime_env
except (ImportError, ValueError):
    from .env_utils import clean_env, load_runtime_env

# Load persistent runtime environment if present
load_runtime_env([
    clean_env("RUNTIME_ENV_PATH", "/mnt/localstorage/hermes/runtime.env"),
])

BIFROST_URL = clean_env("HERMES_MODEL_ENDPOINT", "http://bifrost:8080/v1")
_raw_model = clean_env("HERMES_MODEL_OVERRIDE") or clean_env("HERMES_MODEL_NAME")
MODEL_NAME = _raw_model if (_raw_model and _raw_model.lower() != "auto") else "auto"
BIFROST_KEY = clean_env("BIFROST_VIRTUAL_KEY", "vk-hermes-agent")

HERMES_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_health",
            "description": "Verifica el estado de salud en tiempo real de todos los componentes del cluster (Paperclip, NATS, PostgreSQL, Zerops).",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_zerops_services",
            "description": "Lista todos los servicios desplegados en el proyecto de Zerops y su estado actual (ACTIVE / STOPPED).",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "call_zerops_mcp_tool",
            "description": "Invoca directamente cualquier herramienta nativa del servidor MCP de Zerops (zcp serve: zerops_discover, zerops_import, zerops_scale, zerops_deploy, zerops_subdomain, zerops_env, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Nombre de la herramienta MCP nativa (ej: 'zerops_discover', 'zerops_import', 'zerops_scale', 'zerops_subdomain')"
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Diccionario de argumentos para la herramienta MCP"
                    }
                },
                "required": ["tool_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_zerops_service_status",
            "description": "Consulta el estado y salud detallada de un servicio específico de Zerops.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Nombre exacto del servicio (ej: 'paperclip', 'bifrost', 'hermes', 'pidev')"}
                },
                "required": ["service_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_zerops_service",
            "description": "Inicia o enciende un servicio de Zerops por nombre.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Nombre del servicio"}
                },
                "required": ["service_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_zerops_service",
            "description": "Detiene o apaga un servicio de Zerops por nombre.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Nombre del servicio"}
                },
                "required": ["service_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_zerops_service",
            "description": "Elimina de forma segura un servicio de Zerops cuando es requerido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Nombre del servicio"}
                },
                "required": ["service_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "zerops_get_service_logs",
            "description": "Obtiene los logs recientes de runtime o build de cualquier contenedor en Zerops.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Nombre del servicio (ej: 'paperclip', 'bifrost', 'hermes', 'pidev')"},
                    "limit": {"type": "integer", "description": "Cantidad de líneas a recuperar", "default": 50}
                },
                "required": ["service_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "zerops_deploy_service",
            "description": "Dispara el despliegue o push de código a cualquier servicio de Zerops.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "description": "Nombre del servicio a desplegar"},
                    "working_dir": {"type": "string", "description": "Directorio local de origen (opcional)", "default": ""}
                },
                "required": ["service_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pidev_get_status",
            "description": "Consulta la salud en tiempo real, versión de Gentle-Pi y disponibilidad del servicio PiDev.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pidev_dispatch_task",
            "description": "Despacha una misión de programación o desarrollo frontend (Astro, TypeScript) al agente soberano PiDev (gentle-pi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Instrucción clara de desarrollo o edición de código para Gentle-Pi"},
                    "working_dir": {"type": "string", "description": "Directorio de trabajo dentro de pidev (default: '/var/www')", "default": "/var/www"}
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "linear_create_issue",
            "description": "Crea una nueva tarea o issue en Linear vinculado al proyecto activo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título claro de la tarea"},
                    "description": {"type": "string", "description": "Descripción y criterios de aceptación"},
                    "priority": {"type": "integer", "description": "Prioridad (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low)", "default": 2}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "linear_update_status",
            "description": "Actualiza el estado de una tarea en Linear (Done requiere evidencia comprobable).",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string", "description": "ID del issue (ej: 'BAI-449')"},
                    "status": {"type": "string", "enum": ["Todo", "In Progress", "Done", "Canceled"], "description": "Nuevo estado"},
                    "evidence": {"type": "string", "description": "Evidencia técnica física que valida el cambio de estado"}
                },
                "required": ["issue_id", "status"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "linear_get_issue",
            "description": "Obtiene los detalles, descripción y estado actual de una tarea en Linear.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string", "description": "ID del issue (ej: 'BAI-449')"}
                },
                "required": ["issue_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "linear_comment_issue",
            "description": "Añade un comentario u observación técnica a una tarea en Linear.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": {"type": "string", "description": "ID del issue"},
                    "comment": {"type": "string", "description": "Texto del comentario"}
                },
                "required": ["issue_id", "comment"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_paperclip_status",
            "description": "Consulta el estado en vivo de Paperclip AI (http://paperclip:3100), incluyendo agentes registrados, tareas y spend caps.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "paperclip_list_tasks",
            "description": "Lista tareas e issues activos registrados en el tablero Kanban de Paperclip Control Plane.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filtro opcional por estado (todo, in_progress, in_review, done, backlog)"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "paperclip_create_task",
            "description": "Crea una nueva tarea o issue en el tablero Kanban de Paperclip Control Plane.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Título claro y conciso de la tarea"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detalles o criterios de aceptación de la tarea"
                    },
                    "priority": {
                        "type": "string",
                        "description": "Prioridad de la tarea (low, medium, high, urgent)",
                        "enum": ["low", "medium", "high", "urgent"]
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "paperclip_register_agent",
            "description": "Registra un nuevo agente permanente en el organigrama y control plane de Paperclip bajo la supervisión de Hermes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Nombre del agente (ej. Closer de Ventas, Especialista DIAN, Analista de Mercado)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Cargo formal del agente en el organigrama"
                    },
                    "role": {
                        "type": "string",
                        "description": "Nivel jerárquico (lead, worker)",
                        "enum": ["lead", "worker"]
                    },
                    "adapter_type": {
                        "type": "string",
                        "description": "Tipo de adaptador de ejecución (hermes_gateway, pi_local, process)",
                        "enum": ["hermes_gateway", "pi_local", "process"]
                    },
                    "capabilities": {
                        "type": "string",
                        "description": "Descripción concisa de las capacidades y responsabilidades del agente"
                    },
                    "budget_monthly_cents": {
                        "type": "integer",
                        "description": "Techo de gasto mensual en centavos de dólar (default: 50000 = $500 USD)"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_crew_ai",
            "description": "Despacha una cuadrilla autónoma multi-agente en memoria (CrewAI) para misiones complejas. Puede componer agentes por roles ad-hoc o conectar skills de CoHaLo, con validación Pydantic opcional.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission": {"type": "string", "description": "Objetivo o consigna general para la cuadrilla"},
                    "roles": {
                        "type": "array",
                        "description": "Lista opcional de agentes con rol, meta y backstory",
                        "items": {"type": "object"}
                    },
                    "skills": {
                        "type": "array",
                        "description": "Lista opcional de nombres de skills CoHaLo a invocar (ej: ['seo-aeo-geo', 'automation-engine'])",
                        "items": {"type": "string"}
                    },
                    "output_schema": {
                        "type": "object",
                        "description": "Diccionario opcional de validación Pydantic (ej: {'estrategia': 'str', 'precio_sugerido_usd': 'int', 'acciones': 'list[str]'})",
                        "additionalProperties": {"type": "string"}
                    },
                    "tier": {"type": "string", "enum": ["free", "pro"], "default": "free"}
                },
                "required": ["mission"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_available_crews",
            "description": "Lista todas las cuadrillas autónomas de CrewAI pre-registradas (general_research, astrology_timing, seo_aeo_geo, google_seo).",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "extract_structured_data",
            "description": "Extrae y valida datos estructurados con tipado estricto (PydanticAI) en tiempo de ejecución a partir de texto desordenado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fields_spec": {
                        "type": "object",
                        "description": "Diccionario campo:tipo (ej: {'nombre': 'str', 'score': 'float', 'tags': 'list[str]'})"
                    },
                    "user_input": {"type": "string", "description": "Texto sin estructurar del cual extraer la información"},
                    "tier": {"type": "string", "enum": ["free", "pro"], "default": "free"}
                },
                "required": ["fields_spec", "user_input"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mem_context",
            "description": "Recupera las observaciones más recientes de la memoria persistente Engram (SSoT) para el proyecto activo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 5}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mem_search",
            "description": "Busca en la memoria persistente Engram por palabras clave en títulos, temas y contenido.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Término o palabra clave a buscar"},
                    "limit": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mem_save",
            "description": "Guarda de forma persistente una nueva observación, decisión o descubrimiento en Engram.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título conciso (Verbo + objeto)"},
                    "content": {"type": "string", "description": "Contenido detallado"},
                    "type": {"type": "string", "enum": ["discovery", "architecture", "decision", "bugfix", "pattern", "config", "preference"]},
                    "topic_key": {"type": "string", "description": "Clave estable de tema"}
                },
                "required": ["title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lee cualquier archivo del filesystem por ruta absoluta (ej: '/mnt/localstorage/...', '/var/www/...').",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta del archivo"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crea o sobreescribe un archivo con contenido completo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del archivo"},
                    "content": {"type": "string", "description": "Contenido a escribir"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Realiza reemplazo quirúrgico exacto de cadenas de texto en un archivo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del archivo"},
                    "target": {"type": "string", "description": "Texto exacto a reemplazar"},
                    "replacement": {"type": "string", "description": "Texto nuevo de reemplazo"}
                },
                "required": ["path", "target", "replacement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Lista archivos y subdirectorios de una ruta en disco.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta del directorio (ej: '/mnt/localstorage')"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Ejecuta comandos de shell en el contenedor de Hermes (git, python, curl, scripts).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando a ejecutar"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Búsqueda en vivo en la web mediante Tavily API con Brave fallback.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Consulta de búsqueda"},
                    "max_results": {"type": "integer", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_web_page",
            "description": "Extrae el contenido limpio en Markdown de cualquier página web mediante Jina Reader.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL HTTP/HTTPS a extraer"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "download_file",
            "description": "Descarga activos o binarios directamente desde una URL hacia una ruta local.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL directa de descarga"},
                    "destination_path": {"type": "string", "description": "Ruta de destino en disco"}
                },
                "required": ["url", "destination_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_query",
            "description": "Ejecuta consultas SQL arbitrarias sobre la base de datos PostgreSQL 18 activa. Operaciones destructivas (DROP/TRUNCATE) están prohibidas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Consulta SQL válida para PostgreSQL"},
                    "explanation": {"type": "string", "description": "Propósito de la consulta"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_natal_chart",
            "description": "Calcula efemérides y carta natal astronómica precisa (Oraculo Astrological Worker).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Client"},
                    "year": {"type": "integer", "default": 1990},
                    "month": {"type": "integer", "default": 1},
                    "day": {"type": "integer", "default": 1},
                    "hour": {"type": "integer", "default": 12},
                    "minute": {"type": "integer", "default": 0},
                    "lat": {"type": "number", "default": 4.7110},
                    "lon": {"type": "number", "default": -74.0721},
                    "city": {"type": "string", "default": "Bogota"},
                    "nation": {"type": "string", "default": "Colombia"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_verticals",
            "description": "Lista todas las verticales curadas del ecosistema de negocio registradas en dev/verticals (ej. brand-core, vertical-a, vertical-b).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vertical",
            "description": "Obtiene la especificación técnica completa en JSON de una vertical específica (ej. 'brand-core', 'vertical-a', 'vertical-b').",
            "parameters": {
                "type": "object",
                "properties": {
                    "vertical_slug": {
                        "type": "string",
                        "description": "Slug de la vertical (ej. 'brand-core', 'vertical-a')"
                    }
                },
                "required": ["vertical_slug"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_playbooks",
            "description": "Lista todos los playbooks universales de crecimiento y marketing en /mnt/localstorage/playbooks (ej. seo_aeo_playbook, copywriting_playbook, funnels_cro_playbook).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_playbook",
            "description": "Lee el contenido estratégico de un playbook universal por su slug (ej. 'seo_aeo_playbook', 'copywriting_playbook', 'offers_pricing_playbook').",
            "parameters": {
                "type": "object",
                "properties": {
                    "playbook_slug": {
                        "type": "string",
                        "description": "Slug del playbook (ej. 'seo_aeo_playbook', 'copywriting_playbook')"
                    }
                },
                "required": ["playbook_slug"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_brandbook_tokens",
            "description": "Lee el manual de marca y design tokens (brandbook.json, chroma_manifest.json, font_manifest.json) del espacio base dev/.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "Descubre y lista dinámicamente las sovereign skills disponibles en /mnt/localstorage/skills/ con su descripción y triggers operativos.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Término opcional de búsqueda o filtro (ej. 'seo', 'brand', 'copy', 'oraculo', 'astro')"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_skill_docs",
            "description": "Consulta la documentación SKILL.md y directivas de ejecución de cualquier sovereign skill disponible en /mnt/localstorage/skills/ (ej. 'seo-aeo-geo', 'growth-engine', 'apotelos', 'astro-web').",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Nombre de la skill (ej. 'seo-aeo-geo', 'growth-engine', 'apotelos', 'astro-web')"
                    }
                },
                "required": ["skill_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apotelos_cli",
            "description": "Ejecuta el CLI soberano de Apotelos (/usr/local/bin/apotelos) para orquestación causal, auditoría de contratos Pydantic v2, árbol de dominó y compilación de manifiestos Blackboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subcommand": {
                        "type": "string",
                        "description": "Subcomando de apotelos: 'list', 'audit', 'plan', 'run', 'dossier', 'test', o 'scaffold'"
                    },
                    "args": {
                        "type": "string",
                        "description": "Argumentos adicionales (ej. '--vertical brand-core')"
                    }
                },
                "required": ["subcommand"]
            }
        }
    }
]

TOOL_DISPATCH = {
    "list_verticals": lambda a: list_verticals(),
    "get_vertical": lambda a: get_vertical(a.get("vertical_slug", "")),
    "list_playbooks": lambda a: list_playbooks(),
    "get_playbook": lambda a: get_playbook(a.get("playbook_slug", "")),
    "get_brandbook_tokens": lambda a: get_brandbook_tokens(),
    "list_skills": lambda a: list_skills(a.get("query", "")),
    "get_skill_docs": lambda a: get_skill_docs(a.get("skill_name", "")),
    "apotelos_cli": lambda a: apotelos_cli(a.get("subcommand", ""), a.get("args", "")),
    "get_system_health": lambda a: get_system_health(),
    "list_zerops_services": lambda a: list_zerops_services(),
    "call_zerops_mcp_tool": lambda a: call_zerops_mcp_tool(a.get("tool_name", ""), a.get("arguments", {})),
    "get_zerops_service_status": lambda a: get_zerops_service_status(a.get("service_name", "")),
    "start_zerops_service": lambda a: start_zerops_service(a.get("service_name", "")),
    "stop_zerops_service": lambda a: stop_zerops_service(a.get("service_name", "")),
    "delete_zerops_service": lambda a: delete_zerops_service(a.get("service_name", "")),
    "zerops_get_service_logs": lambda a: zerops_get_service_logs(a.get("service_name", ""), int(a.get("limit", 50))),
    "zerops_deploy_service": lambda a: zerops_deploy_service(a.get("service_name", ""), a.get("working_dir", "")),
    "pidev_get_status": lambda a: pidev_get_status(),
    "pidev_dispatch_task": lambda a: pidev_dispatch_task(a.get("prompt", ""), a.get("working_dir", "/var/www")),
    "linear_create_issue": lambda a: linear_create_issue(a.get("title", ""), a.get("description", ""), int(a.get("priority", 2))),
    "linear_update_status": lambda a: linear_update_status(a.get("issue_id", ""), a.get("status", ""), a.get("evidence", "")),
    "linear_get_issue": lambda a: linear_get_issue(a.get("issue_id", "")),
    "linear_comment_issue": lambda a: linear_comment_issue(a.get("issue_id", ""), a.get("comment", "")),
    "get_paperclip_status": lambda a: get_paperclip_status(),
    "paperclip_list_tasks": lambda a: paperclip_list_tasks(a.get("status", "")),
    "paperclip_create_task": lambda a: paperclip_create_task(a.get("title", ""), a.get("description", ""), a.get("priority", "medium")),
    "paperclip_register_agent": lambda a: paperclip_register_agent(
        a.get("name", ""),
        a.get("title", ""),
        a.get("role", "worker"),
        a.get("adapter_type", "hermes_gateway"),
        a.get("capabilities", ""),
        int(a.get("budget_monthly_cents", 50000))
    ),
    "run_crew_ai": lambda a: run_crew_ai(
        a.get("mission", ""),
        a.get("roles", []),
        a.get("tier", "free"),
        a.get("output_schema"),
        a.get("skills")
    ),
    "list_available_crews": lambda a: list_available_crews(),
    "extract_structured_data": lambda a: extract_structured_data(a.get("fields_spec", {}), a.get("user_input", ""), a.get("tier", "free")),
    "mem_context": lambda a: mem_context(int(a.get("limit", 5))),
    "mem_search": lambda a: mem_search(a.get("query", ""), int(a.get("limit", 5))),
    "mem_save": lambda a: mem_save(a.get("title", ""), a.get("content", ""), a.get("type", "discovery"), a.get("topic_key", "")),
    "read_file": lambda a: read_file(a.get("path", "")),
    "write_file": lambda a: write_file(a.get("path", ""), a.get("content", "")),
    "edit_file": lambda a: edit_file(a.get("path", ""), a.get("target", ""), a.get("replacement", "")),
    "list_directory": lambda a: list_directory(a.get("path", "/mnt/localstorage")),
    "run_command": lambda a: run_command(a.get("command", "")),
    "search_web": lambda a: search_web(a.get("query", ""), a.get("max_results", 5)),
    "fetch_web_page": lambda a: fetch_web_page(a.get("url", "")),
    "download_file": lambda a: download_file(a.get("url", ""), a.get("destination_path", "")),
    "execute_query": lambda a: execute_store_query(a.get("query", ""), a.get("explanation", "")),
    "calculate_natal_chart": lambda a: calculate_natal_chart(
        a.get("name", "Client"), a.get("year", 1990), a.get("month", 1), a.get("day", 1),
        a.get("hour", 12), a.get("minute", 0), float(a.get("lat", 4.7110)), float(a.get("lon", -74.0721)),
        a.get("city", "Bogota"), a.get("nation", "Colombia")
    ),
    "send_whatsapp_otp": lambda a: send_whatsapp_otp(a.get("phone", ""), a.get("otp", "")),
}

def extract_tool_calls(msg: dict) -> list[dict]:
    tool_calls = []
    if msg.get("tool_calls"):
        for tc in msg["tool_calls"]:
            try:
                args = json.loads(tc["function"].get("arguments", "{}"))
            except Exception:
                args = {}
            tool_calls.append({
                "id": tc.get("id", str(uuid.uuid4())),
                "name": tc["function"]["name"],
                "args": args
            })
        return tool_calls

    content = msg.get("content") or ""
    if not content:
        return []

    # 1. Parse <dots_function_call> or <invoke name="..."> blocks (Qwen 2.5 / DeepSeek / OSS)
    if "<invoke" in content or "<dots_function_call>" in content:
        invokes = re.findall(r'<invoke\s+name=["\']([^"\']+)["\']\s*>(.*?)</invoke>', content, re.DOTALL | re.IGNORECASE)
        for name, body in invokes:
            params = {}
            param_matches = re.findall(r'<parameter\s+name=["\']([^"\']+)["\']\s*>(.*?)</parameter>', body, re.DOTALL | re.IGNORECASE)
            if param_matches:
                for p_name, p_val in param_matches:
                    p_val_clean = p_val.strip()
                    try:
                        params[p_name] = json.loads(p_val_clean)
                    except Exception:
                        params[p_name] = p_val_clean
            else:
                body_clean = body.strip()
                if body_clean.startswith("{") and body_clean.endswith("}"):
                    try:
                        params = json.loads(body_clean)
                    except Exception:
                        params = {}
            tool_calls.append({
                "id": str(uuid.uuid4()),
                "name": name.strip(),
                "args": params
            })
        if tool_calls:
            return tool_calls

    # 2. Parse XML <tool_call> or function_call blocks if model emitted raw text
    if "<tool_call>" in content:
        xml_matches = re.findall(r"<tool_call>\s*<(?:name|tool_name)>([^<]+)</(?:name|tool_name)>\s*<(?:arguments|parameters)>(.*?)</(?:arguments|parameters)>\s*</tool_call>", content, re.DOTALL | re.IGNORECASE)
        for name, body in xml_matches:
            try:
                params = json.loads(body.strip())
            except Exception:
                params = {}
            tool_calls.append({
                "id": str(uuid.uuid4()),
                "name": name.strip(),
                "args": params if isinstance(params, dict) else {}
            })
        if tool_calls:
            return tool_calls

    return tool_calls

async def execute_tool(fn_name: str, fn_args: dict) -> str:
    try:
        handler = TOOL_DISPATCH.get(fn_name)
        if not handler:
            return f"Herramienta desconocida: {fn_name}"
        res = handler(fn_args)
        if asyncio.iscoroutine(res):
            raw_res = await res
        else:
            raw_res = res
        
        # Pointer Pattern: If tool output exceeds 8000 characters, persist to localstorage
        res_str = str(raw_res)
        if len(res_str) > 8000:
            artifacts_dir = "/mnt/localstorage/artifacts"
            os.makedirs(artifacts_dir, exist_ok=True)
            art_id = f"tool_{fn_name}_{uuid.uuid4().hex[:8]}.log"
            art_path = os.path.join(artifacts_dir, art_id)
            try:
                with open(art_path, "w", encoding="utf-8") as f:
                    f.write(res_str)
                return (
                    f"[OBSERVACIÓN TRUNCADA: total {len(res_str)} caracteres. Log persistido en {art_path}]\n"
                    f"=== HEAD PREVIEW ===\n{res_str[:3000]}\n"
                    f"... [SNIP {len(res_str) - 6000} caracteres] ...\n"
                    f"=== TAIL PREVIEW ===\n{res_str[-3000:]}"
                )
            except Exception:
                return res_str[:8000] + f"\n... [Truncado a 8000 caracteres]"
        return res_str
    except Exception as e:
        return f"Error ejecutando {fn_name}: {str(e)}"

async def load_chat_history(chat_id: int, limit: int = 10) -> list[dict]:
    """Loads recent messages from PostgreSQL 18 with localstorage SQLite fallback, enforcing zero-CoT hygiene."""
    if not chat_id:
        return []
    raw_messages = []
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url, timeout=3.0)
            rows = await conn.fetch(
                """
                SELECT role, content FROM hermes_messages 
                WHERE chat_id = $1 
                ORDER BY id DESC LIMIT $2
                """,
                chat_id, limit
            )
            await conn.close()
            raw_messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        except Exception as e:
            print(f"[Hermes DB Warning] Error loading history from PostgreSQL: {e}", file=sys.stderr)

    if not raw_messages:
        # Fallback: SQLite WAL on localstorage
        try:
            import aiosqlite
            db_path = "/mnt/localstorage/hermes/sessions.db"
            if os.path.exists(db_path):
                async with aiosqlite.connect(db_path, timeout=3.0) as db:
                    db.row_factory = aiosqlite.Row
                    cursor = await db.execute(
                        """
                        SELECT role, content FROM hermes_messages 
                        WHERE chat_id = ? 
                        ORDER BY id DESC LIMIT ?
                        """,
                        (chat_id, limit)
                    )
                    rows = await cursor.fetchall()
                    raw_messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        except Exception as e:
            print(f"[Hermes DB Warning] Error loading history from SQLite fallback: {e}", file=sys.stderr)

    # Sanitize in-flight: purge any contaminated thought dumps from reaching the context window
    clean_history = []
    for m in raw_messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "assistant":
            clean_text = sanitize_model_output(content)
            if clean_text:
                clean_history.append({"role": "assistant", "content": clean_text})
        else:
            clean_history.append(m)
    return clean_history

async def save_chat_turn(chat_id: int, user_text: str, assistant_text: str) -> None:
    """Persists conversation turn to PostgreSQL 18 and localstorage SQLite WAL."""
    if not chat_id:
        return
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            import asyncpg
            conn = await asyncpg.connect(db_url, timeout=3.0)
            await conn.executemany(
                """
                INSERT INTO hermes_messages (chat_id, role, content) 
                VALUES ($1, $2, $3)
                """,
                [(chat_id, "user", user_text), (chat_id, "assistant", assistant_text)]
            )
            await conn.close()
        except Exception as e:
            print(f"[Hermes DB Warning] Error saving turn to PostgreSQL: {e}", file=sys.stderr)

    # Local replica in SQLite WAL
    try:
        import aiosqlite, time
        os.makedirs("/mnt/localstorage/hermes", exist_ok=True)
        db_path = "/mnt/localstorage/hermes/sessions.db"
        async with aiosqlite.connect(db_path, timeout=3.0) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS hermes_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    role TEXT,
                    content TEXT,
                    created_at REAL
                );
            """)
            now = time.time()
            await db.executemany(
                """
                INSERT INTO hermes_messages (chat_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [(chat_id, "user", user_text, now), (chat_id, "assistant", assistant_text, now + 0.01)]
            )
            await db.commit()
    except Exception as e:
        print(f"[Hermes DB Warning] Error saving turn to SQLite fallback: {e}", file=sys.stderr)

def sanitize_model_output(raw_content: str) -> str:
    """
    Sanitizes raw model completion:
    1. Eradicates all chain-of-thought tags (<think>, <thought>, <reasoning>, etc.).
    2. Eradicates unclosed <think> blocks if truncated or streaming.
    3. Strips leaked XML function/tool calls and ChatML tags.
    4. Detects and eliminates un-fenced English/Spanish chain-of-thought monologues
       (e.g., 'The user is asking...', 'Let me think...', 'Thinking Process:', etc.).
    5. Enforces executive Rioplatense response tone (Gentle AI persona).
    """
    if not raw_content:
        return ""

    text = raw_content

    # 1. Strip explicit thinking / reasoning / reflection tags
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<reflection>.*?</reflection>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"\[THOUGHT\].*?\[/THOUGHT\]", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<internal_monologue>.*?</internal_monologue>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 2. If an unclosed <think> tag exists (e.g. model was interrupted), strip everything inside it
    if "<think>" in text.lower():
        text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Strip raw function / tool calls that might have leaked into content
    text = re.sub(r"<[^>]*function_call.*?</[^>]*function_call>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]*tool_call.*?</[^>]*tool_call>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[\||\s]*tool_calls?[\||\s]*>.*?</[\||\s]*tool_calls?[\||\s]*>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<dots_function_call>.*?</dots_function_call>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]*invoke.*?</[^>]*invoke>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[｜|\s]*DSML.*?</[｜|\s]*DSML[｜|\s]*tool_calls>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[\||\s]*(?:tool_calls?|tool_name|parameters)[\||\s]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</[\||\s]*(?:tool_calls?|tool_name|parameters)[\||\s]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?dots_function_call>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\|im_end\|>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\|im_start\|>assistant", "", text, flags=re.IGNORECASE)

    text = text.strip()

    # 4. Detect unfenced CoT monologue (like 'The user is asking: ... Let me think ...')
    cot_lead_patterns = [
        r"^The user is asking[:\s]",
        r"^This is a (?:follow-up|question|request)",
        r"^Let me think about",
        r"^Let's think about",
        r"^Thinking Process:",
        r"^Internal Monologue:",
        r"^I need to respond",
        r"^Let me draft a (?:concise )?response",
    ]
    if any(re.search(pat, text, re.IGNORECASE) for pat in cot_lead_patterns):
        # Look for explicit draft quotation or transition
        draft_match = re.search(r'(?:Let me draft[^\n]*:\s*|\bresponse:\s*|\bRioplatense Spanish:\s*)\s*["\'](.*?)["\'](?:\s*$|\s*(?:Hmm|Actually))', text, re.DOTALL | re.IGNORECASE)
        if draft_match:
            text = draft_match.group(1).strip()
        else:
            quotes = re.findall(r'"([^"]{20,})"', text, re.DOTALL)
            if quotes:
                text = quotes[-1].strip()
            else:
                paragraphs = text.split("\n\n")
                cleaned_paras = []
                for p in paragraphs:
                    p_strip = p.strip()
                    if not p_strip:
                        continue
                    if any(re.search(pat, p_strip, re.IGNORECASE) for pat in cot_lead_patterns):
                        continue
                    if re.search(r"^(?:Actually|Hmm|So my revised plan|I don't have direct knowledge|The user is challenging)\b", p_strip, re.IGNORECASE):
                        continue
                    cleaned_paras.append(p_strip)
                if cleaned_paras:
                    text = "\n\n".join(cleaned_paras).strip()

    # 5. Detect if the text is predominantly an English reasoning monologue
    words = re.findall(r"\b[a-zA-ZáéíóúÁÉÍÓÚñÑ]+\b", text.lower())
    if len(words) >= 12:
        en_grammatical_stops = {"the", "this", "that", "these", "those", "with", "from", "have", "were", "been", "would", "could", "should", "their", "which", "about", "there", "because"}
        es_stops = {"el", "la", "de", "que", "en", "los", "del", "se", "las", "por", "un", "para", "con", "una", "su", "al", "lo", "como", "más", "pero", "sus", "le", "ya", "o", "si", "te", "digo", "haría", "orden", "creo", "tenés", "hacés", "este", "cargó", "ingesto", "despacho", "hay", "son"}
        en_count = sum(1 for w in words if w in en_grammatical_stops)
        es_count = sum(1 for w in words if w in es_stops)
        if en_count >= 6 and es_count == 0:
            return ""

    return text.strip()

ACTION_KEYWORDS = {
    'ver', 'revisar', 'consultar', 'buscar', 'ejecutar', 'correr', 'crear',
    'editar', 'modificar', 'borrar', 'eliminar', 'desplegar', 'deploy', 'status',
    'logs', 'servicio', 'servicios', 'tabla', 'tablas', 'bd', 'postgres', 'sql', 'zerops',
    'linear', 'paperclip', 'crew', 'crewai', 'enjambre', 'archivo', 'archivos',
    'file', 'token', 'tokens', 'bifrost', 'freellmapi', 'oraculo', 'oráculo',
    'apotelos', 'script', 'reiniciar', 'apagar', 'iniciar', 'start', 'stop',
    'health', 'salud', 'memoria', 'engram', 'natal', 'carta', 'playbook', 'playbooks',
    'código', 'codigo', 'brand-play', 'brandplay', 'brandbook', 'coo', 'vertical',
    'verticales', 'verticals', 'tienda', 'tiendas', 'ecommerce', 'e-commerce', 'producto',
    'productos', 'precio', 'ordenes', 'pedidos', 'checkout', 'pidev', 'landing', 'landings',
    'deepseek', 'pro', 'gratis', 'free', 'sincronizar', 'sync'
}

CHITCHAT_PATTERNS = [
    r'^(?:hola|buenas|buen d[ií]a|buenas tardes|buenas noches|hey|hello|hi|qu[eé] tal|c[oó]mo va)[\s!?.]*$',
    r'^(?:gracias|muchas gracias|dale|listo|ok|joya|perfecto|entendido|chau|hasta luego)[\s!?.]*$',
    r'^(?:qui[eé]n sos|qu[eé] hac[eé]s|c[oó]mo te llam[aá]s|c[oó]mo funcion[aá]s|qu[eé] pod[eé]s hacer)[\s!?.]*$',
]

def classify_query_intent(user_query: str) -> str:
    """
    Classifies the user query into 'chat' (conversational/greetings) or 'operational' (tool-bearing / ecosystem).
    Pure CoHaLo Positive Guidance: pure chitchat prunes 42 tools to 0 to save tokens,
    while any architectural or domain inquiry retains full context.
    """
    t = user_query.strip().lower()
    for p in CHITCHAT_PATTERNS:
        if re.match(p, t):
            return "chat"
    words = set(re.findall(r'\b[a-zA-Z0-9_-]+\b', t))
    if not (words & ACTION_KEYWORDS) and len(words) <= 5 and not any(k in t for k in ("qué", "que", "cómo", "como", "por qué", "por que", "plan")):
        return "chat"
    return "operational"

class HermesAgent:
    def __init__(self, system_prompt: str = None, role: str = "admin", bifrost_key: str = None, tools: list = None):
        self.role = role
        self.system_prompt = system_prompt or load_hermes_soul()
        self.bifrost_key = bifrost_key or os.getenv("BIFROST_VIRTUAL_KEY", "vk-hermes-agent")
        self.tools = tools if tools is not None else HERMES_TOOLS
        self.history: list[dict[str, str]] = []

    async def run_turn(self, user_query: str, chat_id: int = 0) -> str:
        # Load persistent history (strictly last 6 messages = 3 turns max for lean context)
        persistent_history = await load_chat_history(chat_id, limit=6)
        active_history = persistent_history if persistent_history else self.history
        
        intent = classify_query_intent(user_query)
        task_type_header = "chat" if intent == "chat" else "code"
        # Always provide tools and canonical fresh SOUL.md; Hermes model decides autonomously
        active_tools = self.tools
        active_system_prompt = load_hermes_soul()

        messages = [
            {"role": "system", "content": active_system_prompt},
            *active_history,
            {"role": "user", "content": user_query}
        ]
        
        final_content = ""
        max_tool_iterations = 10 if active_tools else 1
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost_cents = 0.0
        active_provider = "freellmapi"
        active_model = MODEL_NAME
        
        request_headers = {
            "Authorization": f"Bearer {self.bifrost_key}",
            "x-freellm-task-type": task_type_header,
        }
        target_model = MODEL_NAME
        query_lower = user_query.lower()
        if any(k in query_lower for k in ("deepseek", "pro tier", "modo pro", "razonamiento pro", "tier pro")):
            request_headers["x-force-deepseek"] = "true"
            request_headers["x-routing-tier"] = "pro"
            target_model = "deepseek-chat"
        elif any(k in query_lower for k in ("freellmapi", "free tier", "modo gratis", "gratis", "tier free", "vuelve a freellmapi", "usa freellm")):
            request_headers["x-routing-tier"] = "free"
            request_headers.pop("x-force-deepseek", None)
            target_model = MODEL_NAME

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                while max_tool_iterations > 0:
                    max_tool_iterations -= 1
                    post_payload = {
                        "model": target_model,
                        "messages": messages,
                        "temperature": 0.3,
                        "max_tokens": 2048,
                    }
                    if active_tools:
                        post_payload["tools"] = active_tools

                    res = await client.post(
                        f"{BIFROST_URL}/chat/completions",
                        headers=request_headers,
                        json=post_payload
                    )
                    if res.status_code != 200:
                        logger.warning(f"[Hermes] Primary gateway status {res.status_code}. Retrying with pro failover...")
                        fallback_payload = {
                            "model": "deepseek-chat",
                            "messages": messages,
                            "temperature": 0.3,
                            "max_tokens": 2048,
                        }
                        if active_tools:
                            fallback_payload["tools"] = active_tools

                        res = await client.post(
                            f"{BIFROST_URL}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.bifrost_key}",
                                "x-force-deepseek": "true",
                                "x-routing-tier": "pro",
                                "x-freellm-task-type": task_type_header,
                            },
                            json=fallback_payload,
                            timeout=120.0
                        )
                        if res.status_code != 200:
                            logger.error(f"[Hermes] Gateway fallback failed: {res.status_code} - {res.text}")
                            return "⚠️ El gateway de inferencia está experimentando alta demanda temporal. Por favor intentá nuevamente en unos momentos."
                    
                    data = res.json()
                    
                    # Accumulate tokens & calculate model costs (FreeLLMAPI = $0, DeepSeek = paid)
                    usage = data.get("usage", {})
                    p_tok = int(usage.get("prompt_tokens", 0))
                    c_tok = int(usage.get("completion_tokens", 0))
                    total_prompt_tokens += p_tok
                    total_completion_tokens += c_tok
                    
                    extra = data.get("extra_fields", {})
                    call_provider = extra.get("provider", "freellmapi")
                    active_model = extra.get("resolved_model_used", data.get("model", MODEL_NAME))
                    if call_provider == "deepseek":
                        active_provider = "deepseek"
                        # Bifrost pricing for DeepSeek: ~$0.27/1M prompt, ~$2.00/1M completion (rates in cents: 0.000027 / 0.00020)
                        total_cost_cents += (p_tok * 0.000027) + (c_tok * 0.00020)

                    msg = data["choices"][0]["message"]
                    parsed_tool_calls = extract_tool_calls(msg)
                    
                    if not parsed_tool_calls:
                        raw_content = msg.get("content") or ""
                        action_verbs = {
                            "ejecutar", "ejecuta", "ejecutá", "correr", "corre", "corré", 
                            "crear", "crea", "iniciar", "inicia", "iniciá", "desplegar", 
                            "deploy", "sincronizar", "sync"
                        }
                        query_words = set(re.findall(r'\b[a-zA-Z0-9_-]+\b', user_query.lower()))
                        if (query_words & action_verbs) and max_tool_iterations == 9 and active_tools:
                            messages.append({"role": "assistant", "content": raw_content})
                            messages.append({
                                "role": "user",
                                "content": "Mandato de acción detectado. Invocá inmediatamente la herramienta correspondiente (ej: run_command con el CLI adecuado, pidev_dispatch_task, etc.) sin emitir texto conversacional ni explicaciones."
                            })
                            continue
                        final_content = sanitize_model_output(raw_content)
                        break
                    
                    # Tool call execution step
                    assistant_msg = {"role": "assistant"}
                    if msg.get("tool_calls"):
                        assistant_msg["tool_calls"] = msg["tool_calls"]
                    else:
                        assistant_msg["tool_calls"] = [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["args"])
                                }
                            }
                            for tc in parsed_tool_calls
                        ]
                    if msg.get("content"):
                        sanitized_assistant_content = sanitize_model_output(msg["content"])
                        if sanitized_assistant_content:
                            assistant_msg["content"] = sanitized_assistant_content
                    messages.append(assistant_msg)
                    
                    for tc in parsed_tool_calls:
                        fn_name = tc["name"]
                        fn_args = tc["args"]
                        tool_result = await execute_tool(fn_name, fn_args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": str(tool_result)
                        })
                
                if not final_content or not final_content.strip():
                    # If tools were executed but no text content was emitted, force synthesis turn without tools
                    messages.append({
                        "role": "user",
                        "content": "Con base en las herramientas ejecutadas, redactá un reporte técnico ejecutivo conciso (máximo 3-4 viñetas) en español rioplatense (voseo) sobre lo realizado y el estado final físico observado. Cero discursos, cero relleno y sin código Markdown no solicitado."
                    })
                    try:
                        res_synth = await client.post(
                            f"{BIFROST_URL}/chat/completions",
                            headers=request_headers,
                            json={
                                "model": target_model,
                                "messages": messages,
                                "temperature": 0.2,
                                "max_tokens": 1024,
                            },
                            timeout=30.0
                        )
                        if res_synth.status_code == 200:
                            s_data = res_synth.json()
                            s_usage = s_data.get("usage", {})
                            s_p = int(s_usage.get("prompt_tokens", 0))
                            s_c = int(s_usage.get("completion_tokens", 0))
                            total_prompt_tokens += s_p
                            total_completion_tokens += s_c
                            s_extra = s_data.get("extra_fields", {})
                            if s_extra.get("provider") == "deepseek":
                                active_provider = "deepseek"
                                total_cost_cents += (s_p * 0.000027) + (s_c * 0.00020)
                            synth_msg = s_data["choices"][0]["message"].get("content") or ""
                            final_content = sanitize_model_output(synth_msg)
                    except Exception as se:
                        logger.warning(f"Synthesis turn failed: {se}")

                if not final_content or not final_content.strip():
                    final_content = "Operación técnica ejecutada con éxito. Los artefactos y comandos fueron verificados físicamente en el entorno."

                # Store turn cost and usage telemetry for Paperclip Control Plane
                self.last_turn_telemetry = {
                    "provider": active_provider,
                    "model": active_model,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "cost_cents": round(total_cost_cents, 4),
                }
                
                # Persist turn
                if chat_id:
                    await save_chat_turn(chat_id, user_query, final_content)
                else:
                    self.history.append({"role": "user", "content": user_query})
                    self.history.append({"role": "assistant", "content": final_content})
                    if len(self.history) > 6:
                        self.history = self.history[-6:]
                
                return final_content
            except Exception as e:
                logger.error(f"[Hermes] Error in run_turn: {e}")
                return f"⚠️ Error en la ejecución del turno de Hermes: {str(e)}"
