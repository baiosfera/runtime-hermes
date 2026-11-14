"""
Nous Research Hermes-Agent: Autonomous Daemon & NATS Event Bridge
Pure Python standard library HTTP health server + NATS JetStream daemon.
Zero FastAPI/Uvicorn runtime bloat.
"""
import os
import sys
import json
import time
import uuid
import queue
import asyncio
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import threading

for _extra_bin in ("/mnt/localstorage/bin", "/var/www/bin", "/usr/local/bin"):
    if _extra_bin not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = f"{_extra_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}"

# Auto-load runtime keys from shared localstorage vault if missing or unresolved placeholder
try:
    from env_utils import clean_env, load_runtime_env
except (ImportError, ValueError):
    from .env_utils import clean_env, load_runtime_env

load_runtime_env([
    os.path.join(clean_env("LOCAL_STORAGE_PATH", "/mnt/localstorage/hermes"), "runtime.env"),
    "/mnt/localstorage/hermes/runtime.env",
    "/var/www/localstorage/hermes/runtime.env",
])

ACTIVE_RUNS = {}
_MAX_CONCURRENT_RUNS = 10

try:
    from agent import HermesAgent
except (ImportError, ValueError):
    from .agent import HermesAgent

try:
    from telegram_gateway import run_bot as run_telegram_bot
except (ImportError, ValueError):
    try:
        from .telegram_gateway import run_bot as run_telegram_bot
    except Exception:
        run_telegram_bot = None

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        clean_path = self.path.split("?")[0]
        if clean_path in ("/health", "/healthz", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status_payload = {
                "status": "ok",
                "service": "hermes-agent",
                "mode": "daemon_nats_bridge",
                "model_endpoint": os.getenv("HERMES_MODEL_ENDPOINT", "http://bifrost:8080/v1"),
                "nats_url": os.getenv("NATS_URL") or os.getenv("ZCP_NATS_URL", "nats://nats:4222"),
                "database_configured": bool(os.getenv("DATABASE_URL")),
                "cpu_mode": "SHARED",
                "capabilities": [
                    "astrology_worker",
                    "agent_loop",
                    "client_dumps_reader",
                    "paperclip_gateway_v1",
                    "crewai_runner"
                ]
            }
            self.wfile.write(json.dumps(status_payload).encode("utf-8"))
            return

        # Status check for Paperclip run: /v1/runs/<run_id>
        if clean_path.startswith("/v1/runs/") and not clean_path.endswith("/events"):
            parts = clean_path.split("/")
            if len(parts) >= 4:
                run_id = parts[3]
                run_info = ACTIVE_RUNS.get(run_id)
                if not run_info:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"Run {run_id} not found"}).encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "id": run_id,
                    "run_id": run_id,
                    "status": "completed" if run_info.get("terminal") else "running",
                    "terminal": run_info.get("terminal", False),
                    "crew_name": run_info.get("crew_name")
                }).encode("utf-8"))
                return

        # SSE Events stream for Paperclip: /v1/runs/<run_id>/events
        if clean_path.startswith("/v1/runs/") and clean_path.endswith("/events"):
            parts = clean_path.split("/")
            if len(parts) >= 5:
                run_id = parts[3]
                run_info = ACTIVE_RUNS.get(run_id)
                if not run_info:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"Run {run_id} not found"}).encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                q = run_info["queue"]
                while True:
                    try:
                        event = q.get(timeout=2.0)
                        event_name = event.get("event", "message")
                        data_str = json.dumps(event.get("data", {}))
                        payload = f"event: {event_name}\ndata: {data_str}\n\n"
                        self.wfile.write(payload.encode("utf-8"))
                        self.wfile.flush()
                        if event_name in ("run.completed", "run.failed", "run.cancelled"):
                            break
                    except queue.Empty:
                        try:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                        except Exception:
                            break
                        if run_info.get("terminal"):
                            break
                    except (BrokenPipeError, ConnectionResetError):
                        break
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        clean_path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}

        # 1. Paperclip Gateway Run Dispatch: /v1/runs
        if clean_path == "/v1/runs":
            now = time.time()
            # Stale runs sweep (TTL > 1 hour)
            stale_keys = [rid for rid, rinfo in ACTIVE_RUNS.items() if now - rinfo.get("created_at", now) > 3600]
            for rid in stale_keys:
                ACTIVE_RUNS.pop(rid, None)

            # Concurrency protection
            running_runs = [r for r in ACTIVE_RUNS.values() if not r.get("terminal")]
            if len(running_runs) >= _MAX_CONCURRENT_RUNS:
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Demasiadas ejecuciones concurrentes en Hermes (máximo 10). Intentá nuevamente en unos momentos."}).encode("utf-8"))
                return

            run_id = f"run_{uuid.uuid4().hex[:12]}"
            crew_header = self.headers.get("x-crew-name") or self.headers.get("X-Crew-Name")
            crew_name = payload.get("crew_name") or crew_header
            input_text = payload.get("input") or payload.get("goal") or payload.get("prompt") or "General task"

            run_queue = queue.Queue()
            ACTIVE_RUNS[run_id] = {
                "id": run_id,
                "status": "running",
                "queue": run_queue,
                "terminal": False,
                "crew_name": crew_name,
                "created_at": now
            }

            def worker():
                try:
                    display_name = crew_name or "Hermes Autonomous Agent"
                    run_queue.put({
                        "event": "message.delta",
                        "data": {"delta": f"🚀 [Hermes Gateway] Iniciando ejecución de {display_name}...\n"}
                    })

                    output_text = ""
                    if crew_name and crew_name.lower() != "hermes":
                        run_queue.put({
                            "event": "message.delta",
                            "data": {"delta": f"👥 Ensamblando cuadrilla CrewAI: '{crew_name}'...\n"}
                        })
                        try:
                            from crews.crew_factory import CrewFactory
                        except ImportError:
                            from .crews.crew_factory import CrewFactory

                        output_text = CrewFactory.execute(crew_name, input_text)
                    else:
                        run_queue.put({
                            "event": "message.delta",
                            "data": {"delta": "🧠 Ejecutando turno con Hermes Autonomous Agent...\n"}
                        })
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        agent = HermesAgent()
                        output_text = loop.run_until_complete(agent.run_turn(input_text))
                        loop.close()

                    run_queue.put({
                        "event": "message.delta",
                        "data": {"delta": f"\n\n{output_text}\n"}
                    })
                    run_queue.put({
                        "event": "run.completed",
                        "data": {
                            "status": "completed",
                            "output": output_text,
                            "usage": {
                                "input_tokens": 150,
                                "output_tokens": len(output_text.split()),
                                "cost_cents": 0
                            }
                        }
                    })
                except Exception as err:
                    run_queue.put({
                        "event": "run.failed",
                        "data": {
                            "status": "failed",
                            "error": str(err),
                            "output": f"Error ejecutando run: {str(err)}"
                        }
                    })
                finally:
                    if run_id in ACTIVE_RUNS:
                        ACTIVE_RUNS[run_id]["terminal"] = True

            threading.Thread(target=worker, daemon=True).start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "id": run_id,
                "run_id": run_id,
                "status": "running"
            }).encode("utf-8"))
            return

        # 2. Paperclip Gateway Stop Run: /v1/runs/<run_id>/stop
        if clean_path.startswith("/v1/runs/") and clean_path.endswith("/stop"):
            parts = clean_path.split("/")
            if len(parts) >= 4:
                run_id = parts[3]
                if run_id in ACTIVE_RUNS:
                    ACTIVE_RUNS[run_id]["terminal"] = True
                    ACTIVE_RUNS[run_id]["queue"].put({
                        "event": "run.cancelled",
                        "data": {"status": "cancelled", "message": "Run stopped by operator"}
                    })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopped", "id": run_id if 'run_id' in locals() else ""}).encode("utf-8"))
            return

        # 3. Direct Programmatic Kickoff: /api/crews/kickoff
        if clean_path in ("/api/crews/kickoff", "/crews/kickoff"):
            try:
                crew_name = payload.get("crew", "")
                skills = payload.get("skills", [])
                goal = payload.get("goal") or payload.get("topic") or "General task"
                tier = payload.get("tier", "free")

                try:
                    from crews.crew_factory import CrewFactory
                except ImportError:
                    from .crews.crew_factory import CrewFactory

                if skills and isinstance(skills, list):
                    output = CrewFactory.execute_skills_crew(skills, goal, tier=tier)
                elif crew_name:
                    output = CrewFactory.execute(crew_name, goal, tier=tier)
                else:
                    output = "Error: Parámetros inválidos. Especificá 'crew' o lista de 'skills'."

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "result": output}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Quiet standard logging
        pass

def run_health_server(port: int = 8000):
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    server.daemon_threads = True
    print(f"[Hermes-Agent] Threading health server listening on port {port}")
    server.serve_forever()

async def handle_astrology_request(msg):
    """Callback for astrology.requests topic on NATS"""
    try:
        data = json.loads(msg.data.decode("utf-8"))
        print(f"[Hermes-Agent] Received astrology request: {data.get('task_id', 'unknown')}")
        # Acknowledge message if under JetStream
        if hasattr(msg, "ack"):
            await msg.ack()
    except Exception as err:
        print(f"[Hermes-Agent] Error processing astrology request: {err}")

async def run_nats_bridge():
    """
    Hermes background consumer for NATS JetStream events.
    Listens for astrology.requests, events.ops and coaching notifications.
    """
    nats_url = os.getenv("NATS_URL") or os.getenv("ZCP_NATS_URL", "nats://nats:4222")
    agent = HermesAgent()
    print(f"[Hermes-Agent] Autonomous loop and NATS event listener initialized against {nats_url}.")
    
    nc = None
    try:
        from nats.aio.client import Client as NATS
        nc = NATS()
        await nc.connect(nats_url, connect_timeout=5)
        print("[Hermes-Agent] Connected to NATS broker successfully.")
        await nc.subscribe("astrology.requests", cb=handle_astrology_request)
    except Exception as err:
        print(f"[Hermes-Agent] NATS connection deferred ({err}). Running in standalone polling mode.")

    while True:
        await asyncio.sleep(60)

async def run_services():
    # 0. Auto-initialize Database and persistent schemas idempotently
    try:
        try:
            from db import init_db
        except (ImportError, ValueError):
            from .db import init_db
        print("[Hermes-Agent] Initializing and verifying persistent database schemas...")
        await init_db()
    except Exception as _db_err:
        print(f"[Hermes-Agent] Database initialization warning: {_db_err}", file=sys.stderr)

    try:
        from paperclip_bridge import reconcile_bifrost_to_paperclip
        print("[Hermes-Agent] Reconciling Bifrost costs into Paperclip Control Plane...")
        await reconcile_bifrost_to_paperclip()
    except Exception as _reconcile_err:
        print(f"[Hermes-Agent] Startup cost reconciliation deferred: {_reconcile_err}")

    tasks = [asyncio.create_task(run_nats_bridge())]
    if run_telegram_bot:
        print("[Hermes-Agent] Initializing Telegram gateway...")
        tasks.append(asyncio.create_task(run_telegram_bot()))
    await asyncio.gather(*tasks)

def main():
    port = int(os.getenv("PORT", "8000"))
    # Start health server in background daemon thread
    server_thread = threading.Thread(target=run_health_server, args=(port,), daemon=True)
    server_thread.start()

    # Run primary async agent loops
    try:
        asyncio.run(run_services())
    except KeyboardInterrupt:
        print("[Hermes-Agent] Shutting down gracefully.")

if __name__ == "__main__":
    main()
