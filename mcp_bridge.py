"""
Sovereign Zerops Control Plane MCP Bridge (v1.0)
Native, zero-dependency async stdio JSON-RPC client connecting Hermes Agent
directly to the official 'zcp serve' MCP server.
Provides 24 native Zerops platform tools without bespoke wrappers.
"""
import os
import sys
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("hermes.mcp_bridge")

ZCP_CANDIDATES = [
    "/mnt/localstorage/bin/zcp",
    "/usr/local/bin/zcp",
    "/var/www/bin/zcp",
]

def resolve_zcp_binary() -> str:
    """Finds the executable zcp binary across known mount paths."""
    for path in ZCP_CANDIDATES:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    raise FileNotFoundError("zcp binary not found in /mnt/localstorage/bin or /usr/local/bin")

async def execute_mcp_request(method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 180.0) -> Dict[str, Any]:
    """
    Executes a single JSON-RPC 2.0 exchange with 'zcp serve' over standard I/O.
    Ensures safe initialization and graceful process shutdown.
    """
    zcp_bin = resolve_zcp_binary()
    proc = await asyncio.create_subprocess_exec(
        zcp_bin, "serve",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024
    )

    try:
        # 1. Initialize MCP handshake
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hermes-agent", "version": "1.0"}
            }
        }
        proc.stdin.write(json.dumps(init_req).encode("utf-8") + b"\n")
        await proc.stdin.drain()

        # Read handshake response
        init_raw = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        if not init_raw:
            raise RuntimeError("zcp serve closed stream without initialize response")

        # 2. Execute target method
        req_id = 2
        call_req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        proc.stdin.write(json.dumps(call_req).encode("utf-8") + b"\n")
        await proc.stdin.drain()

        resp_raw = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        if not resp_raw:
            raise RuntimeError(f"zcp serve closed stream during {method}")

        return json.loads(resp_raw.decode("utf-8"))
    finally:
        try:
            if proc.stdin:
                proc.stdin.close()
                await proc.stdin.wait_closed()
        except Exception:
            pass
        try:
            proc.terminate()
            await proc.wait()
        except Exception:
            pass

async def call_zerops_mcp(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
    """
    Invokes any of the 24 native Zerops MCP tools via 'zcp serve'.
    Returns the parsed text content or formatted error message.
    """
    try:
        clean_args = arguments if isinstance(arguments, dict) else {}
        resp = await execute_mcp_request("tools/call", {"name": tool_name, "arguments": clean_args})
        
        if "error" in resp:
            err = resp["error"]
            return f"❌ Error en Zerops MCP ({tool_name}): {err.get('message', str(err))}"
        
        result = resp.get("result", {})
        content_items = result.get("content", [])
        if content_items and isinstance(content_items, list):
            text_parts = [item.get("text", "") for item in content_items if isinstance(item, dict) and item.get("type") == "text"]
            return "\n".join(text_parts).strip()
        
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error executing Zerops MCP tool {tool_name}: {e}", exc_info=True)
        return f"❌ Error comunicando con zcp serve ({tool_name}): {str(e)}"

async def list_zerops_mcp_tools() -> List[Dict[str, Any]]:
    """Retrieves the schemas for all 24 native Zerops MCP tools."""
    try:
        resp = await execute_mcp_request("tools/list", {})
        return resp.get("result", {}).get("tools", [])
    except Exception as e:
        logger.error(f"Error listing Zerops MCP tools: {e}")
        return []

def run_tests() -> bool:
    """Deterministic verification test suite (Exit Code 0)."""
    print("Testing ZCP binary resolution...")
    bin_path = resolve_zcp_binary()
    print(f"✓ Binary found at: {bin_path}")

    print("Testing zcp serve handshake and tools/list...")
    tools = asyncio.run(list_zerops_mcp_tools())
    assert len(tools) >= 20, f"Expected >= 20 tools, found {len(tools)}"
    print(f"✓ Tools/list succeeded with {len(tools)} tools registered.")

    print("Testing tools/call with zerops_discover...")
    discovery = asyncio.run(call_zerops_mcp("zerops_discover", {}))
    assert "project" in discovery and "services" in discovery, f"Unexpected discovery format: {discovery[:200]}"
    print("✓ zerops_discover executed successfully via MCP bridge.")
    print("All tests passed with exit code 0.")
    return True

if __name__ == "__main__":
    if "--test" in sys.argv:
        try:
            success = run_tests()
            sys.exit(0 if success else 1)
        except Exception as err:
            print(f"Test failed: {err}", file=sys.stderr)
            sys.exit(1)
    else:
        # Quick CLI runner: python3 mcp_bridge.py zerops_discover
        cmd = sys.argv[1] if len(sys.argv) > 1 else "zerops_discover"
        args_json = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(asyncio.run(call_zerops_mcp(cmd, args_json)))
