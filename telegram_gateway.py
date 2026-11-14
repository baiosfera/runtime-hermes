"""
Hermes-Agent Telegram Gateway
Provides a private Telegram Bot interface for the owner/administrator.
Features dormant standby mode when TELEGRAM_BOT_TOKEN is not configured,
Zero-Trust whitelist security, continuous keep_typing feedback,
and resilient multi-tier message chunking.
"""
import os
import re
import sys
import time
import asyncio
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hermes.telegram")

try:
    from env_utils import clean_env
except (ImportError, ValueError):
    from .env_utils import clean_env

ADMIN_TOKEN = clean_env("TELEGRAM_ADMIN_BOT_TOKEN") or clean_env("TELEGRAM_BOT_TOKEN")
CLIENT_TOKEN = clean_env("TELEGRAM_CLIENT_BOT_TOKEN")

ADMIN_ALLOWED_USERS_RAW = clean_env("TELEGRAM_ADMIN_ALLOWED_USERS") or clean_env("TELEGRAM_ALLOWED_USERS")
ADMIN_ALLOWED_USERS = {
    int(x.strip())
    for x in ADMIN_ALLOWED_USERS_RAW.split(",")
    if x.strip() and x.strip().lstrip("-").isdigit()
}

CLIENT_ALLOWED_USERS_RAW = clean_env("TELEGRAM_CLIENT_ALLOWED_USERS")
CLIENT_ALLOWED_USERS = {
    int(x.strip())
    for x in CLIENT_ALLOWED_USERS_RAW.split(",")
    if x.strip() and x.strip().lstrip("-").isdigit()
}

try:
    from agent import HermesAgent
except (ImportError, ValueError):
    from .agent import HermesAgent

try:
    from paperclip_bridge import record_telegram_turn
except (ImportError, ValueError):
    try:
        from .paperclip_bridge import record_telegram_turn
    except Exception:
        record_telegram_turn = None

async def run_dormant_loop():
    logger.info("ℹ️ No TELEGRAM_BOT_TOKEN provided. Gateway running in dormant standby mode.")
    logger.info(
        "To activate Telegram post-deploy for this brand, set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USERS "
        "(comma-separated numeric Telegram user IDs) in Zerops Vault and restart hermes."
    )
    while True:
        await asyncio.sleep(3600)

@asynccontextmanager
async def keep_typing(bot, chat_id: int, interval: float = 4.0):
    """
    Maintains continuous 'typing...' feedback in Telegram for long-running operations.
    Cancels cleanly upon exit.
    """
    stop_event = asyncio.Event()

    async def _loop():
        while not stop_event.is_set():
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

async def send_split_message(update, text: str, max_chunk_size: int = 3900, parse_mode: str = "Markdown"):
    """
    Splits long responses (>4096 chars) into balanced Markdown chunks
    preserving codeblock closures (```) and provides a resilient multi-tier
    fallback to plain text if Telegram Markdown parsing fails.
    """
    if not text:
        return

    chunks = []
    lines = text.splitlines(keepends=True)
    current_chunk = []
    current_len = 0
    in_code_block = False
    current_lang = ""

    code_fence_pattern = re.compile(r"^```(\w*)")

    for line in lines:
        fence_match = code_fence_pattern.match(line.strip())
        needed_margin = 10 if in_code_block else 0

        if current_len + len(line) + needed_margin > max_chunk_size:
            if current_chunk:
                if in_code_block:
                    current_chunk.append("\n```")
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_len = 0
                if in_code_block:
                    current_chunk.append(f"```{current_lang}\n")
                    current_len = len(current_chunk[0])

            while len(line) > max_chunk_size:
                chunks.append(line[:max_chunk_size])
                line = line[max_chunk_size:]

        current_chunk.append(line)
        current_len += len(line)

        if fence_match:
            if not in_code_block:
                in_code_block = True
                current_lang = fence_match.group(1)
            else:
                in_code_block = False
                current_lang = ""

    if current_chunk:
        if in_code_block:
            current_chunk.append("\n```")
        chunks.append("".join(current_chunk))

    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            await update.message.reply_text(chunk, parse_mode=parse_mode)
        except Exception as parse_err:
            logger.warning(f"Formatting error with {parse_mode} ({parse_err}). Falling back to plain text.")
            await update.message.reply_text(chunk, parse_mode=None)
        if len(chunks) > 1:
            await asyncio.sleep(0.3)

def build_bot_app(token: str, role: str, allowed_users: set, bifrost_key: str):
    from telegram import Update
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        TypeHandler,
        ApplicationHandlerStop,
        filters,
        ContextTypes
    )

    agent = HermesAgent(role=role, bifrost_key=bifrost_key)
    app = ApplicationBuilder().token(token).build()

    async def security_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not allowed_users:
            uid = update.effective_user.id if update.effective_user else "desconocido"
            logger.warning(f"⛔ Telegram fail-closed ({role}): allowlist vacía, rechazado User ID {uid}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Bot en modo cerrado: configurá TELEGRAM_ALLOWED_USERS en Zerops Vault (tu ID: {uid})."
                )
            raise ApplicationHandlerStop
        user = update.effective_user
        if not user or user.id not in allowed_users:
            uid = user.id if user else "desconocido"
            logger.warning(f"⛔ Acceso no autorizado ({role}): User ID {uid}")
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Acceso no autorizado para el bot de {role}. Tu Telegram User ID ({uid}) no está registrado."
                )
            raise ApplicationHandlerStop

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        project_name = clean_env("PROJECT_NAME", "default").replace("_", " ").title()
        msg = (
            f"👋 *Hola. Soy Hermes, tu copiloto soberano en Zerops ({project_name}).*\n\n"
            "Capacidades operativas en Fase 1 (Apotelos Mesh):\n"
            "• `/status` - Salud del gateway y servicios Zerops\n"
            "• `/reset` - Limpiar historial y ventana de contexto\n"
            "• 🧠 *Enjambres CrewAI*: Orquestación de cuadrillas (research, timing, SEO)\n"
            "• 📋 *Gestión Linear*: Creación y seguimiento de issues y proyectos\n"
            "• 📎 *Paperclip AI*: Gobernanza de agentes y control de spend caps\n"
            "• 🛡️ *PydanticAI*: Extracción y validación estricta de esquemas\n"
            "• 💾 *Memoria Engram*: Búsqueda y persistencia cross-session\n"
            "• ⚙️ *Plataforma Zerops*: Diagnóstico y control de servicios en vivo\n\n"
            "Escribime en lenguaje natural cualquier instrucción, análisis u orden operativa."
        )
        await send_split_message(update, msg)

    async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            f"🟢 Hermes Status ({role.upper()}): OPERATIONAL\n"
            f"• Virtual Key: {bifrost_key}\n"
            f"• Rol: {role}\n"
            f"• Base de Datos: PostgreSQL 18 (Paperclip & Mesh Store)\n"
            f"• Whitelist: {'Activa (' + str(len(allowed_users)) + ' usuarios)' if allowed_users else 'Cerrada (sin usuarios autorizados)'}"
        )

    async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        cid = update.effective_chat.id
        agent.history = []
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            try:
                import asyncpg
                conn = await asyncpg.connect(db_url, timeout=3.0)
                await conn.execute("DELETE FROM hermes_messages WHERE chat_id = $1", cid)
                await conn.close()
            except Exception:
                pass
        try:
            import aiosqlite
            db_path = "/mnt/localstorage/hermes/sessions.db"
            if os.path.exists(db_path):
                async with aiosqlite.connect(db_path, timeout=3.0) as db:
                    await db.execute("DELETE FROM hermes_messages WHERE chat_id = ?", (cid,))
                    await db.commit()
        except Exception:
            pass
        await update.message.reply_text("🧹 Historial y ventana de contexto reiniciados con éxito.")

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message:
            return

        user_text = update.message.text or update.message.caption or ""
        photo_path = None

        if update.message.photo:
            try:
                photo = update.message.photo[-1]
                file_obj = await context.bot.get_file(photo.file_id)
                storage_dir = "/mnt/localstorage/uploads" if os.path.exists("/mnt/localstorage") else "/var/www/localstorage/uploads"
                os.makedirs(storage_dir, exist_ok=True)
                filename = f"telegram_{update.message.id}_{photo.file_unique_id}.jpg"
                dest_path = os.path.join(storage_dir, filename)
                await file_obj.download_to_drive(dest_path)
                photo_path = dest_path
                logger.info(f"[{role.upper()}] Foto guardada exitosamente en: {photo_path}")
            except Exception as pe:
                logger.error(f"[{role.upper()}] Error al descargar foto de Telegram: {pe}")

        doc_path = None
        if update.message.document:
            try:
                doc = update.message.document
                file_obj = await context.bot.get_file(doc.file_id)
                storage_dir = "/mnt/localstorage/uploads" if os.path.exists("/mnt/localstorage") else "/var/www/localstorage/uploads"
                os.makedirs(storage_dir, exist_ok=True)
                clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', doc.file_name or "document.bin")
                filename = f"telegram_{update.message.id}_{clean_name}"
                dest_path = os.path.join(storage_dir, filename)
                await file_obj.download_to_drive(dest_path)
                doc_path = dest_path
                logger.info(f"[{role.upper()}] Documento guardado exitosamente en: {doc_path}")
            except Exception as de:
                logger.error(f"[{role.upper()}] Error al descargar documento de Telegram: {de}")

        if not user_text and not photo_path and not doc_path:
            return

        if photo_path:
            user_text = f"[Foto recibida y guardada localmente en {photo_path}]: {user_text}".strip()
        if doc_path:
            user_text = f"[Documento recibido y guardado localmente en {doc_path}]: {user_text}".strip()

        chat_id = update.effective_chat.id
        logger.info(f"[{role.upper()}] Prompt from chat {chat_id}: {user_text[:50]}...")
        turn_start_time = time.time()
        async with keep_typing(context.bot, chat_id):
            try:
                reply = await agent.run_turn(user_text, chat_id=chat_id)
                turn_duration = time.time() - turn_start_time
                await send_split_message(update, reply)

                # Sincronización automática de telemetría hacia Paperclip Control Plane
                if record_telegram_turn:
                    try:
                        telemetry = getattr(agent, "last_turn_telemetry", {})
                        asyncio.create_task(
                            record_telegram_turn(
                                user_id=chat_id,
                                prompt=user_text,
                                reply=reply,
                                tokens_in=telemetry.get("prompt_tokens", 0),
                                tokens_out=telemetry.get("completion_tokens", 0),
                                cost_cents=telemetry.get("cost_cents", 0.0),
                                provider=telemetry.get("provider", "freellmapi"),
                                model=telemetry.get("model", "auto"),
                                duration_sec=turn_duration
                            )
                        )
                    except Exception as bridge_err:
                        logger.warning(f"[{role.upper()}] Error despachando telemetría a Paperclip: {bridge_err}")
            except Exception as e:
                logger.error(f"[{role.upper()}] Error processing turn: {e}")
                await update.message.reply_text(f"⚠️ Error al procesar tu solicitud: {str(e)}")

    async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message:
            await update.message.reply_text("🎙️ Recibí tu mensaje de voz. Actualmente proceso texto, fotos y documentos. Escribime tu instrucción.")

    app.add_handler(TypeHandler(Update, security_gate), group=-1)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    # Route ALL other messages (including any custom slash commands like /plan, /run, etc.) directly to Hermes
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.COMMAND, handle_message))
    return app

async def run_bot():
    admin_token = ADMIN_TOKEN or clean_env("TELEGRAM_ADMIN_BOT_TOKEN") or clean_env("TELEGRAM_BOT_TOKEN")
    client_token = CLIENT_TOKEN or clean_env("TELEGRAM_CLIENT_BOT_TOKEN")
    admin_allowed_raw = clean_env("TELEGRAM_ADMIN_ALLOWED_USERS") or clean_env("TELEGRAM_ALLOWED_USERS")
    admin_allowed = ADMIN_ALLOWED_USERS or {int(x.strip()) for x in admin_allowed_raw.split(",") if x.strip() and x.strip().lstrip("-").isdigit()}

    if not admin_token and not client_token:
        await run_dormant_loop()
        return

    try:
        import telegram
    except ImportError:
        logger.warning("python-telegram-bot is not installed. Running in dormant standby mode.")
        await run_dormant_loop()
        return

    apps = []
    if admin_token:
        admin_app = build_bot_app(
            token=admin_token,
            role="admin",
            allowed_users=admin_allowed,
            bifrost_key="vk-hermes-agent"
        )
        apps.append(admin_app)

    if client_token and client_token != admin_token:
        client_allowed_raw = clean_env("TELEGRAM_CLIENT_ALLOWED_USERS")
        client_allowed = CLIENT_ALLOWED_USERS or {int(x.strip()) for x in client_allowed_raw.split(",") if x.strip() and x.strip().lstrip("-").isdigit()}
        client_app = build_bot_app(
            token=client_token,
            role="client",
            allowed_users=client_allowed,
            bifrost_key=clean_env("BIFROST_VK_CLIENT", "vk-hermes-agent")
        )
        apps.append(client_app)

    logger.info(f"🚀 Starting Hermes Telegram Gateway ({len(apps)} active bot instance(s))...")
    for app in apps:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(10)
            for app in apps:
                if app.updater and not app.updater.running:
                    logger.warning("⚠️ Telegram updater stopped! Attempting recovery...")
                    try:
                        await app.updater.start_polling(drop_pending_updates=True)
                        logger.info("✅ Telegram updater recovered successfully.")
                    except Exception as poll_err:
                        logger.error(f"Failed to recover telegram polling: {poll_err}")
    finally:
        for app in apps:
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception:
                pass

def main():
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Hermes Telegram Gateway stopped by user.")

if __name__ == "__main__":
    main()
