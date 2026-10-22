"""Register this local stdio server with Codex, then verify its saved command."""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ddda_mcp.common import atomic_json

ROOT = Path(__file__).resolve().parents[1]
NAME = "dragons-dogma-dark"


async def main():
    cli = shutil.which("codex")
    if not cli:
        raise RuntimeError("Codex CLI must be installed and on PATH.")
    command = str(Path(sys.executable).resolve())
    args = ["-m", "ddda_mcp", "--project", str(ROOT)]
    result = subprocess.run([cli, "mcp", "get", NAME, "--json"], capture_output=True, text=True, timeout=30)
    if result.returncode:
        if "No MCP server named" not in result.stderr:
            raise RuntimeError("Cannot read Codex MCP configuration; no changes made.")
        subprocess.run([cli, "mcp", "add", NAME, "--", command, *args], check=True, timeout=30)
        result = subprocess.run(
            [cli, "mcp", "get", NAME, "--json"], capture_output=True, text=True, check=True, timeout=30
        )
    entry = json.loads(result.stdout)
    transport = entry["transport"]
    if (
        transport["type"] != "stdio"
        or Path(transport["command"]).resolve() != Path(command)
        or transport.get("args") != args
        or not entry.get("enabled")
    ):
        raise RuntimeError("An existing Codex entry differs; it was preserved for review.")
    async with Client(
        StdioServerParameters(command=transport["command"], args=transport["args"]), read_timeout_seconds=30
    ) as client:
        tools = await client.list_tools()
        result = await client.call_tool("project_status", {})
        assert not result.is_error
        status = result.structured_content["data"]
        assert status["creator"] == "Thingolus"
        report = {
            "registered": True,
            "server": NAME,
            "command_verified": True,
            "stdio_handshake": True,
            "tool_count": len(tools.tools),
            "version": status["version"],
            "note": "Saved Codex configuration verified; an already-running chat may need a new session to discover it.",
        }
    atomic_json(ROOT / "artifacts/validation/codex-connection.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
