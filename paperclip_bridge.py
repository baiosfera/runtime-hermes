"""
Paperclip Bidirectional Telemetry & Task Bridge for Hermes Agent.
Synchronizes Telegram conversation turns, tool actions, and heartbeat runs
directly into Paperclip Control Plane (PostgreSQL 18 + Activity Stream).
"""
import os
import json
import uuid
import time
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("hermes.paperclip_bridge")

try:
    from env_utils import clean_env
except (ImportError, ValueError):
    from .env_utils import clean_env

# Fallback UUIDs when Paperclip company discovery is unavailable (overridable via env)
DEFAULT_COMPANY_ID = clean_env("PAPERCLIP_COMPANY_ID", "2c915432-4c84-4b01-b90b-ee7482147eef")
DEFAULT_HERMES_AGENT_ID = "22222222-2222-2222-2222-222222222222"
DEFAULT_PI_AGENT_ID = "33333333-3333-3333-3333-333333333333"
DEFAULT_CREWAI_AGENT_ID = "44444444-4444-4444-4444-444444444444"
DEFAULT_RESPONSIBLE_USER_ID = "xy80KZka8U4baAQBJwmSzEVOFjd2GRby"

_DB_CONN_STR: Optional[str] = None

def get_paperclip_db_url() -> Optional[str]:
    """
    Dynamically discovers the canonical PostgreSQL connection string
    from Paperclip instance config or environment without hardcoded secrets.
    """
    global _DB_CONN_STR
    if _DB_CONN_STR:
        return _DB_CONN_STR

    # 1. Direct environment override
    env_url = clean_env("PAPERCLIP_DATABASE_URL")
    if env_url:
        _DB_CONN_STR = env_url
        return _DB_CONN_STR

    # 2. LocalStorage NVMe instance config
    for candidate_path in [
        "/mnt/localstorage/paperclip/instances/default/config.json",
        "/var/www/localstorage/paperclip/instances/default/config.json",
        os.path.expanduser("~/.paperclip/instances/default/config.json"),
    ]:
        if os.path.exists(candidate_path):
            try:
                with open(candidate_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    db_str = cfg.get("database", {}).get("connectionString")
                    if db_str:
                        _DB_CONN_STR = db_str
                        return _DB_CONN_STR
            except Exception as e:
                logger.warning("Could not read Paperclip config from %s: %s", candidate_path, e)

    # 3. Fallback to DATABASE_URL if pointing to paperclip database
    fallback = clean_env("DATABASE_URL")
    if "paperclip" in fallback:
        _DB_CONN_STR = fallback
        return _DB_CONN_STR

    return None

def get_bifrost_db_url() -> Optional[str]:
    """
    Returns the database connection URL for Bifrost gateway request logs.
    Derived dynamically from Paperclip DB URL or environment.
    """
    env_url = clean_env("BIFROST_DATABASE_URL")
    if env_url:
        return env_url
    pc_url = get_paperclip_db_url()
    if pc_url and "/paperclip" in pc_url:
        return pc_url.replace("/paperclip", "/db")
    fallback = clean_env("DATABASE_URL")
    if fallback and "/paperclip" in fallback:
        return fallback.replace("/paperclip", "/db")
    return None

async def reconcile_bifrost_to_paperclip(
    company_id: str = DEFAULT_COMPANY_ID,
    agent_id: str = DEFAULT_HERMES_AGENT_ID,
) -> int:
    """
    Reconciles paid LLM requests (e.g. DeepSeek) from Bifrost logs into Paperclip's cost_events ledger.
    Ensures 100% financial and token parity between Bifrost gateway and Paperclip Control Plane.
    Returns the count of reconciled cost events.
    """
    pc_url = get_paperclip_db_url()
    bf_url = get_bifrost_db_url()
    if not pc_url or not bf_url:
        return 0

    try:
        import asyncpg
    except ImportError:
        return 0

    conn_pc = None
    conn_bf = None
    reconciled_count = 0
    try:
        conn_pc = await asyncpg.connect(pc_url, timeout=5.0)
        conn_bf = await asyncpg.connect(bf_url, timeout=5.0)

        logs = await conn_bf.fetch(
            """
            SELECT id, provider, model, prompt_tokens, completion_tokens,
                   cached_read_tokens, total_tokens, cost, timestamp
            FROM logs
            WHERE provider = 'deepseek' AND cost > 0
            ORDER BY timestamp ASC
            """
        )

        company_uuid = uuid.UUID(company_id)
        agent_uuid = uuid.UUID(agent_id)

        for log in logs:
            log_id_str = str(log["id"])
            try:
                log_uuid = uuid.UUID(log_id_str)
            except Exception:
                log_uuid = uuid.uuid4()

            cost_usd = float(log["cost"] or 0.0)
            cost_cents = round(cost_usd * 100.0, 7)
            p_tok = int(log["prompt_tokens"] or 0)
            c_tok = int(log["completion_tokens"] or 0)
            cached_tok = int(log["cached_read_tokens"] or 0)
            model_name = str(log["model"] or "deepseek-v4-pro")
            occurred = log["timestamp"]

            usage_payload = json.dumps({
                "cost_usd": cost_usd,
                "costUsd": cost_usd,
                "cost_cents": cost_cents,
                "provider": "deepseek",
                "model": model_name,
                "input_tokens": p_tok,
                "output_tokens": c_tok,
                "total_tokens": p_tok + c_tok,
            })

            await conn_pc.execute(
                """
                INSERT INTO cost_events (
                    id, company_id, agent_id, provider, model,
                    input_tokens, output_tokens, cached_input_tokens, cost_cents,
                    occurred_at, created_at, biller, billing_type, cost_status,
                    usage_kind, reported_cost_cents, provider_request_id, reported_usage_json
                ) VALUES (
                    $1, $2, $3, 'deepseek', $4,
                    $5, $6, $7, $8,
                    $9, $9, 'deepseek', 'metered_api', 'reported',
                    'agent', $8, $10, $11::jsonb
                )
                ON CONFLICT (id) DO UPDATE SET
                    cost_cents = EXCLUDED.cost_cents,
                    reported_cost_cents = EXCLUDED.reported_cost_cents,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    occurred_at = EXCLUDED.occurred_at
                """,
                log_uuid,
                company_uuid,
                agent_uuid,
                model_name,
                p_tok,
                c_tok,
                cached_tok,
                cost_cents,
                occurred,
                log_id_str,
                usage_payload,
            )
            reconciled_count += 1

        # Synchronize Hermes spent_monthly_cents to exact ledger sum for the current UTC month
        await conn_pc.execute(
            """
            UPDATE agents 
            SET spent_monthly_cents = (
                SELECT COALESCE(SUM(cost_cents), 0) 
                FROM cost_events 
                WHERE agent_id = $1 
                  AND occurred_at >= DATE_TRUNC('month', NOW())
            )
            WHERE id = $1
            """,
            agent_uuid,
        )

        logger.info("⚡ [Paperclip Bridge] Reconciled %d Bifrost cost events into Paperclip", reconciled_count)
        return reconciled_count
    except Exception as err:
        logger.warning("⚠️ [Paperclip Bridge] Reconcile Bifrost failed: %s", err)
        return 0
    finally:
        if conn_pc:
            await conn_pc.close()
        if conn_bf:
            await conn_bf.close()

async def record_telegram_turn(
    user_id: Any,
    prompt: str,
    reply: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_cents: float = 0.0,
    provider: str = "freellmapi",
    model: str = "auto",
    duration_sec: float = 0.0,
    company_id: str = DEFAULT_COMPANY_ID,
    agent_id: str = DEFAULT_HERMES_AGENT_ID,
) -> bool:
    """
    Records a completed Telegram conversation turn into Paperclip Control Plane:
    1. Creates a completed record in heartbeat_runs with token & cost telemetry.
    2. Emits an audit event in activity_log for real-time dashboard visibility.
    3. Updates agent last_heartbeat_at timestamp and active status.
    Fully fail-safe: failures are logged without blocking conversational flow.
    """
    db_url = get_paperclip_db_url()
    if not db_url:
        logger.debug("Paperclip database URL not available; skipping telemetry sync.")
        return False

    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg module not available in Hermes environment.")
        return False

    # Estimate token counts if not provided (~4 chars per token standard)
    if tokens_in <= 0 and prompt:
        tokens_in = max(1, len(prompt) // 4)
    if tokens_out <= 0 and reply:
        tokens_out = max(1, len(reply) // 4)

    run_id = uuid.uuid4()
    company_uuid = uuid.UUID(company_id)
    agent_uuid = uuid.UUID(agent_id)

    cost_usd = round(cost_cents / 100.0, 6)
    total_tokens = tokens_in + tokens_out

    usage_payload = json.dumps({
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "total_tokens": total_tokens,
        "inputTokens": tokens_in,
        "outputTokens": tokens_out,
        "totalTokens": total_tokens,
        "cost_cents": round(cost_cents, 4),
        "cost_usd": cost_usd,
        "costUsd": cost_usd,
        "provider": provider,
        "model": model,
        "duration_sec": round(duration_sec, 2),
    })

    summary_text = (reply[:197] + "...") if len(reply) > 200 else reply
    result_payload = json.dumps({
        "summary": summary_text,
        "provider": provider,
        "model": model,
        "cost_cents": round(cost_cents, 4),
        "cost_usd": cost_usd,
        "costUsd": cost_usd,
    })

    activity_details = json.dumps({
        "channel": "telegram",
        "user_id": str(user_id),
        "prompt": prompt[:300] if prompt else "",
        "reply": summary_text,
        "provider": provider,
        "model": model,
        "cost_cents": round(cost_cents, 4),
        "cost_usd": cost_usd,
        "tokens": {"input": tokens_in, "output": tokens_out, "total": total_tokens},
        "duration_sec": round(duration_sec, 2),
    })

    conn = None
    try:
        conn = await asyncpg.connect(db_url, timeout=5.0)

        # 1. Insert heartbeat run
        await conn.execute(
            """
            INSERT INTO heartbeat_runs (
                id, company_id, agent_id, invocation_source, status, trigger_detail,
                started_at, finished_at, stdout_excerpt, usage_json, result_json,
                scope_kind, runtime_mode, cost_accounting_pending, process_loss_retry_count,
                continuation_attempt, scheduled_retry_attempt, accounting_attempt_count, next_event_seq
            ) VALUES (
                $1, $2, $3, 'telegram', 'succeeded', $4,
                NOW() - ($5 || ' seconds')::interval, NOW(), $6, $7::jsonb,
                $8::jsonb, 'company', 'direct', false, 0, 0, 0, 0, 1
            )
            """,
            run_id,
            company_uuid,
            agent_uuid,
            f"Telegram ({provider}:{model}) interaction with user {user_id}",
            str(max(0.1, duration_sec)),
            summary_text,
            usage_payload,
            result_payload,
        )

        # 2. Insert into cost_events ledger for Paperclip Costs Tab
        await conn.execute(
            """
            INSERT INTO cost_events (
                id, company_id, agent_id, heartbeat_run_id, provider, model,
                input_tokens, output_tokens, cost_cents, occurred_at, created_at,
                biller, billing_type, cached_input_tokens, cost_status, usage_kind,
                reported_cost_cents, reported_usage_json
            ) VALUES (
                gen_random_uuid(), $1, $2, $3, $4, $5,
                $6, $7, $8, NOW(), NOW(),
                $4, 'metered_api', 0, 'reported', 'agent',
                $8, $9::jsonb
            )
            """,
            company_uuid,
            agent_uuid,
            run_id,
            provider,
            model,
            tokens_in,
            tokens_out,
            cost_cents,
            usage_payload,
        )

        # 3. Insert into activity log
        await conn.execute(
            """
            INSERT INTO activity_log (
                id, company_id, actor_type, actor_id, action, entity_type, entity_id,
                agent_id, run_id, details, created_at, responsible_user_id
            ) VALUES (
                gen_random_uuid(), $1, 'agent', $2, 'agent.telegram_turn', 'agent', $2,
                $3, $4, $5::jsonb, NOW(), $6
            )
            """,
            company_uuid,
            str(agent_id),
            agent_uuid,
            run_id,
            activity_details,
            DEFAULT_RESPONSIBLE_USER_ID,
        )

        # 3. Update agent heartbeat and spend
        await conn.execute(
            """
            UPDATE agents
            SET last_heartbeat_at = NOW(),
                status = 'idle',
                spent_monthly_cents = spent_monthly_cents + $2
            WHERE id = $1
            """,
            agent_uuid,
            float(cost_cents),
        )

        logger.info("⚡ [Paperclip Bridge] Recorded Telegram turn into Paperclip (run_id: %s)", run_id)
        if provider == "deepseek" or cost_cents > 0:
            import asyncio
            asyncio.create_task(reconcile_bifrost_to_paperclip(company_id=company_id, agent_id=agent_id))
        return True
    except Exception as err:
        logger.warning("⚠️ [Paperclip Bridge] Failed to record turn in Paperclip: %s", err)
        return False
    finally:
        if conn:
            try:
                await conn.close()
            except Exception:
                pass

async def list_paperclip_issues(
    status: Optional[str] = None,
    company_id: str = DEFAULT_COMPANY_ID,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Queries actionable issues from Paperclip Kanban board.
    """
    db_url = get_paperclip_db_url()
    if not db_url:
        return []

    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)
        query = """
            SELECT id, identifier, title, status, priority, created_at
            FROM issues
            WHERE company_id = $1
        """
        params = [uuid.UUID(company_id)]
        if status:
            query += " AND status = $2"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)

        rows = await conn.fetch(query, *params)
        await conn.close()
        return [
            {
                "id": str(r["id"]),
                "identifier": r["identifier"],
                "title": r["title"],
                "status": r["status"],
                "priority": r["priority"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    except Exception as err:
        logger.warning("Error querying Paperclip issues: %s", err)
        return []

async def create_paperclip_issue(
    title: str,
    description: str = "",
    priority: str = "medium",
    company_id: str = DEFAULT_COMPANY_ID,
    assignee_agent_id: str = DEFAULT_HERMES_AGENT_ID,
) -> Optional[Dict[str, Any]]:
    """
    Creates a new issue in Paperclip directly from conversational Hermes requests.
    """
    db_url = get_paperclip_db_url()
    if not db_url:
        return None

    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)

        # 1. Resolve issue prefix & calculate next sequence
        company_row = await conn.fetchrow(
            "SELECT issue_prefix FROM companies WHERE id = $1",
            uuid.UUID(company_id),
        )
        prefix = company_row["issue_prefix"] if company_row else "BAI"

        count_row = await conn.fetchrow(
            "SELECT COUNT(*) FROM issues WHERE company_id = $1",
            uuid.UUID(company_id),
        )
        seq = (count_row[0] if count_row else 0) + 1
        identifier = f"{prefix}-{seq}"

        issue_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO issues (
                id, company_id, identifier, title, description, status, priority,
                assignee_agent_id, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, 'todo', $6, $7, NOW(), NOW()
            )
            """,
            issue_id,
            uuid.UUID(company_id),
            identifier,
            title,
            description,
            priority,
            uuid.UUID(assignee_agent_id),
        )

        # Log activity
        await conn.execute(
            """
            INSERT INTO activity_log (
                id, company_id, actor_type, actor_id, action, entity_type, entity_id,
                agent_id, details, created_at, responsible_user_id
            ) VALUES (
                gen_random_uuid(), $1, 'agent', $2, 'issue.created', 'issue', $3,
                $4, $5::jsonb, NOW(), $6
            )
            """,
            uuid.UUID(company_id),
            str(assignee_agent_id),
            str(issue_id),
            uuid.UUID(assignee_agent_id),
            json.dumps({"identifier": identifier, "title": title, "source": "telegram_hermes"}),
            DEFAULT_RESPONSIBLE_USER_ID,
        )

        await conn.close()
        logger.info("📋 [Paperclip Bridge] Created issue %s: %s", identifier, title)
        return {
            "id": str(issue_id),
            "identifier": identifier,
            "title": title,
            "status": "todo",
            "priority": priority,
        }
    except Exception as err:
        logger.warning("Error creating Paperclip issue: %s", err)
        return None

async def register_paperclip_agent(
    name: str,
    title: str = "",
    role: str = "worker",
    adapter_type: str = "hermes_gateway",
    capabilities: str = "",
    budget_monthly_cents: int = 50000,
    reports_to: Optional[str] = DEFAULT_HERMES_AGENT_ID,
    company_id: str = DEFAULT_COMPANY_ID,
) -> Optional[Dict[str, Any]]:
    """
    Registers a permanent autonomous agent in Paperclip's Org Chart.
    """
    db_url = get_paperclip_db_url()
    if not db_url:
        return None

    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)

        agent_id = uuid.uuid4()
        reports_to_uuid = uuid.UUID(reports_to) if reports_to else None

        adapter_config = {
            "apiBaseUrl": "http://hermes:8000",
            "apiKey": "hermes-internal-key",
            "timeoutSec": 600,
            "sessionKeyStrategy": "issue",
            "dangerouslyAllowInsecureRemoteHttp": True,
        }
        if adapter_type == "pi_local":
            adapter_config = {
                "command": "pidev",
                "model": "bifrost/auto",
                "thinking": "medium",
                "env": {
                    "OPENAI_BASE_URL": "http://bifrost:8080/v1",
                    "OPENAI_API_KEY": clean_env("PIDEV_BIFROST_KEY", "vk-pidev"),
                },
            }

        runtime_config = {
            "heartbeat": {
                "enabled": True,
                "intervalSec": 300,
                "cooldownSec": 10,
                "wakeOnDemand": True,
                "maxConcurrentRuns": 5,
                "skipTimerWhenNoActionableWork": True,
            }
        }

        await conn.execute(
            """
            INSERT INTO agents (
                id, company_id, name, role, title, status, lifecycle_state,
                reports_to, capabilities, adapter_type, adapter_config,
                runtime_config, budget_monthly_cents, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, 'idle', 'ready',
                $6, $7, $8, $9::jsonb,
                $10::jsonb, $11, NOW(), NOW()
            )
            """,
            agent_id,
            uuid.UUID(company_id),
            name,
            role,
            title or f"{name} Specialist",
            reports_to_uuid,
            capabilities or f"Autonomous {name} agent for {title}",
            adapter_type,
            json.dumps(adapter_config),
            json.dumps(runtime_config),
            budget_monthly_cents,
        )

        # Log creation activity
        await conn.execute(
            """
            INSERT INTO activity_log (
                id, company_id, actor_type, actor_id, action, entity_type, entity_id,
                agent_id, details, created_at, responsible_user_id
            ) VALUES (
                gen_random_uuid(), $1, 'agent', $2, 'agent.registered', 'agent', $3,
                $4, $5::jsonb, NOW(), $6
            )
            """,
            uuid.UUID(company_id),
            str(reports_to or agent_id),
            str(agent_id),
            reports_to_uuid or agent_id,
            json.dumps({"name": name, "role": role, "title": title, "adapter_type": adapter_type}),
            DEFAULT_RESPONSIBLE_USER_ID,
        )

        await conn.close()
        logger.info("🤖 [Paperclip Bridge] Registered new permanent agent %s (%s) in Org Chart", name, role)
        return {
            "id": str(agent_id),
            "name": name,
            "role": role,
            "title": title,
            "reports_to": str(reports_to) if reports_to else None,
            "status": "idle",
        }
    except Exception as err:
        logger.warning("Error registering Paperclip agent: %s", err)
        return None

async def record_crewai_execution(
    mission: str,
    roles: Optional[List[Any]] = None,
    skills: Optional[List[str]] = None,
    output_summary: str = "",
    duration_sec: float = 0.0,
    success: bool = True,
    company_id: str = DEFAULT_COMPANY_ID,
    agent_id: str = DEFAULT_CREWAI_AGENT_ID,
) -> bool:
    """
    Records an ephemeral CrewAI swarm execution into Paperclip telemetry
    under the persistent CrewAI Engine worker (44444444-4444-4444-4444-444444444444).
    """
    db_url = get_paperclip_db_url()
    if not db_url:
        return False

    try:
        import asyncpg
        conn = await asyncpg.connect(db_url, timeout=5.0)

        run_id = uuid.uuid4()
        agent_uuid = uuid.UUID(agent_id)
        company_uuid = uuid.UUID(company_id)

        clean_roles = roles if roles and isinstance(roles, list) else []
        clean_skills = skills if skills and isinstance(skills, list) else []
        summary = (output_summary or "Execution completed")[:500]

        usage_payload = json.dumps({
            "duration_sec": round(duration_sec, 2),
            "roles_count": len(clean_roles),
            "skills": clean_skills,
            "cost_cents": 0,
            "cost_usd": 0.0,
            "costUsd": 0.0,
            "provider": "freellmapi",
            "model": "crewai-swarm",
        })
        result_payload = json.dumps({
            "status": "succeeded" if success else "failed",
            "summary": summary,
            "provider": "freellmapi",
            "model": "crewai-swarm",
            "cost_cents": 0,
            "cost_usd": 0.0,
        })
        activity_details = json.dumps({
            "mission": (mission or "")[:200],
            "roles": [r.get("role") if isinstance(r, dict) else str(r) for r in clean_roles],
            "skills": clean_skills,
            "duration_sec": round(duration_sec, 2),
            "success": success,
            "provider": "freellmapi",
            "model": "crewai-swarm",
            "cost_usd": 0.0,
        })

        # 1. Insert into heartbeat_runs under CrewAI Engine worker
        await conn.execute(
            """
            INSERT INTO heartbeat_runs (
                id, company_id, agent_id, invocation_source, status, trigger_detail,
                started_at, finished_at, stdout_excerpt, usage_json, result_json,
                scope_kind, runtime_mode, cost_accounting_pending, process_loss_retry_count,
                continuation_attempt, scheduled_retry_attempt, accounting_attempt_count, next_event_seq
            ) VALUES (
                $1, $2, $3, 'crewai_swarm', $4, $5,
                NOW() - ($6 || ' seconds')::interval, NOW(), $7, $8::jsonb,
                $9::jsonb, 'company', 'direct', false, 0, 0, 0, 0, 1
            )
            """,
            run_id,
            company_uuid,
            agent_uuid,
            "succeeded" if success else "failed",
            f"CrewAI Swarm: {mission[:120]}",
            str(max(0.1, duration_sec)),
            summary,
            usage_payload,
            result_payload,
        )

        # 2. Insert into cost_events ledger for Paperclip Costs Tab
        await conn.execute(
            """
            INSERT INTO cost_events (
                id, company_id, agent_id, heartbeat_run_id, provider, model,
                input_tokens, output_tokens, cost_cents, occurred_at, created_at,
                biller, billing_type, cached_input_tokens, cost_status, usage_kind,
                reported_cost_cents, reported_usage_json
            ) VALUES (
                gen_random_uuid(), $1, $2, $3, 'freellmapi', 'crewai-swarm',
                0, 0, 0.0, NOW(), NOW(),
                'freellmapi', 'metered_api', 0, 'reported', 'agent',
                0.0, $4::jsonb
            )
            """,
            company_uuid,
            agent_uuid,
            run_id,
            usage_payload,
        )

        # 3. Insert into activity_log
        await conn.execute(
            """
            INSERT INTO activity_log (
                id, company_id, actor_type, actor_id, action, entity_type, entity_id,
                agent_id, run_id, details, created_at, responsible_user_id
            ) VALUES (
                gen_random_uuid(), $1, 'agent', $2, 'crewai.swarm_executed', 'agent', $2,
                $3, $4, $5::jsonb, NOW(), $6
            )
            """,
            company_uuid,
            str(agent_id),
            agent_uuid,
            run_id,
            activity_details,
            DEFAULT_RESPONSIBLE_USER_ID,
        )

        # 3. Update agent heartbeat
        await conn.execute(
            """
            UPDATE agents
            SET last_heartbeat_at = NOW(),
                status = 'idle'
            WHERE id = $1
            """,
            agent_uuid,
        )

        await conn.close()
        logger.info("⚡ [Paperclip Bridge] Recorded CrewAI swarm execution for agent %s in %ss", agent_id, duration_sec)
        return True
    except Exception as err:
        logger.warning("Error recording CrewAI execution in Paperclip: %s", err)
        return False

