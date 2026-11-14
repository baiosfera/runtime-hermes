#!/usr/bin/env python3
"""Interactive REPL CLI for HermesAgent inside ttyd/tmux."""
import asyncio
import os
import sys

try:
    import readline  # noqa: F401
except ImportError:
    pass

from agent import HermesAgent
from env_utils import clean_env


async def run_repl() -> int:
    project_name = clean_env("PROJECT_NAME", "zerops")
    bifrost_key = clean_env("BIFROST_VIRTUAL_KEY", "vk-hermes-agent")
    agent = HermesAgent(role="admin", bifrost_key=bifrost_key)
    chat_id = int(clean_env("HERMES_CLI_CHAT_ID", "0") or "0")

    print(f"=== Hermes-Agent Interactive REPL ({project_name}) ===")
    print("Connected to Bifrost:", clean_env("HERMES_MODEL_ENDPOINT", "http://bifrost:8080/v1"))
    print("Commands: /help | /reset | /status | /exit")
    print("")

    while True:
        try:
            prompt = await asyncio.to_thread(input, "hermes> ")
        except (EOFError, KeyboardInterrupt):
            print("\nExiting Hermes REPL.")
            return 0

        text = prompt.strip()
        if not text:
            continue
        if text in {"/exit", "/quit", "exit", "quit"}:
            print("Bye.")
            return 0
        if text == "/help":
            print("Commands: /help, /reset, /status, /exit — or type any instruction for HermesAgent.")
            continue
        if text == "/reset":
            agent.history = []
            print("Session history cleared.")
            continue
        if text == "/status":
            print(f"role=admin project={project_name} model={clean_env('HERMES_MODEL_NAME', 'auto')} history={len(agent.history)}")
            continue

        try:
            reply = await agent.run_turn(text, chat_id=chat_id)
            print(f"\n{reply}\n")
        except Exception as err:
            print(f"[ERROR] {err}", file=sys.stderr)


if __name__ == "__main__":
    os.chdir(os.getenv("HERMES_WORKDIR", "/var/www"))
    raise SystemExit(asyncio.run(run_repl()))
