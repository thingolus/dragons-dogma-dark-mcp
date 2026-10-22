"""Verify the real stdio Ghidra tool against the explicitly prepared local database."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from native_smoke import job

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import atomic_json
from ddda_mcp.config import Config

ROOT = Path(__file__).resolve().parents[1]


async def main():
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "ddda_mcp", "--project", str(ROOT)]
    )
    async with Client(parameters, read_timeout_seconds=60) as client:
        receipt = await job(client, "decompile_symbol", {"symbol_name": "pawn_delete"})
        artifact = Artifacts(Config.load(ROOT)).get(receipt["result"]["artifact_id"])
        report = {"job": receipt, "evidence": artifact}
        atomic_json(ROOT / "artifacts/validation/ghidra.json", report)
        assert receipt["result"]["summary"]["passed"], artifact["data"]["process"]
        assert len(artifact["data"]["export"]["code"]) > 20
        print(
            json.dumps(
                {
                    "passed": True,
                    "artifact_id": artifact["id"],
                    "code_characters": len(artifact["data"]["export"]["code"]),
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
