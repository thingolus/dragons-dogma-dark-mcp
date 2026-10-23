"""Exercise diagnostic/replay/feature workflows over real stdio; never launch DDDA."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "ddda_mcp", "--project", str(ROOT)])
    report = {"evidence_class": "synthetic_and_static", "checks": {}}
    async with Client(params, read_timeout_seconds=60) as client:

        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(f"{name}: {result.structured_content}")
            return result.structured_content["data"]

        report["tool_count"] = len((await client.list_tools()).tools)
        catalog = await call("list_diagnostic_adapters")
        report["checks"]["adapter_catalog"] = len(catalog["adapters"]) == 3
        # Synthetic capacity refusal; the words contain no game or private data.
        words = [2080, 1, 64, 8, 1, 1, 1, 0] + [0] * 512
        words[8:12] = [1, 3, 1, 0]
        words[15] = 500
        diagnostic = await call("decode_diagnostic", adapter="death_refusals", payload={"words": words})
        replay = await call("replay_diagnostic", artifact_id=diagnostic["artifact_id"])
        report["checks"]["diagnostic_replay"] = replay["summary"]["matches_recorded_decode"]
        timeline = await call("build_event_timeline", artifact_ids=[diagnostic["artifact_id"]])
        queried = await call(
            "query_event_timeline", artifact_id=timeline["artifact_id"], kind="death_refusal"
        )
        report["checks"]["timeline_query"] = queried["total_matches"] == 1
        replayed = await call("replay_event_timeline", artifact_id=timeline["artifact_id"])
        report["checks"]["timeline_replay"] = all(
            replayed["summary"][key] for key in ("matches_recorded_events", "matches_recorded_findings")
        )
        report["features"] = []
        for feature, terms in (
            ("shared inventory", ["inventory", "pickup"]),
            ("pawn commands", ["pawn", "command"]),
            ("shared-life revival", ["shared_life", "revival"]),
        ):
            result = await call("investigate_feature", feature=feature, terms=terms)
            if result["summary"]["source_candidates"] == 0:
                raise RuntimeError(f"No source candidates for {feature}")
            report["features"].append(result)
        report["artifacts"] = {"diagnostic": diagnostic["artifact_id"], "timeline": timeline["artifact_id"]}
    if not all(report["checks"].values()):
        raise RuntimeError("Workflow smoke failed")
    report["limitations"] = (
        "Synthetic replay and pinned source only; no live capture, input, gameplay acceptance or measured development speedup."
    )
    output = ROOT / "artifacts/validation/future-workflows-smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
