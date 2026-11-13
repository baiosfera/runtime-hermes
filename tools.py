"""
Hermes-Agent Execution Tools
Sovereign Integration Mesh: Connects Hermes-Agent to PostgreSQL 18, NATS JetStream, and the AstroBranding Central Engine.
"""
import os
import re
import sys
import time
import signal
import subprocess
import json
import uuid
import httpx
from typing import Dict, Any, Optional

try:
    from env_utils import clean_env
except (ImportError, ValueError):
    from .env_utils import clean_env

API_BASE = clean_env("API_BASE_URL", "http://astrobranding:3000")
DATABASE_URL = clean_env("DATABASE_URL")
NATS_URL = clean_env("NATS_URL") or clean_env("ZCP_NATS_URL", "nats://nats:4222")

async def get_system_health() -> dict:
    """Check health across mesh components"""
    health = {
        "service": "hermes-agent",
        "status": "autonomous",
        "mesh": {}
    }
    targets = {
        "bifrost": "http://bifrost:8080/healthz",
        "paperclip": "http://paperclip:3100/api/health",
        "freellmapi": "http://freellmapi:3001/"
    }
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in targets.items():
            try:
                r = await client.get(url)
                health["mesh"][name] = "ok" if r.status_code in (200, 401, 404) else f"status_{r.status_code}"
            except Exception as e:
                health["mesh"][name] = f"down: {str(e)[:50]}"
    return health

async def calculate_natal_chart(client_id: str, ayanamsha: str = "tropical") -> dict:
    """Calculate chart or trigger computation via internal engine"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                f"{API_BASE}/api/astrology/chart",
                json={"clientId": client_id, "ayanamsha": ayanamsha, "houseSystem": "placidus"}
            )
            return res.json()
        except Exception as e:
            return {"error": str(e)}

async def get_client_gold_feeds(client_id: str) -> dict:
    """Fetch XML Gold Feeds directly from PostgreSQL 18 or API fallback"""
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL)
            rows = await conn.fetch(
                "SELECT feed_name, feed_xml FROM client_feeds WHERE client_id = $1",
                uuid.UUID(client_id)
            )
            await conn.close()
            feeds = {row["feed_name"]: row["feed_xml"] for row in rows}
            return {"status": "ok", "client_id": client_id, "source": "postgres_direct", "feeds": feeds}
        except Exception as err:
            pass

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(f"{API_BASE}/api/v1/feeds/{client_id}")
            return res.json()
        except Exception as e:
            return {"error": str(e)}

async def query_client_dumps(client_id: str, shard_name: Optional[str] = None) -> dict:
    """Query 15-shard JSONB client dumps directly from PostgreSQL 18"""
    if not DATABASE_URL:
        return {"status": "error", "message": "DATABASE_URL not configured"}
    try:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        if shard_name:
            query = f"SELECT {shard_name} FROM client_dumps WHERE client_id = $1"
            row = await conn.fetchrow(query, uuid.UUID(client_id))
            await conn.close()
            return {
                "status": "ok",
                "client_id": client_id,
                "shard": shard_name,
                "data": json.loads(row[0]) if row and row[0] else None
            }
        else:
            row = await conn.fetchrow("SELECT * FROM client_dumps WHERE client_id = $1", uuid.UUID(client_id))
            await conn.close()
            return {"status": "ok", "client_id": client_id, "data": dict(row) if row else None}
    except Exception as err:
        return {"status": "error", "message": f"PostgreSQL query failed: {str(err)}"}

async def trigger_universal_extraction(birth_data: dict, dry_run: bool = False) -> dict:
    """Trigger or dispatch the 15-Shard Universal Extraction across federated astrology engines"""
    task_id = str(uuid.uuid4())
    payload = {
        "task_id": task_id,
        "action": "astrology.calculate.v1",
        "client": birth_data,
        "dry_run": dry_run
    }
    try:
        from nats.aio.client import Client as NATS
        nc = NATS()
        await nc.connect(NATS_URL)
        js = nc.jetstream()
        await js.publish(
            "astrology.requests",
            json.dumps(payload).encode("utf-8"),
            headers={"Nats-Msg-Id": task_id}
        )
        await nc.close()
        return {"status": "dispatched", "task_id": task_id, "message": "Astrological calculation queued on NATS."}
    except Exception:
        # Fallback to direct HTTP if NATS connection is unavailable
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res = await client.post(
                    f"{API_BASE}/api/v1/extract?dryRun={'true' if dry_run else 'false'}",
                    json=birth_data
                )
                return res.json()
            except Exception as e:
                return {"status": "error", "error": str(e)}

async def send_whatsapp_otp(phone: str, client_name: str) -> dict:
    """Send OTP via Evolution API or internal broker"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                f"{API_BASE}/api/whatsapp/otp",
                json={"phoneNumber": phone, "clientName": client_name, "template": "otp_verification"}
            )
            return res.json()
        except Exception as e:
            return {"error": str(e)}

# --- Zerops Control Plane & Platform Orchestration Tools (Native MCP Bridge) ---

def _clean_service_name(name: str) -> str:
    name = name.strip().lower()
    name = name.replace("/var/www/", "").strip("/")
    return name.split(".")[0]

def call_zerops_mcp_tool(tool_name: str, arguments: dict = None) -> str:
    """Invokes any native Zerops MCP tool (zerops_discover, zerops_import, zerops_deploy, zerops_scale, zerops_logs, etc.)."""
    import asyncio
    try:
        from mcp_bridge import call_zerops_mcp
    except ImportError:
        from hermes.mcp_bridge import call_zerops_mcp
    return asyncio.run(call_zerops_mcp(tool_name, arguments or {}))

def list_zerops_services() -> str:
    """Lists all active and configured services in the Zerops project via native MCP zerops_discover."""
    return call_zerops_mcp_tool("zerops_discover", {})

def zerops_get_service_logs(service_name: str, limit: int = 50) -> str:
    """Fetches recent runtime logs from a specific Zerops service container via native MCP zerops_logs."""
    clean = _clean_service_name(service_name)
    return call_zerops_mcp_tool("zerops_logs", {"serviceHostname": clean, "limit": limit})

def zerops_deploy_service(service_name: str, working_dir: str = "") -> str:
    """Triggers code deployment for a Zerops service using native MCP zerops_deploy."""
    clean = _clean_service_name(service_name)
    args = {"targetService": clean}
    if working_dir:
        args["workingDir"] = working_dir
    return call_zerops_mcp_tool("zerops_deploy", args)

def start_zerops_service(service_name: str) -> str:
    """Scales up/starts a Zerops service to 1 container via native MCP zerops_scale."""
    clean = _clean_service_name(service_name)
    return call_zerops_mcp_tool("zerops_scale", {"serviceHostname": clean, "minContainers": 1, "maxContainers": 1})

def stop_zerops_service(service_name: str) -> str:
    """Scales down/stops a Zerops service to 0 containers via native MCP zerops_scale."""
    clean = _clean_service_name(service_name)
    return call_zerops_mcp_tool("zerops_scale", {"serviceHostname": clean, "minContainers": 0, "maxContainers": 0})

def delete_zerops_service(service_name: str) -> str:
    """Deletes a Zerops service safely via native MCP zerops_delete."""
    clean = _clean_service_name(service_name)
    return call_zerops_mcp_tool("zerops_delete", {"serviceHostname": clean, "confirm": True})

def get_zerops_service_status(service_name: str) -> str:
    """Checks current status and reachability of a specific Zerops service."""
    clean = _clean_service_name(service_name)
    return call_zerops_mcp_tool("zerops_discover", {})

# --- PiDev & Gentle-Pi Coding Agent Tools ---

def pidev_get_status() -> str:
    """Checks the health, agent version, and operational readiness of the PiDev service."""
    import requests
    try:
        res = requests.get("http://pidev:3000/status", timeout=5)
        if res.status_code == 200:
            data = res.json()
            return (
                f"🟢 PiDev (Gentle-Pi) OPERATIVO:\n"
                f"• Versión: {data.get('version', 'gentle-shell')}\n"
                f"• Uptime: {data.get('uptime', 0):.1f}s\n"
                f"• Endpoint: http://pidev:3000"
            )
        return f"⚠️ PiDev respondió con código {res.status_code}: {res.text}"
    except Exception as e:
        return f"❌ PiDev no alcanzable en http://pidev:3000 ({str(e)})"

def pidev_dispatch_task(prompt: str, working_dir: str = "/var/www") -> str:
    """Dispatches a web/application coding task to Gentle-Pi in pidev."""
    import requests
    try:
        res = requests.post(
            "http://pidev:3000/execute",
            json={"prompt": prompt, "cwd": working_dir},
            timeout=180
        )
        if res.status_code == 200:
            data = res.json()
            output = data.get("output", "")
            stderr = data.get("stderr", "")
            return f"✅ Resultado de Gentle-Pi (pidev):\n{output}\n{('Advertencias: ' + stderr) if stderr else ''}"
        return f"❌ Error ejecutando en PiDev ({res.status_code}): {res.text}"
    except Exception as e:
        return f"❌ Error conectando a PiDev: {str(e)}"


def git_web_diff_branches(base_branch: str = "main", target_branch: str = "dev") -> str:
    """Compares two branches (e.g. 'main' and 'dev') and lists changed files and statistics."""
    if not os.path.exists(WEB_REPO_DIR):
        return "❌ Repositorio web no encontrado en /mnt/localstorage/web."
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=WEB_REPO_DIR, capture_output=True, timeout=10)
    except Exception:
        pass
    res = subprocess.run(["git", "diff", f"{base_branch}..{target_branch}", "--stat"], cwd=WEB_REPO_DIR, capture_output=True, text=True)
    if res.returncode == 0:
        output = res.stdout.strip()
        return output if output else f"Las ramas '{base_branch}' y '{target_branch}' están idénticas (sin diferencias)."
    return f"❌ Error en git diff: {res.stderr.strip()}"

# --- Universal AGY-Twin Engineering & File Tools ---

def read_file(path: str) -> str:
    """Reads any file in the workspace or localstorage (e.g. '/mnt/localstorage/...', or '/var/www/...')."""
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return f"❌ El archivo '{path}' no existe."
    if os.path.isdir(path):
        return f"❌ '{path}' es un directorio, usa list_directory."
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > 4000:
            return content[:4000] + f"\n... [Truncado: total {len(content)} caracteres]"
        return content
    except Exception as e:
        return f"❌ Error leyendo archivo: {str(e)}"

PROTECTED_PATH_PATTERNS = [
    re.compile(r'(\.git/|\.env\b|00-SUPREME-DIRECTIVE\.md|_handover)', re.IGNORECASE),
    re.compile(r'(/etc/|/var/run/|/usr/|/bin/)', re.IGNORECASE)
]

def validate_code_safety(path: str, new_content: str, allow_shrink: bool = False) -> Optional[str]:
    """Validates syntax and security invariants before modifying files on disk."""
    norm = os.path.normpath(path)
    for pat in PROTECTED_PATH_PATTERNS:
        if pat.search(norm):
            return f"❌ Violación de seguridad: Ruta protegida contra escritura: '{norm}'."

    # 1. AST syntax check for Python
    if norm.endswith(".py"):
        import ast
        try:
            ast.parse(new_content)
        except SyntaxError as e:
            return f"❌ Error de sintaxis Python bloqueado: {e.msg} en línea {e.lineno}."

    # 2. Syntax check for Shell
    elif norm.endswith((".sh", ".bash")):
        res = subprocess.run(["bash", "-n"], input=new_content, text=True, capture_output=True)
        if res.returncode != 0:
            return f"❌ Error de sintaxis Bash bloqueado: {res.stderr.strip()}."

    # 3. Anti-Wiping monotonicity check
    if os.path.exists(norm) and not allow_shrink:
        try:
            with open(norm, "r", encoding="utf-8", errors="ignore") as f:
                old_lines = f.readlines()
            new_lines = new_content.splitlines()
            if len(old_lines) > 50 and len(new_lines) < (len(old_lines) * 0.5):
                return (
                    f"❌ Bloqueado por Anti-Wiping: Intento de reducir '{norm}' de {len(old_lines)} a "
                    f"{len(new_lines)} líneas sin flag explícito de refactorización."
                )
        except Exception:
            pass

    return None

def write_file(path: str, content: str, allow_shrink: bool = False) -> str:
    """Creates or overwrites a file with syntax validation and anti-wiping safety."""
    path = os.path.normpath(path)
    safety_err = validate_code_safety(path, content, allow_shrink)
    if safety_err:
        return safety_err

    try:
        target_dir = os.path.dirname(path)
        os.makedirs(target_dir, exist_ok=True)
        temp_file = os.path.join(target_dir, f".tmp_{uuid.uuid4().hex[:8]}_{os.path.basename(path)}")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp_file, path)
        return f"✅ Archivo '{path}' guardado con éxito ({len(content)} bytes, sintaxis validada)."
    except Exception as e:
        return f"❌ Error escribiendo archivo: {str(e)}"

def edit_file(path: str, target: str, replacement: str, allow_shrink: bool = False) -> str:
    """Replaces exact target text with replacement text after AST validation."""
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return f"❌ El archivo '{path}' no existe."
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if target not in content:
            return f"❌ No se encontró el texto objetivo en '{path}'."
        new_content = content.replace(target, replacement)
        
        safety_err = validate_code_safety(path, new_content, allow_shrink)
        if safety_err:
            return safety_err

        target_dir = os.path.dirname(path)
        temp_file = os.path.join(target_dir, f".tmp_{uuid.uuid4().hex[:8]}_{os.path.basename(path)}")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(temp_file, path)
        return f"✅ Archivo '{path}' modificado con éxito (sintaxis validada)."
    except Exception as e:
        return f"❌ Error editando archivo: {str(e)}"

def list_directory(path: str = "/mnt/localstorage") -> str:
    """Lists files and folders inside any directory."""
    path = os.path.normpath(path)
    if not os.path.exists(path):
        return f"❌ La ruta '{path}' no existe."
    try:
        items = os.listdir(path)
        formatted = []
        for item in sorted(items)[:50]:
            full = os.path.join(path, item)
            is_dir = os.path.isdir(full)
            formatted.append(f"{'[DIR] ' if is_dir else '      '}{item}")
        return "\n".join(formatted) if formatted else "Directorio vacío."
    except Exception as e:
        return f"❌ Error listando directorio: {str(e)}"

INTERACTIVE_PROMPT_REGEX = re.compile(
    r'(\[y/n\]|\(yes/no\)|password\s*:|enter passphrase|do you want to continue\?)',
    re.IGNORECASE
)

def run_command(command: str) -> str:
    """Executes a bounded shell command with process group isolation, non-interactive env, and Pointer Pattern."""
    # Block destructive Git commands
    if re.search(r'git\s+push\s+.*(--force|-f)\b', command, re.IGNORECASE):
        return "❌ Violación de seguridad: 'git push --force' está estrictamente prohibido."
    if re.search(r'git\s+reset\s+--hard\b', command, re.IGNORECASE):
        return "❌ Violación de seguridad: 'git reset --hard' está estrictamente prohibido."

    env = dict(os.environ)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["CI"] = "true"
    env["TERM"] = "dumb"
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,  # Prevent interactive hangs
            preexec_fn=os.setsid,       # Process group isolation
            text=True,
            env=env
        )

        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            # Kill entire process group
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                time.sleep(0.5)
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
            return "❌ Error: El comando excedió el tiempo límite de 30 segundos y su grupo de procesos fue terminado."

        output = stdout.strip() if stdout else ""
        err = stderr.strip() if stderr else ""

        # Check for interactive prompt traps in output
        if INTERACTIVE_PROMPT_REGEX.search(output + "\n" + err):
            return f"❌ Advertencia de proceso interactivo detectada en salida. Ejecución abortada:\n{output[:500]}"

        combined = []
        if output:
            combined.append(output)
        if err:
            combined.append(f"STDERR:\n{err}")
        full_res = "\n".join(combined) if combined else "(Comando ejecutado con éxito sin salida)"

        # Pointer Pattern: If output > 6000 chars, persist full log to localstorage and return preview
        if len(full_res) > 6000:
            artifacts_dir = "/mnt/localstorage/artifacts"
            os.makedirs(artifacts_dir, exist_ok=True)
            art_id = f"cmd_out_{uuid.uuid4().hex[:8]}.log"
            art_path = os.path.join(artifacts_dir, art_id)
            with open(art_path, "w", encoding="utf-8") as f:
                f.write(full_res)
            return (
                f"[SALIDA TRUNCADA: total {len(full_res)} caracteres. Log completo en {art_path}]\n"
                f"=== HEAD (primeros 2500 caracteres) ===\n{full_res[:2500]}\n"
                f"... [SNIP {len(full_res) - 5000} caracteres] ...\n"
                f"=== TAIL (últimos 2500 caracteres) ===\n{full_res[-2500:]}"
            )

        return full_res
    except Exception as e:
        return f"❌ Error ejecutando comando: {str(e)}"

# --- Multi-Tier Internet Research & Asset Ingestion Tools (AGY Parity) ---

def search_web(query: str, max_results: int = 5) -> str:
    """Performs deep epistemic web search using Tavily API (with Brave API fallback). Returns titles, URLs, and snippets."""
    tavily_key = os.getenv("TAVILY_API_KEY")
    if tavily_key:
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    "https://api.tavily.com/search",
                    json={"query": query, "max_results": min(max_results, 8), "api_key": tavily_key}
                )
                if res.status_code == 200:
                    data = res.json()
                    results = data.get("results", [])
                    if not results:
                        return f"No se encontraron resultados en la web para: '{query}'."
                    formatted = [f"Resultados web para '{query}':"]
                    for i, r in enumerate(results, 1):
                        title = r.get("title", "Sin título")
                        url = r.get("url", "")
                        snippet = r.get("content", "").strip()[:300]
                        formatted.append(f"{i}. [{title}]({url})\n   {snippet}")
                    return "\n\n".join(formatted)
        except Exception:
            pass

    brave_key = os.getenv("BRAVE_API_KEY")
    if brave_key:
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": brave_key, "Accept": "application/json"},
                    params={"q": query, "count": min(max_results, 8)}
                )
                if res.status_code == 200:
                    data = res.json()
                    results = data.get("web", {}).get("results", [])
                    if not results:
                        return f"No se encontraron resultados en Brave Search para: '{query}'."
                    formatted = [f"Resultados web (Brave) para '{query}':"]
                    for i, r in enumerate(results, 1):
                        title = r.get("title", "Sin título")
                        url = r.get("url", "")
                        snippet = r.get("description", "").strip()[:300]
                        formatted.append(f"{i}. [{title}]({url})\n   {snippet}")
                    return "\n\n".join(formatted)
        except Exception as e:
            return f"❌ Error en búsqueda web: {str(e)}"

    return "❌ Error: Ni TAVILY_API_KEY ni BRAVE_API_KEY están disponibles en el entorno."

def fetch_web_page(url: str) -> str:
    """Fetches and parses any web page into clean readable Markdown using Jina Reader API."""
    jina_key = os.getenv("JINA_API_KEY")
    headers = {"Authorization": f"Bearer {jina_key}"} if jina_key else {}
    target_url = f"https://r.jina.ai/{url}"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            res = client.get(target_url, headers=headers)
            if res.status_code == 200:
                text = res.text.strip()
                if len(text) > 6000:
                    return text[:6000] + f"\n... [Contenido truncado: total {len(text)} caracteres]"
                return text if text else "Página web vacía o sin contenido extraíble."
            return f"❌ Error al consultar la página {url}: HTTP {res.status_code} - {res.text[:200]}"
    except Exception as e:
        return f"❌ Error al extraer contenido web de {url}: {str(e)}"

def download_file(url: str, destination_path: str, max_mb: int = 50) -> str:
    """Downloads a binary or asset file (video, image, font, template) from a URL directly to the workspace."""
    dest = os.path.normpath(destination_path)
    for pat in PROTECTED_PATH_PATTERNS:
        if pat.search(dest):
            return f"❌ Violación de seguridad: No se puede descargar a '{dest}'."

    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            with client.stream("GET", url) as res:
                if res.status_code != 200:
                    return f"❌ Error HTTP {res.status_code} al descargar desde '{url}'."
                cl = res.headers.get("content-length")
                if cl and int(cl) > max_mb * 1024 * 1024:
                    return f"❌ Archivo demasiado grande ({int(cl)/(1024*1024):.1f} MB). Límite máximo: {max_mb} MB."
                
                bytes_written = 0
                with open(dest, "wb") as f:
                    for chunk in res.iter_bytes(chunk_size=65536):
                        f.write(chunk)
                        bytes_written += len(chunk)
                        if bytes_written > max_mb * 1024 * 1024:
                            return f"❌ Descarga abortada: superó el límite de {max_mb} MB."
                
        return f"✅ Archivo descargado exitosamente en '{dest}' ({bytes_written/1024:.1f} KB)."
    except Exception as e:
        return f"❌ Error durante la descarga: {str(e)}"

# --- Sovereign Agentic SQL Engine (PostgreSQL 18 Live Impact) ---

async def describe_store_schema(include_internal: bool = False) -> str:
    """Discovers tables, columns, and data types in the public PostgreSQL database.
    By default, filters to core application domain tables (products, product_variants, services,
    site_settings, orders, order_items, bookings, users) to keep context lean and prevent truncation.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        filter_clause = ""
        if not include_internal:
            filter_clause = "AND table_name IN ('products', 'product_variants', 'services', 'site_settings', 'orders', 'order_items', 'bookings', 'leads', 'users', 'sessions')"
        query = f"""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' {filter_clause}
        ORDER BY table_name, ordinal_position;
        """
        rows = await conn.fetch(query)
        await conn.close()
        if not rows:
            return "No se encontraron tablas de tienda en la base de datos."
        
        tables = {}
        for r in rows:
            t_name = r["table_name"]
            if t_name not in tables:
                tables[t_name] = []
            tables[t_name].append(f"{r['column_name']} ({r['data_type']})")
        
        out = ["📊 **Esquema de Base de Datos Soberano (PostgreSQL 18):**"]
        for t, cols in tables.items():
            out.append(f"• **{t}**: {', '.join(cols)}")
        return "\n".join(out)
    except Exception as e:
        return f"❌ Error descubriendo esquema: {str(e)}"

async def create_store_product(
    name: str,
    base_price: int,
    stock: int = 1,
    image_filename_or_url: str = "",
    category: str = "activewear",
    description: str = ""
) -> str:
    """Crea o actualiza un producto en la base de datos PostgreSQL 18.
    Normaliza automáticamente la URL de la imagen en Astro (/images/products/<filename>).
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg, re
        
        clean_name = name.strip() if name else "Nuevo Producto"
        slug = re.sub(r'[^a-z0-9]+', '-', clean_name.lower()).strip('-')
        if not slug:
            slug = f"producto-{int(base_price)}"
            
        img_url = ""
        if image_filename_or_url:
            raw = str(image_filename_or_url).strip()
            filename = os.path.basename(raw)
            img_url = f"/images/products/{filename}" if not filename.startswith("/images/") else filename
                
        images_json = json.dumps([img_url]) if img_url else "[]"
        desc = description.strip() or f"{clean_name} — Activewear de alta compresión y elegancia anatómica."

        conn = await asyncpg.connect(db_url, timeout=5.0)
        query = """
        INSERT INTO products (slug, name, description, category, base_price, stock, images, is_active, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, 1, NOW())
        ON CONFLICT (slug) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            base_price = EXCLUDED.base_price,
            stock = EXCLUDED.stock,
            images = CASE WHEN EXCLUDED.images = '[]'::jsonb THEN products.images ELSE EXCLUDED.images END,
            is_active = 1,
            updated_at = NOW()
        RETURNING id, slug, name, base_price, stock, images;
        """
        row = await conn.fetchrow(query, slug, clean_name, desc, category, int(base_price), int(stock), images_json)
        await conn.close()
        return f"✅ Producto '{row['name']}' registrado exitosamente en la tienda (Slug: {row['slug']}, Precio: ${row['base_price']:,} COP, Stock: {row['stock']}, Imagen: {img_url})."
    except Exception as e:
        return f"❌ Error creando producto: {str(e)}"

async def set_site_image(
    key: str,
    image_filename_or_url: str,
    alt: str = "",
    title: str = "",
    badge: str = "",
    price: str = ""
) -> str:
    """Configura o actualiza una imagen de sección de la web en site_settings (ej: 'hero_image', 'hero_secondary_image').
    Se refleja en vivo vía SSR sin necesidad de redeploy.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        target_key = key.strip() if key in ("hero_image", "hero_secondary_image") else "hero_image"
        raw = str(image_filename_or_url).strip()
        filename = os.path.basename(raw)
        img_url = f"/images/products/{filename}" if not filename.startswith("/images/") else filename
        
        val_obj = {"url": img_url}
        if alt:
            val_obj["alt"] = alt
        if title:
            val_obj["title"] = title
        if badge:
            val_obj["badge"] = badge
        if price:
            val_obj["price"] = price

        conn = await asyncpg.connect(db_url, timeout=5.0)
        query = """
        INSERT INTO site_settings (key, value, description, updated_at)
        VALUES ($1, $2::jsonb, 'Visual web SSR', NOW())
        ON CONFLICT (key) DO UPDATE SET
            value = site_settings.value || EXCLUDED.value,
            updated_at = NOW()
        RETURNING key, value;
        """
        row = await conn.fetchrow(query, target_key, json.dumps(val_obj))
        await conn.close()
        return f"✅ Imagen visual '{row['key']}' actualizada exitosamente en la portada web: {img_url}"
    except Exception as e:
        return f"❌ Error configurando imagen de sitio: {str(e)}"

async def execute_store_query(query: str, explanation: str = "") -> str:
    """Executes arbitrary SQL queries or mutations on PostgreSQL 18.
    Provides complete agentic freedom for querying and updating products, categories,
    prices, orders, stock, bookings, or analytics.
    Destructive operations (DROP DATABASE, DROP TABLE, DROP SCHEMA, TRUNCATE) are forbidden.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    
    clean_q = query.strip()
    forbidden = re.compile(r'\b(DROP\s+DATABASE|DROP\s+TABLE|DROP\s+SCHEMA|TRUNCATE)\b', re.IGNORECASE)
    if forbidden.search(clean_q):
        return "❌ Violación de seguridad: Operaciones destructivas (DROP/TRUNCATE) están prohibidas."
    
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=10.0)
        is_select = clean_q.lstrip().upper().startswith(("SELECT", "WITH", "EXPLAIN", "SHOW"))
        
        if is_select:
            rows = await conn.fetch(clean_q)
            await conn.close()
            if not rows:
                return "La consulta no devolvió resultados (0 filas)."
            
            cols = list(rows[0].keys())
            if len(rows) <= 15:
                header = "| " + " | ".join(cols) + " |"
                sep = "| " + " | ".join(["---"] * len(cols)) + " |"
                lines = [header, sep]
                for r in rows:
                    row_vals = [str(r[c]) if r[c] is not None else "NULL" for c in cols]
                    lines.append("| " + " | ".join(row_vals) + " |")
                return f"✅ Resultado ({len(rows)} filas):\n" + "\n".join(lines)
            else:
                out = [f"✅ Resultado ({len(rows)} filas - mostrando primeras 15):"]
                for i, r in enumerate(rows[:15]):
                    items = [f"{c}={r[c]}" for c in cols]
                    out.append(f"{i+1}. {', '.join(items)}")
                return "\n".join(out)
        else:
            status = await conn.execute(clean_q)
            await conn.close()
            return f"✅ Consulta ejecutada exitosamente: {status}"
    except Exception as e:
        return f"❌ Error ejecutando SQL: {str(e)}"

# --- E-Commerce & Store Management Tools (SSR PostgreSQL 18 Live Impact) ---

async def get_store_products(category: str = "") -> str:
    """Lists available activewear products with prices and status from the live store database."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        rows = await conn.fetch("SELECT name, base_price, is_active FROM products WHERE is_active = 1 ORDER BY base_price ASC")
        await conn.close()
        if not rows:
            return "No hay productos activos en el catálogo."
        out = ["🛍️ **Catálogo de Productos:**"]
        for r in rows:
            out.append(f"• **{r['name']}**: ${r['base_price']:,} COP")
        return "\n".join(out)
    except Exception as e:
        return f"❌ Error consultando catálogo: {str(e)}"

async def update_product_price(product_name: str, new_price: int) -> str:
    """Updates the price of a product in the live store database."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        await conn.execute(
            "UPDATE products SET base_price = $1, updated_at = NOW() WHERE name ILIKE $2",
            new_price, f"%{product_name.strip()}%"
        )
        row = await conn.fetchrow("SELECT name, base_price FROM products WHERE name ILIKE $1 LIMIT 1", f"%{product_name.strip()}%")
        await conn.close()
        if row:
            return f"✅ Precio actualizado con éxito en vivo:\n• **{row['name']}**: ${row['base_price']:,} COP\nEl cambio ya es visible en la tienda en tiempo real."
        return f"❌ No se encontró ningún producto que coincida con '{product_name}'."
    except Exception as e:
        return f"❌ Error actualizando precio: {str(e)}"

async def get_store_services() -> str:
    """Lists active services and pricing."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        rows = await conn.fetch("SELECT name, price, is_active FROM services WHERE is_active = 1 ORDER BY price ASC")
        await conn.close()
        if not rows:
            return "No hay servicios activos."
        out = ["💼 **Catálogo de Servicios:**"]
        for r in rows:
            out.append(f"• **{r['name']}**: ${r['price']:,} COP")
        return "\n".join(out)
    except Exception as e:
        return f"❌ Error consultando servicios: {str(e)}"

# Retrocompatibility alias
get_makeup_services = get_store_services

async def update_service_price(service_name: str, new_price: int) -> str:
    """Updates the price of a service in the live database."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        await conn.execute(
            "UPDATE services SET price = $1, updated_at = NOW() WHERE name ILIKE $2",
            new_price, f"%{service_name.strip()}%"
        )
        row = await conn.fetchrow("SELECT name, price FROM services WHERE name ILIKE $1 LIMIT 1", f"%{service_name.strip()}%")
        await conn.close()
        if row:
            return f"✅ Servicio actualizado en vivo:\n• **{row['name']}**: ${row['price']:,} COP\nEl cambio ya es visible en la tienda."
        return f"❌ No se encontró ningún servicio que coincida con '{service_name}'."
    except Exception as e:
        return f"❌ Error actualizando servicio: {str(e)}"

async def get_recent_orders(limit: int = 5) -> str:
    """Lists recent customer orders from the store database."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        rows = await conn.fetch("SELECT id, customer_name, total_amount, status, created_at FROM orders ORDER BY created_at DESC LIMIT $1", limit)
        await conn.close()
        if not rows:
            return "No hay pedidos registrados en la tienda todavía."
        out = [f"📦 **Últimos {len(rows)} Pedidos:**"]
        for r in rows:
            date_str = r['created_at'].strftime('%Y-%m-%d %H:%M') if r.get('created_at') else 'N/A'
            out.append(f"• ID #{str(r['id'])[:8]} - {r['customer_name'] or 'Cliente'}: ${r['total_amount']:,} COP [{r['status']}] ({date_str})")
        return "\n".join(out)
    except Exception as e:
        return f"❌ Error consultando pedidos: {str(e)}"

async def get_store_bookings(limit: int = 5) -> str:
    """Lists upcoming or recent appointment bookings."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return "❌ Error: DATABASE_URL no está configurada."
    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        rows = await conn.fetch("SELECT id, customer_name, customer_phone, service_name, appointment_date, status FROM bookings ORDER BY created_at DESC LIMIT $1", limit)
        await conn.close()
        if not rows:
            return "No hay citas ni reservas registradas todavía."
        out = [f"📅 **Citas / Reservas ({len(rows)}):**"]
        for r in rows:
            out.append(f"• {r['customer_name']} ({r['customer_phone'] or 'Sin tel'}): {r['service_name']} - Fecha: {r['appointment_date']} [{r['status']}]")
        return "\n".join(out)
    except Exception as e:
        return f"❌ Error consultando citas: {str(e)}"

# Retrocompatibility alias
get_makeup_bookings = get_store_bookings

# --- Dynamic AI Swarms (CrewAI) & Structured Validation (PydanticAI) ---

async def run_crew_ai(mission: str, roles: list = None, tier: str = "free", output_schema: dict = None, skills: list = None) -> str:
    """Dispatches a dynamic in-memory CrewAI swarm or multi-skill CoHaLo crew with optional Pydantic validation."""
    t0 = time.time()
    try:
        import asyncio
        try:
            from crews.crew_factory import CrewFactory
        except ImportError:
            from hermes.crews.crew_factory import CrewFactory
        
        # If specific sovereign skills are requested (e.g. ['seo-aeo-geo', 'automation-engine'])
        if skills and isinstance(skills, list) and len(skills) > 0:
            result = await asyncio.to_thread(CrewFactory.execute_skills_crew, skill_names=skills, goal=mission, tier=tier)
        else:
            # Standard dynamic role-based crew with optional Pydantic schema
            clean_roles = roles if roles and isinstance(roles, list) else [
                {"role": "Especialista Principal", "goal": mission, "backstory": "Experto técnico senior"}
            ]
            result = await asyncio.to_thread(
                CrewFactory.create_dynamic_crew,
                goal=mission,
                roles=clean_roles,
                tier=tier,
                output_schema=output_schema
            )
        
        # Telemetry to Paperclip (fire-and-forget under CrewAI Engine worker)
        try:
            try:
                from paperclip_bridge import record_crewai_execution
            except ImportError:
                from hermes.paperclip_bridge import record_crewai_execution
            asyncio.create_task(record_crewai_execution(
                mission=mission,
                roles=roles,
                skills=skills,
                output_summary=str(result),
                duration_sec=time.time() - t0,
                success=True
            ))
        except Exception:
            pass

        return result
    except Exception as e:
        # Telemetry to Paperclip on failure
        try:
            try:
                from paperclip_bridge import record_crewai_execution
            except ImportError:
                from hermes.paperclip_bridge import record_crewai_execution
            asyncio.create_task(record_crewai_execution(
                mission=mission,
                roles=roles,
                skills=skills,
                output_summary=f"Error: {str(e)}",
                duration_sec=time.time() - t0,
                success=False
            ))
        except Exception:
            pass
        return f"❌ Error ejecutando CrewAI: {str(e)}"

async def extract_structured_data(fields_spec: dict, user_input: str, tier: str = "free") -> str:
    """Extracts and validates structured data dynamically via PydanticAI."""
    try:
        from pydanticai_engine import extract_structured_data as _extract
        return await _extract(fields_spec=fields_spec, user_input=user_input, tier=tier)
    except Exception as e:
        return f"❌ Error extrayendo datos con PydanticAI: {str(e)}"

def list_available_crews() -> str:
    """Lists dynamic CrewAI swarm capabilities and available CoHaLo skills."""
    try:
        from crews.universal_harness import UniversalSkillHarness
        skills = UniversalSkillHarness.list_available_skills()
        total = len(skills)
        sample = ", ".join([f"`{s}`" for s in skills[:15]])
        return (
            f"🤖 **Catálogo Dinámico de Cuadrillas CrewAI ({total} Skills disponibles):**\n"
            f"1. **Enjambres Ad-hoc por Roles**: Podés pedirme crear cuadrillas personalizadas pasando roles y objetivos a `run_crew_ai`.\n"
            f"2. **Validación Estricta con Pydantic**: Soporte nativo para exigir salida JSON estructurada pasando `output_schema`.\n"
            f"3. **Skills Soberanas CoHaLo**: Mapeo directo a {total} skills activas. Muestra: {sample}...\n\n"
            "Ejemplo de uso: *'Creá una cuadrilla con un estratega de pricing y un auditor para definir las tarifas de mentorías 1:1'*."
        )
    except Exception:
        return "🤖 Cuadrillas dinámicas CrewAI operativas sobre Bifrost ($0 FreeLLMAPI). Podés crear cualquier enjambre pasando roles y misión."

async def get_paperclip_status() -> str:
    """Queries Paperclip AI board at http://paperclip:3100 to check live company, agents, and task status."""
    try:
        import httpx
        from paperclip_bridge import get_paperclip_db_url, list_paperclip_issues

        dashboard_url = "https://paperclip-2b6-3100.ny1.zerops.app"
        config_path = "/mnt/localstorage/paperclip/instances/default/config.json"
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    dashboard_url = cfg.get("auth", {}).get("publicBaseUrl") or dashboard_url
            except Exception:
                pass

        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get("http://paperclip:3100/api/health")
            if res.status_code != 200:
                return f"⚠️ Paperclip responde con estado {res.status_code}"

        # Dynamic introspection of physical agents in PostgreSQL
        db_url = get_paperclip_db_url()
        agents_info = []
        if db_url:
            import asyncpg
            conn = await asyncpg.connect(db_url, timeout=5.0)
            rows = await conn.fetch("SELECT name, role, adapter_type, status, last_heartbeat_at FROM agents ORDER BY role ASC")
            await conn.close()
            for r in rows:
                hb = r['last_heartbeat_at'].strftime('%Y-%m-%d %H:%M:%S UTC') if r['last_heartbeat_at'] else 'Sin latidos'
                agents_info.append(f"  - **{r['name']}** ({r['role']}): {r['status']} | Adaptador: `{r['adapter_type']}` | Último latido: {hb}")

        issues = await list_paperclip_issues(limit=5)
        issues_text = ""
        if issues:
            issues_text = "\n• **Tareas Recientes en Tablero:**\n" + "\n".join(
                [f"  - [{i['identifier']}] {i['title']} ({i['status']}, prioridad: {i['priority']})" for i in issues]
            )

        agents_text = "\n".join(agents_info) if agents_info else "  - Sin agentes registrados"
        return (
            "📋 **Paperclip Autonomous Control Plane (http://paperclip:3100):**\n"
            "• Estado: ACTIVO (Node.js 26 + PostgreSQL 18)\n"
            f"• Dashboard: {dashboard_url}\n"
            "• **Organigrama Activo en Base de Datos:**\n"
            f"{agents_text}\n"
            f"{issues_text}\n"
            "• **Telemetría Bidireccional:** Habilitada (Telegram turns ➔ Heartbeat Runs + Activity Log)."
        )
    except Exception as e:
        return f"❌ Error conectando a Paperclip: {str(e)}"

async def paperclip_list_tasks(status: str = "") -> str:
    """Lists actionable tasks from Paperclip Control Plane."""
    try:
        from paperclip_bridge import list_paperclip_issues
        issues = await list_paperclip_issues(status=status.strip() if status else None, limit=10)
        if not issues:
            return "No se encontraron tareas registradas en Paperclip."
        lines = [f"📋 **Tareas en Paperclip ({len(issues)}):**"]
        for i in issues:
            lines.append(f"• **[{i['identifier']}]** {i['title']} — Estado: `{i['status']}` (Prioridad: {i['priority']})")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Error consultando tareas de Paperclip: {str(e)}"

async def paperclip_create_task(title: str, description: str = "", priority: str = "medium") -> str:
    """Creates a new actionable task directly in Paperclip Control Plane."""
    try:
        from paperclip_bridge import create_paperclip_issue
        res = await create_paperclip_issue(title=title, description=description, priority=priority)
        if res:
            return f"✅ Tarea creada con éxito en Paperclip:\n• Identificador: **{res['identifier']}**\n• Título: {res['title']}\n• Estado: `{res['status']}` (Prioridad: {res['priority']})"
        return "❌ No se pudo crear la tarea en Paperclip."
    except Exception as e:
        return f"❌ Error creando tarea en Paperclip: {str(e)}"

async def paperclip_register_agent(
    name: str,
    title: str = "",
    role: str = "worker",
    adapter_type: str = "hermes_gateway",
    capabilities: str = "",
    budget_monthly_cents: int = 50000,
) -> str:
    """Registers a new permanent agent in Paperclip's Org Chart under Hermes."""
    try:
        from paperclip_bridge import register_paperclip_agent
        res = await register_paperclip_agent(
            name=name,
            title=title,
            role=role,
            adapter_type=adapter_type,
            capabilities=capabilities,
            budget_monthly_cents=budget_monthly_cents,
        )
        if res:
            return f"✅ Agente registrado con éxito en Paperclip:\n• Nombre: **{res['name']}**\n• Rol: `{res['role']}`\n• Título: {res['title']}\n• ID: `{res['id']}`\n• Visible en el Organigrama de Paperclip."
        return "❌ No se pudo registrar el agente en Paperclip."
    except Exception as e:
        return f"❌ Error registrando agente en Paperclip: {str(e)}"

# ==============================================================================
# Sovereign Engram Memory Engine (Multi-Agent LocalStorage & Cross-Container SSoT)
# ==============================================================================

def _resolve_engram_ssot_path() -> Optional[str]:
    """Resolves active project engram_ssot.json in persistent localstorage."""
    project_name = (clean_env("PROJECT_NAME") or clean_env("ENGRAM_PROJECT") or clean_env("ZEROPS_ProjectId")).lower()
    if project_name:
        base_dirs = [
            os.path.join(os.getenv("ENGRAM_STORAGE_DIR", "/mnt/localstorage/engram"), project_name),
            os.path.join("/var/www/localstorage/engram", project_name),
            f"/mnt/localstorage/engram/{project_name}",
        ]
        for d in base_dirs:
            p = os.path.join(d, "engram_ssot.json")
            if os.path.exists(p):
                return p
    # Dynamic auto-discovery: find any existing engram_ssot.json in localstorage
    for root in ["/mnt/localstorage/engram", "/var/www/localstorage/engram"]:
        if os.path.exists(root):
            try:
                for item in os.listdir(root):
                    cand = os.path.join(root, item, "engram_ssot.json")
                    if os.path.isfile(cand):
                        return cand
            except Exception:
                pass
    return None

def mem_context(limit: int = 5) -> str:
    """Recovers the most recent persistent observations from Engram for the active project."""
    ssot_path = _resolve_engram_ssot_path()
    if not ssot_path or not os.path.exists(ssot_path):
        return "ℹ️ No hay memoria Engram registrada aún para este proyecto en localstorage."
    try:
        with open(ssot_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        obs = data.get("observations") or []
        if not obs:
            return "ℹ️ Engram está vacío (0 observaciones registradas)."
        active_obs = [o for o in obs if not o.get("deleted_at")]
        recent = active_obs[-limit:]
        lines = [f"🧠 **Engram SSoT ({len(active_obs)} observaciones activas, mostrando últimas {len(recent)}):**"]
        for o in reversed(recent):
            lines.append(f"• **[{o.get('type', 'discovery')}] {o.get('title', 'Sin título')}** (`{o.get('topic_key', 'general')}`):\n  {o.get('content', '')}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"❌ Error leyendo Engram: {str(e)}"

def mem_search(query: str, limit: int = 5) -> str:
    """Searches persistent Engram memory by keyword across titles, topics, and content."""
    ssot_path = _resolve_engram_ssot_path()
    if not ssot_path or not os.path.exists(ssot_path):
        return "ℹ️ No hay memoria Engram registrada aún para este proyecto."
    try:
        with open(ssot_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        obs = data.get("observations") or []
        q = query.lower().strip()
        matches = []
        for o in obs:
            if o.get("deleted_at"):
                continue
            haystack = f"{o.get('title', '')} {o.get('topic_key', '')} {o.get('content', '')}".lower()
            if q in haystack:
                matches.append(o)
        if not matches:
            return f"ℹ️ Cero coincidencias en Engram para la búsqueda: '{query}'."
        lines = [f"🔍 **Engram Search ('{query}' - {len(matches)} coincidencias):**"]
        for o in matches[-limit:]:
            lines.append(f"• **[{o.get('type', 'discovery')}] {o.get('title', 'Sin título')}** (`{o.get('topic_key', 'general')}`):\n  {o.get('content', '')}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"❌ Error buscando en Engram: {str(e)}"

def mem_save(title: str, content: str, type: str = "discovery", topic_key: str = "") -> str:
    """Saves a new observation to persistent Engram storage in localstorage."""
    project_name = (clean_env("PROJECT_NAME") or clean_env("ENGRAM_PROJECT") or clean_env("ZEROPS_ProjectId") or "default").lower()
    engram_dir = os.path.join(os.getenv("ENGRAM_STORAGE_DIR", "/mnt/localstorage/engram"), project_name)
    if not os.path.exists(engram_dir):
        engram_dir = f"/var/www/localstorage/engram/{project_name}"
    os.makedirs(engram_dir, exist_ok=True)
    ssot_path = os.path.join(engram_dir, "engram_ssot.json")
    
    import hashlib
    from datetime import datetime, timezone
    
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    raw_hash = hashlib.sha256(f"{project_name}:{title}:{content}".encode("utf-8")).hexdigest()[:16]
    sync_id = f"obs-{raw_hash}"
    
    data = {"version": "0.1.0", "exported_at": now_iso, "sessions": [], "observations": []}
    if os.path.exists(ssot_path):
        try:
            with open(ssot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
            
    obs_list = data.setdefault("observations", [])
    existing = None
    for o in obs_list:
        if o.get("sync_id") == sync_id or (topic_key and o.get("topic_key") == topic_key):
            existing = o
            break
            
    if existing:
        existing["content"] = content
        existing["title"] = title
        existing["type"] = type
        existing["updated_at"] = now_iso
        existing["revision_count"] = existing.get("revision_count", 1) + 1
    else:
        new_obs = {
            "id": len(obs_list) + 1,
            "sync_id": sync_id,
            "session_id": f"hermes-{project_name}",
            "type": type,
            "title": title,
            "content": content,
            "project": project_name,
            "scope": "project",
            "topic_key": topic_key or "hermes/discovery",
            "revision_count": 1,
            "duplicate_count": 1,
            "created_at": now_iso,
            "updated_at": now_iso
        }
        obs_list.append(new_obs)
        
    data["exported_at"] = now_iso
    temp_path = f"{ssot_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, ssot_path)
    return f"✅ Observación guardada en Engram persistentemente (`{sync_id}`): '{title}'"

# ==============================================================================
# Sovereign Linear Bridge Integration (Typed Linear Operations in Hermes)
# ==============================================================================

def get_linear_bridge():
    """Initializes and returns a cached or new LinearBridge instance."""
    try:
        from .linear_bridge import LinearBridge
    except ImportError:
        try:
            from linear_bridge import LinearBridge
        except ImportError:
            return None
    return LinearBridge()

def linear_create_issue(title: str, description: str = "", priority: int = 2) -> str:
    """Creates a new issue in the active Linear project."""
    bridge = get_linear_bridge()
    if not bridge:
        return "❌ Error: linear_bridge no disponible en este entorno."
    try:
        issue = bridge.create_issue(title=title, description=description, priority=priority)
        return f"✅ Ticket Linear creado: [{issue.id}] {issue.title}\nURL: {issue.url}\nEstado: {issue.status}"
    except Exception as e:
        return f"❌ Error creando ticket Linear: {str(e)}"

def linear_update_status(issue_id: str, status: str, evidence: str = "") -> str:
    """Updates the workflow status of a Linear issue (e.g. 'In Progress', 'Done', 'Canceled')."""
    bridge = get_linear_bridge()
    if not bridge:
        return "❌ Error: linear_bridge no disponible en este entorno."
    try:
        bridge.update_status(issue_id=issue_id, status=status, evidence=evidence)
        return f"✅ Estado actualizado en Linear: [{issue_id}] -> {status}"
    except Exception as e:
        return f"❌ Error actualizando ticket Linear: {str(e)}"

def linear_get_issue(issue_id: str) -> str:
    """Fetches details of a Linear issue by ID (e.g. 'BAI-453')."""
    bridge = get_linear_bridge()
    if not bridge:
        return "❌ Error: linear_bridge no disponible en este entorno."
    try:
        issue = bridge.get_issue(issue_id)
        return f"📋 **[{issue.id}] {issue.title}**\nEstado: {issue.status} | Prioridad: {issue.priority}\nURL: {issue.url}\nDescripción:\n{issue.description}"
    except Exception as e:
        return f"❌ Error obteniendo ticket Linear: {str(e)}"

def linear_comment_issue(issue_id: str, comment: str) -> str:
    """Adds a comment to a Linear issue."""
    bridge = get_linear_bridge()
    if not bridge:
        return "❌ Error: linear_bridge no disponible en este entorno."
    try:
        bridge.comment_issue(issue_id, comment)
        return f"✅ Comentario publicado en Linear [{issue_id}]."
    except Exception as e:
        return f"❌ Error comentando en ticket Linear: {str(e)}"



# ==============================================================================
# Operational Base Workspace & Verticals Grounding (MentorIA/dev & Playbooks)
# ==============================================================================

_PROJ = clean_env("PROJECT_NAME", "default")
DEV_BASE_PATH = f"/mnt/localstorage/{_PROJ}/dev"
PLAYBOOKS_PATH = "/mnt/localstorage/playbooks"
SKILLS_PATH = "/mnt/localstorage/skills"

def list_verticals() -> str:
    """Lists all available vertical specifications in the dev base workspace."""
    vert_dir = os.path.join(DEV_BASE_PATH, "verticals")
    if not os.path.exists(vert_dir):
        vert_dir = f"/var/www/localstorage/{_PROJ}/dev/verticals"
    if not os.path.exists(vert_dir):
        return "❌ Directorio de verticales no encontrado en /mnt/localstorage/${PROJECT_NAME}/dev/verticals"
    
    verticals = []
    for fn in sorted(os.listdir(vert_dir)):
        if fn.endswith(".json") and fn != "ecosystem.json":
            fpath = os.path.join(vert_dir, fn)
            try:
                with open(fpath, "r", encoding="utf-8") as jf:
                    data = json.load(jf)
                    slug = data.get("vertical_slug", fn[:-5])
                    name = data.get("display_name", slug)
                    domain = data.get("custom_domain", "")
                    funnel = data.get("funnel_type", "")
                    verticals.append(f"• **{slug}**: {name} (Dominio: {domain} | Funnel: {funnel})")
            except Exception:
                verticals.append(f"• **{fn[:-5]}**")
    
    if not verticals:
        return "No hay especificaciones de verticales registradas aún en dev/verticals."
    return "📂 **Verticales Curadas Disponibles (dev/verticals)**:\n" + "\n".join(verticals)

def get_vertical(vertical_slug: str) -> str:
    """Retrieves the complete JSON specification of a curated vertical (e.g. 'brand-core', 'vertical-a', 'vertical-b')."""
    slug = vertical_slug.strip().lower()
    if slug.endswith(".json"):
        slug = slug[:-5]
    
    for base in [DEV_BASE_PATH, f"/var/www/localstorage/{_PROJ}/dev"]:
        fpath = os.path.join(base, "verticals", f"{slug}.json")
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as jf:
                    return jf.read()
            except Exception as e:
                return f"❌ Error leyendo vertical {slug}: {str(e)}"
    
    return f"❌ Vertical '{slug}' no encontrada en dev/verticals. Usa list_verticals para ver las disponibles."

def list_playbooks() -> str:
    """Lists all available universal playbooks in /mnt/localstorage/playbooks."""
    pdir = PLAYBOOKS_PATH if os.path.exists(PLAYBOOKS_PATH) else "/var/www/localstorage/playbooks"
    if not os.path.exists(pdir):
        return "❌ Directorio de playbooks no encontrado en /mnt/localstorage/playbooks"
    
    playbooks = [fn[:-3] for fn in sorted(os.listdir(pdir)) if fn.endswith(".md")]
    if not playbooks:
        return "No hay playbooks disponibles."
    return "📚 **Playbooks Universales Disponibles**:\n" + "\n".join([f"• {p}" for p in playbooks])

def get_playbook(playbook_slug: str) -> str:
    """Reads a universal playbook markdown file by name (e.g. 'seo_aeo_playbook', 'copywriting_playbook', 'offers_pricing_playbook', 'funnels_cro_playbook')."""
    slug = playbook_slug.strip().lower()
    if not slug.endswith(".md"):
        slug = f"{slug}.md"
    
    for base in [PLAYBOOKS_PATH, "/var/www/localstorage/playbooks"]:
        fpath = os.path.join(base, slug)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                    if len(content) > 6000:
                        return f"[PLAYBOOK {slug} (primeros 6000 caracteres)]:\n\n{content[:6000]}\n\n... [snip resto del playbook]"
                    return content
            except Exception as e:
                return f"❌ Error leyendo playbook {slug}: {str(e)}"
    
    return f"❌ Playbook '{playbook_slug}' no encontrado. Usa list_playbooks para ver los disponibles."

def get_brandbook_tokens(vertical_slug: str = "") -> str:
    """Reads the compiled brandbook and design tokens (brandbook.json, chroma_manifest.json, font_manifest.json) for a specific vertical from its isolated workspace."""
    slug = (vertical_slug or "brand-core").strip().lower()
    for base in [DEV_BASE_PATH, f"/var/www/localstorage/{_PROJ}/dev"]:
        # 1. Check workspace brand path
        w_path = os.path.join(base, "workspaces", slug, "brand", "brandbook.json")
        if os.path.exists(w_path):
            try:
                with open(w_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"❌ Error leyendo brandbook.json en workspace {slug}: {str(e)}"
        # 2. Check root / fallback symlink
        bb_path = os.path.join(base, "brandbook.json")
        if os.path.exists(bb_path):
            try:
                with open(bb_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"❌ Error leyendo brandbook.json: {str(e)}"
    return f"❌ brandbook.json no encontrado para vertical '{slug}' en dev/workspaces/."

def list_skills(query: str = "") -> str:
    """Lists available sovereign skills in /mnt/localstorage/skills/ with their operational triggers and descriptions."""
    bases = [SKILLS_PATH, "/var/www/localstorage/skills"]
    target_base = None
    for b in bases:
        if os.path.isdir(b):
            target_base = b
            break
    if not target_base:
        return "❌ Directorio de sovereign skills no encontrado en /mnt/localstorage/skills"
    
    q = query.strip().lower()
    discovered = []
    for item in sorted(os.listdir(target_base)):
        item_path = os.path.join(target_base, item)
        if not os.path.isdir(item_path):
            continue
        skill_md = os.path.join(item_path, "SKILL.md")
        if not os.path.exists(skill_md):
            continue
        
        desc = ""
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read(1500)
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        for line in parts[1].splitlines():
                            if line.strip().startswith("description:"):
                                desc = line.split("description:", 1)[1].strip().strip('"').strip("'")
                                break
        except Exception:
            pass
        
        if q:
            if q in item.lower() or q in desc.lower():
                discovered.append((item, desc))
        else:
            discovered.append((item, desc))
            
    if not discovered:
        return f"No se encontraron sovereign skills que coincidan con '{query}'."
    
    if q:
        lines = [f"• **{n}**: {d[:160]}..." if d else f"• **{n}**" for n, d in discovered]
        return f"🛠️ **Sovereign Skills Coincidentes con '{query}' ({len(lines)})**:\n" + "\n".join(lines)
    else:
        names = [item[0] for item in discovered]
        return f"🛠️ **{len(names)} Sovereign Skills en /mnt/localstorage/skills/** (filtrá con list_skills(query='...') o consultá con get_skill_docs(name)):\n" + ", ".join(names)

def get_skill_docs(skill_name: str) -> str:
    """Reads the SKILL.md and operational usage guidelines of any sovereign skill from /mnt/localstorage/skills/ (e.g. 'seo-aeo-geo', 'growth-engine', 'apotelos', 'astro-web')."""
    sname = skill_name.strip().lower()
    for base in [SKILLS_PATH, "/var/www/localstorage/skills"]:
        sdir = os.path.join(base, sname)
        if os.path.isdir(sdir):
            skill_md = os.path.join(sdir, "SKILL.md")
            if os.path.exists(skill_md):
                try:
                    with open(skill_md, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception as e:
                    return f"❌ Error leyendo SKILL.md para {sname}: {str(e)}"
    return f"❌ Skill '{sname}' no encontrada en localstorage/skills."

def apotelos_cli(subcommand: str, args: str = "") -> str:
    """
    Executes the sovereign Apotelos Reverse-Causality CLI (/usr/local/bin/apotelos).
    Subcommands:
      - 'list': Lists all discovered business verticals and active ecosystem.
      - 'audit': Validates static Pydantic v2 contract for a vertical (e.g. args='--vertical brand-core').
      - 'plan': Displays the reverse causality domino tree (Dominó 4 a Dominó 0).
      - 'run': Compiles the authoritative Blackboard Manifest and SSoT Markdown Dossier.
      - 'dossier': Compiles the comprehensive SSoT markdown dossier for the ecosystem.
      - 'test': Runs the physical agnostic integrity sensor.
      - 'scaffold': Materializes Astro 5 SSR code from the Blackboard manifest.
    """
    import subprocess
    cmd = f"/usr/local/bin/apotelos {subcommand} {args}".strip()
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        out = (res.stdout + "\n" + res.stderr).strip()
        return out if out else f"✅ Comando '{cmd}' ejecutado exitosamente con código {res.returncode}."
    except Exception as e:
        return f"❌ Error ejecutando '{cmd}': {str(e)}"


