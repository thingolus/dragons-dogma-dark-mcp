"""Opt-in real deployment/rollback and disposable-save acceptance, optionally with native UI testing."""

import argparse
import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from native_smoke import call

from ddda_mcp.build import run_process
from ddda_mcp.common import atomic_json, digest
from ddda_mcp.config import GAME_SHA256, Config
from ddda_mcp.deployment import installed
from ddda_mcp.ownership import require_closed

ROOT = Path(__file__).resolve().parents[1]


async def main(native: bool):
    config = Config.load(ROOT)
    require_closed()
    original = installed(config)
    baseline = {name: digest(config.game / name) for name in [*original["files"], "ddcoop-deployment.json"]}
    folder = ROOT / "private/acceptance" / uuid.uuid4().hex
    candidate = folder / "candidate"
    candidate.mkdir(parents=True)
    for name in original["files"]:
        shutil.copyfile(config.game / name, candidate / name)
    settings = (candidate / "ddcoop.ini").read_text(encoding="utf-8-sig")
    assert "developer_input=0" in settings
    (candidate / "ddcoop.ini").write_text(
        settings.replace("developer_input=0", "developer_input=1"), encoding="utf-8"
    )
    atomic_json(
        candidate / "candidate.json",
        {"game_sha256": GAME_SHA256, "files": {name: digest(candidate / name) for name in original["files"]}},
    )
    values = config.settings.model_dump()
    values["deployment_candidates"] = {"acceptance": str(candidate)}
    actual_saves = [(ROOT / root).resolve() for root in values["save_roots"]]
    assert actual_saves, "Configure explicit save_roots to preserve player saves before testing"
    saved_hashes = {str(p): digest(p) for root in actual_saves for p in root.glob("*.sav")}
    config_path = folder / "config.json"
    atomic_json(config_path, values)
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "ddda_mcp", "--project", str(ROOT), "--config", str(config_path)]
    )
    report = {
        "passed": False,
        "baseline": baseline,
        "source_runtime": original["files"]["ddcoop_runtime.dll"],
    }
    receipt = None
    try:
        async with Client(parameters, read_timeout_seconds=60) as client:
            backup = await call(client, "backup_saves")
            report["player_backup"] = backup
            try:
                prepared = await call(client, "prepare_deployment", {"candidate_name": "acceptance"})
                receipt = prepared["receipt_id"]
                report["apply"] = await call(client, "apply_deployment", {"receipt_id": receipt})
                if native:
                    print("Temporary developer deployment applied; starting native acceptance", flush=True)
                    result = await run_process(
                        [
                            sys.executable,
                            str(ROOT / "scripts/native_smoke.py"),
                            "--config",
                            str(config_path),
                            "--neutral",
                        ],
                        ROOT,
                        folder / "native.log",
                        600,
                    )
                    report["native"] = result
                    assert result["exit_code"] == 0, result
            finally:
                if receipt:
                    report["rollback"] = await call(client, "rollback_deployment", {"receipt_id": receipt})
                if any(digest(Path(path)) != sha for path, sha in saved_hashes.items()):
                    report["player_restore"] = await call(
                        client, "restore_saves", {"backup_id": backup["backup_id"]}
                    )
                assert all(digest(Path(path)) == sha for path, sha in saved_hashes.items()), (
                    "Player save restoration differs"
                )
                assert all(digest(config.game / name) == sha for name, sha in baseline.items()), (
                    "Deployment restoration differs"
                )
                report["player_saves_preserved"] = True
            fixture = folder / "save-fixture"
            fixture.mkdir()
            for path in saved_hashes:
                shutil.copyfile(path, fixture / Path(path).name)
            values["save_roots"] = [str(fixture)]
            fixture_config = folder / "fixture-config.json"
            atomic_json(fixture_config, values)
            parameters.args[-1] = str(fixture_config)
            async with Client(parameters) as fixture_client:
                saved = await call(fixture_client, "backup_saves")
                for save in fixture.glob("*.sav"):
                    save.write_bytes(b"Disposable MCP restore fixture")
                restored = await call(fixture_client, "restore_saves", {"backup_id": saved["backup_id"]})
                assert all(digest(fixture / Path(path).name) == sha for path, sha in saved_hashes.items())
                await call(fixture_client, "restore_saves", {"backup_id": restored["previous_saves_backup"]})
                assert all(p.read_bytes() == b"Disposable MCP restore fixture" for p in fixture.glob("*.sav"))
                report["fixture_restore_and_undo"] = True
            report["passed"] = True
    finally:
        atomic_json(ROOT / "artifacts/validation/transactions.json", report)
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.native))
