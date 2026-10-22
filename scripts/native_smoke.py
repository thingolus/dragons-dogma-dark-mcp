"""Opt-in real-game acceptance through MCP stdio; always stop the owned session."""

import argparse
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ddda_mcp.common import atomic_json

ROOT = Path(__file__).resolve().parents[1]


async def call(client, name, arguments=None):
    result = await client.call_tool(name, arguments or {})
    if result.is_error:
        raise RuntimeError(f"{name}: {result.structured_content}")
    return result.structured_content["data"]


async def job(client, name, arguments=None):
    receipt = await call(client, name, arguments)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        receipt = await call(client, "job_status", {"job_id": receipt["job_id"]})
        if receipt["state"] not in {"queued", "running"}:
            if receipt["state"] != "completed":
                raise RuntimeError(json.dumps(receipt))
            return receipt
        await asyncio.sleep(0.25)
    raise TimeoutError("Native acceptance job exceeded one minute")


async def main(config: Path, neutral: bool):
    report = {"evidence_class": "synthetic_native" if neutral else "native_observation", "passed": False}
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ddda_mcp", "--project", str(ROOT), "--config", str(config.resolve())],
    )
    try:
        async with Client(parameters, read_timeout_seconds=45) as client:
            try:
                report["start"] = await job(client, "start_session")
                print("Owned game started", flush=True)
                await asyncio.sleep(5)
                report["snapshot"] = await call(client, "runtime_snapshot")
                if neutral:
                    report["title_start"] = await job(client, "run_scenario", {"recipe": "dismiss_title"})
                    print("Bounded title Start completed; waiting for native offline readiness", flush=True)
                    for _ in range(30):
                        report["snapshot"] = await call(client, "runtime_snapshot")
                        if report["snapshot"]["input_admitted"]:
                            break
                        await asyncio.sleep(1)
                    assert report["snapshot"]["input_admitted"], report["snapshot"]
                report["performance"] = await call(client, "runtime_snapshot", {"group": "performance"})
                async with Client(parameters) as competitor:
                    refused = await call(competitor, "start_session")
                    for _ in range(120):
                        refused = await call(competitor, "job_status", {"job_id": refused["job_id"]})
                        if refused["state"] not in {"running", "queued"}:
                            break
                        await asyncio.sleep(0.1)
                    assert refused["state"] == "failed", refused
                    assert refused["error"]["code"] == "session_busy", refused
                    report["competing_client"] = refused
                recipe = "neutral_input" if neutral else "observe_idle"
                report["captures"] = []
                for _ in range(2):
                    receipt = await job(client, "run_scenario", {"recipe": recipe, "seconds": 3})
                    assert receipt["result"]["summary"]["sample_count"] > 0
                    report["captures"].append(receipt)
                ids = [entry["result"]["artifact_id"] for entry in report["captures"]]
                report["comparison"] = await call(
                    client, "compare_runs", {"before_id": ids[0], "after_id": ids[1]}
                )
                active = await call(client, "run_scenario", {"recipe": recipe, "seconds": 30})
                await asyncio.sleep(1)
                report["cancel"] = await call(client, "cancel_job", {"job_id": active["job_id"]})
                assert report["cancel"]["state"] == "cancelled", report["cancel"]
                assert "partial_evidence" in report["cancel"], report["cancel"]
                report["after_cancel"] = await call(client, "runtime_snapshot")
                report["passed"] = True
            finally:
                report["stop"] = await call(client, "stop_session")
                report["final_status"] = await call(client, "session_status")
                assert not report["final_status"]["running"]
                assert not report["final_status"]["external_game_processes"]
    except BaseException as exc:
        report["passed"] = False
        report["error"] = str(exc)
        report["traceback"] = "".join(traceback.format_exception(exc))
        raise
    finally:
        path = (
            ROOT / "artifacts/validation" / ("native-neutral.json" if neutral else "native-observation.json")
        )
        atomic_json(path, report)
        print(
            json.dumps({"passed": report["passed"], "report": str(path), "error": report.get("error")}),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config/local.json")
    parser.add_argument("--neutral", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.config, args.neutral))
