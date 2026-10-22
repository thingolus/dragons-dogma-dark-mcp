"""Read-only MCP stdio smoke and latency measurements against the configured project."""

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def main():
    samples, checks = [], {}
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "ddda_mcp", "--project", str(ROOT)]
    )
    async with Client(parameters, read_timeout_seconds=30) as client:
        tools = await client.list_tools()
        checks["tool_count"] = len(tools.tools)
        checks["all_output_schemas_present"] = all(tool.output_schema for tool in tools.tools)
        for name, arguments in [
            ("project_status", {}),
            ("verify_upstream", {}),
            ("inspect_build", {}),
            ("lookup_symbol", {"name_or_rva": "pawn_movement_consume"}),
            ("inspect_binary", {"mode": "disassembly", "value": "0x751ee0", "size": 32}),
            ("read_source", {"path": "include/coop/runtime_status.hpp", "limit": 25}),
            ("session_status", {}),
        ]:
            result = await client.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(f"{name}: {result.structured_content}")
            checks[name] = {"success": True, "bytes": len(json.dumps(result.structured_content).encode())}
            if name == "project_status":
                checks["knowledge_documents"] = result.structured_content["data"]["knowledge_documents"]
            if name == "verify_upstream":
                checks["verified_source_files"] = result.structured_content["data"]["verified_files"]
            if name == "inspect_build":
                checks["adapter_supported"] = result.structured_content["data"]["adapter_supported"]
        for index in range(6):
            start = time.perf_counter()
            result = await client.call_tool("search_knowledge", {"query": "menu ownership", "limit": 5})
            if result.is_error or not result.structured_content["data"]["results"]:
                raise RuntimeError("Expected research search results")
            samples.append(
                {
                    "iteration": index,
                    "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
                    "output_bytes": len(json.dumps(result.structured_content).encode()),
                }
            )
        resource = await client.read_resource("ddda://symbols/pawn_movement_consume")
        checks["symbol_resource"] = "pawn_movement_consume" in resource.contents[0].text
    warm = [sample["elapsed_ms"] for sample in samples[1:]]
    report = {
        "evidence_class": "static",
        "checks": checks,
        "search_measurements": samples,
        "warm_search_median_ms": statistics.median(warm),
        "warm_search_range_ms": [min(warm), max(warm)],
        "limitations": [
            "No native game launch or mutation.",
            "No baseline AI workflow/token comparison; no speedup claimed.",
            "Native, Ghidra and C++ build acceptance remain separate.",
        ],
    }
    output = ROOT / "artifacts/validation/stdio-smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
