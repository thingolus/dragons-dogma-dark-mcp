"""Paired direct-command/MCP measurements; not an LLM productivity experiment."""

import asyncio
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ddda_mcp import __version__
from ddda_mcp.common import atomic_json, utc_now
from ddda_mcp.config import Config

ROOT = Path(__file__).resolve().parents[1]


async def main():
    config = Config.load(ROOT)
    pin = config.settings.coop_source_commit
    git = ["git", "-C", str(config.source)]
    cases = [
        {
            "name": "Read copied runtime ABI",
            "command": [*git, "show", f"{pin}:include/coop/runtime_status.hpp"],
            "tool": "read_source",
            "args": {"path": "include/coop/runtime_status.hpp", "limit": 100},
        },
        {
            "name": "Locate pawn_delete RVA",
            "command": [
                *git,
                "grep",
                "-n",
                "-F",
                "pawn_delete",
                pin,
                "--",
                "research/symbols.csv",
                "include/coop/supported_build.hpp",
            ],
            "tool": "lookup_symbol",
            "args": {"name_or_rva": "pawn_delete"},
        },
        {
            "name": "Fingerprint executable",
            "command": [
                sys.executable,
                str(ROOT / "scripts/benchmark_baseline.py"),
                str(config.game / "DDDA.exe"),
            ],
            "tool": "inspect_build",
            "args": {},
        },
        {
            "name": "Find menu ownership evidence",
            "command": [
                *git,
                "grep",
                "-n",
                "-i",
                "-F",
                "menu ownership",
                pin,
                "--",
                "docs/*.md",
                "research/EXP-*.md",
            ],
            "tool": "search_knowledge",
            "args": {"query": "menu ownership", "limit": 5},
        },
    ]
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "ddda_mcp", "--project", str(ROOT)]
    )
    started = time.perf_counter()
    report = {
        "version": __version__,
        "captured_at": utc_now(),
        "source_commit": pin,
        "evidence_class": "static_paired_workflows",
        "repetitions": 5,
        "workflows": [],
    }
    async with Client(parameters, read_timeout_seconds=30) as client:
        await client.list_tools()
        report["mcp_startup_and_discovery_ms"] = round((time.perf_counter() - started) * 1000, 3)
        for case in cases:
            samples = []
            for iteration in range(5):
                output, timing, sizes = {}, {}, {}
                order = ["direct", "mcp"] if iteration % 2 == 0 else ["mcp", "direct"]
                for route in order:
                    tick = time.perf_counter()
                    if route == "direct":
                        result = await asyncio.to_thread(
                            subprocess.run, case["command"], capture_output=True, check=True, timeout=30
                        )
                        output[route] = result.stdout.decode("utf-8-sig")
                        sizes[route] = len(result.stdout)
                    else:
                        result = await client.call_tool(case["tool"], case["args"])
                        assert not result.is_error, result.structured_content
                        output[route] = result.structured_content["data"]
                        # One structured result, not both duplicated SDK text and structured blocks.
                        sizes[route] = len(json.dumps(result.structured_content, ensure_ascii=False).encode())
                    timing[route] = round((time.perf_counter() - tick) * 1000, 3)
                direct, mcp = output["direct"], output["mcp"]
                if case["tool"] == "read_source":
                    assert direct.splitlines() == [line["text"] for line in mcp["lines"]]
                    quality = "Exact source lines match"
                elif case["tool"] == "lookup_symbol":
                    symbol = next(s for s in mcp["symbols"] if s["name"] == "pawn_delete")
                    assert symbol["runtime_signature"]["rva"].lower() in direct.lower()
                    quality = "Same symbol and runtime RVA"
                elif case["tool"] == "inspect_build":
                    baseline = json.loads(direct)
                    assert all(mcp[k] == v for k, v in baseline.items())
                    report["game_sha256"] = mcp["sha256"]
                    quality = "SHA-256, size, architecture and image base match"
                else:
                    assert "menu ownership" in direct.lower() and mcp["results"]
                    assert all(r["source"]["commit"] == pin for r in mcp["results"])
                    quality = "Both find pinned evidence; phrase grep and ranked word search are not identical retrieval"
                samples.append(
                    {
                        "iteration": iteration,
                        "order": order,
                        "elapsed_ms": timing,
                        "response_utf8_bytes": sizes,
                        "checks_passed": True,
                    }
                )
            report["workflows"].append(
                {
                    "name": case["name"],
                    "quality": quality,
                    "samples": samples,
                    "direct_median_ms": statistics.median(s["elapsed_ms"]["direct"] for s in samples),
                    "mcp_median_ms": statistics.median(s["elapsed_ms"]["mcp"] for s in samples),
                    "direct_response_bytes": statistics.median(
                        s["response_utf8_bytes"]["direct"] for s in samples
                    ),
                    "mcp_response_bytes": statistics.median(s["response_utf8_bytes"]["mcp"] for s in samples),
                    "calls_per_route": 1,
                }
            )
    report["limitations"] = [
        "Scripted paired tool workflows, not independent AI task completion; reasoning time and model tokens were not measured.",
        "Five pairs per task; alternating order, existing OS caches, first MCP calls include lazy initialization.",
        "MCP startup/discovery is reported separately; direct commands start a process per operation.",
        "Direct commands are prewritten; MCP returns richer provenance/guards. Output sizes are not equivalent content or token counts.",
        "No gameplay, builds, Ghidra analysis time, or overall development speedup is inferred.",
    ]
    atomic_json(ROOT / "artifacts/validation/workflow-benchmark.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "workflows"}, indent=2))
    for row in report["workflows"]:
        print(json.dumps({k: v for k, v in row.items() if k != "samples"}))


if __name__ == "__main__":
    asyncio.run(main())
