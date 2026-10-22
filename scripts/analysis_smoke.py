"""Local static integration: real game/source inputs, no launch or deployment."""

import argparse
import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ddda_mcp.common import atomic_json, digest
from ddda_mcp.config import Config
from ddda_mcp.deployment import installed
from ddda_mcp.source import Source

ROOT = Path(__file__).resolve().parents[1]


async def main(decompile):
    config = Config.load(ROOT)
    source = Source(config)
    parent = source.git("rev-parse", "--verify", f"{source.commit}^{{commit}}^", "--").decode().strip()
    # Resolve the actual parent without consulting or changing the working tree.
    parent = parent.splitlines()[0]
    manifest = installed(config)
    folder = ROOT / "private/analysis-smoke" / uuid.uuid4().hex
    candidate = folder / "candidate"
    candidate.mkdir(parents=True)
    for name in manifest["files"]:
        shutil.copyfile(config.game / name, candidate / name)
    settings = candidate / "ddcoop.ini"
    value = settings.read_text(encoding="utf-8-sig")
    assert "developer_input=0" in value
    settings.write_text(value.replace("developer_input=0", "developer_input=1"), encoding="utf-8")
    atomic_json(
        candidate / "candidate.json",
        {
            "game_sha256": manifest["exe_sha256"],
            "files": {name: digest(candidate / name) for name in manifest["files"]},
        },
    )
    values = config.settings.model_dump()
    values["analysis_builds"] = {"static-fixture": str(candidate)}
    path = folder / "config.json"
    atomic_json(path, values)
    report = {"passed": False, "game_launched": False}
    try:
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "ddda_mcp", "--project", str(ROOT), "--config", str(path)]
        )
        async with Client(parameters, read_timeout_seconds=45) as client:

            async def call(name, args):
                result = await client.call_tool(name, args)
                assert not result.is_error, result.structured_content
                return result.structured_content["data"]

            report["source_comparison"] = await call(
                "compare_source_revisions", {"before_commit": parent, "after_commit": source.commit}
            )
            report["build_comparison"] = await call(
                "compare_builds", {"before_name": "installed", "after_name": "static-fixture"}
            )
            assert report["build_comparison"]["summary"]["changed_payloads"] == 1
            job = await call(
                "investigate_symbol",
                {"symbol_name": "pawn_delete", "query": "pawn", "include_decompilation": decompile},
            )
            for _ in range(180):
                job = await call("job_status", {"job_id": job["job_id"]})
                if job["state"] not in {"queued", "running"}:
                    break
                await asyncio.sleep(1)
            assert job["state"] == "completed", job
            report["investigation"] = job["result"]
            assert report["investigation"]["summary"]["complete"], report["investigation"]
            report["passed"] = True
    finally:
        assert installed(config)["files"] == manifest["files"]
        atomic_json(ROOT / "artifacts/validation/analysis-smoke.json", report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--decompile", action="store_true")
    asyncio.run(main(parser.parse_args().decompile))
