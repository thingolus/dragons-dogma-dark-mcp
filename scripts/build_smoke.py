"""Run the real MCP build job on an isolated upstream checkout; no game access."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from mcp import Client

from ddda_mcp.config import Config
from ddda_mcp.server import create_server

ROOT = Path(__file__).resolve().parents[1]


async def main(cmake: str):
    config = Config.load(ROOT)
    config.settings.profile = "development"
    config.settings.cmake = cmake
    server, app = create_server(config)
    async with Client(server) as client:
        result = await client.call_tool("build_and_test", {"configuration": "Debug", "test_group": "core"})
        if result.is_error:
            raise RuntimeError(result.structured_content)
        job_id = result.structured_content["data"]["job_id"]
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            status = await client.call_tool("job_status", {"job_id": job_id})
            receipt = status.structured_content["data"]
            if receipt["state"] not in {"queued", "running"}:
                report = {"job": receipt}
                if "artifact_id" in receipt.get("result", {}):
                    report["evidence"] = app.artifacts.get(receipt["result"]["artifact_id"])
                path = ROOT / "artifacts/validation/core-build.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(receipt, indent=2))
                if not receipt.get("result", {}).get("summary", {}).get("passed"):
                    raise SystemExit(1)
                return
            await asyncio.sleep(2)
        raise TimeoutError("Build smoke exceeded ten minutes; server shutdown will cancel its job.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cmake", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.cmake))
