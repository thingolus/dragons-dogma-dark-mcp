"""Exercise the installed public package through stdio without game or source checkout."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    with tempfile.TemporaryDirectory(prefix="ddda-public-install-") as directory:
        root = Path(directory).resolve()
        (root / "config").mkdir()
        (root / "config/local.json").write_text(
            json.dumps(
                {"profile": "development", "coop_source_root": "missing-source", "game_root": "missing-game"}
            ),
            encoding="utf-8",
        )
        parameters = StdioServerParameters(
            command=sys.executable, args=["-I", "-m", "ddda_mcp", "--project", str(root)], cwd=str(root)
        )
        checks = {}
        async with Client(parameters, read_timeout_seconds=30) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 103
            assert all(tool.output_schema for tool in tools.tools)
            for name, arguments in [
                ("project_status", {}),
                ("verify_upstream", {}),
                ("lookup_symbol", {"name_or_rva": "pawn_movement_consume"}),
                ("read_source", {"path": "include/coop/runtime_status.hpp", "limit": 5}),
                ("ddda_sdk_catalog", {}),
                ("generate_ddda_sdk", {}),
            ]:
                result = await client.call_tool(name, arguments)
                assert not result.is_error, (name, result.structured_content)
                assert result.structured_content["success"], (name, result.structured_content)
                data = result.structured_content["data"]
                if name == "project_status":
                    assert data["source_access"] == "bundled_snapshot"
                    assert data["upstream_compatibility"]["status"] == "unchanged"
                elif name == "verify_upstream":
                    assert data["verified_files"] == 50
                elif name == "generate_ddda_sdk":
                    sdk = Path(data["directory"]).resolve()
                    assert sdk.is_relative_to(root)
                    assert (sdk / "native_sdk.cpp").is_file()
                    assert (sdk / "example_mod.cpp").is_file()
                    assert "Thingolus" in (sdk / "LICENSE").read_text(encoding="utf-8")
                checks[name] = "passed"
        print(json.dumps({"tool_count": len(tools.tools), "source_checkout": False, "checks": checks}))


if __name__ == "__main__":
    asyncio.run(main())
