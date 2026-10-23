"""Explicit local live acceptance; client loads the observed native menus. MIT, Thingolus."""

import argparse
import asyncio
import json
from pathlib import Path

from ddda_mcp.common import atomic_json
from ddda_mcp.config import Config
from ddda_mcp.copied_groups import GROUPS
from ddda_mcp.server import Application


async def run(checkpoint, candidate):
    root = Path(__file__).resolve().parents[1]
    app = Application(Config.load(root))
    report = {"diagnostics": {}, "traces": {}}
    deployment = None
    backup = None
    try:
        backup = app.saves.backup()["backup_id"]
        report["save_backup"] = backup
        deployment = app.deployment.prepare(candidate)["receipt_id"]
        app.deployment.apply(deployment)
        report["launch"] = await app.harness.launch(checkpoint)
        print(
            json.dumps({"state": "awaiting_observed_load_game", "session": app.sessions.receipt}), flush=True
        )
        report["ready"] = await app.harness.wait_ready(app.harness.load(checkpoint), 120)
        for group in GROUPS:
            try:
                result = await app.sessions.snapshot(group)
                report["diagnostics"][group] = result
            except Exception as exc:
                report["diagnostics"][group] = {"error": str(exc)}
        for symbol in ("native_stamina_apply", "goblin_health_subtract"):
            try:
                report["traces"][symbol] = await app.tracing.capture(symbol, 2)
            except Exception as exc:
                report["traces"][symbol] = {"error": str(exc), "details": getattr(exc, "details", None)}
        report["harness"] = await app.harness.run(checkpoint, "neutral_input", 2, 10)
    finally:
        await app.close()
        if deployment:
            report["rollback"] = app.deployment.rollback(deployment)
        if backup:
            report["save_restore"] = app.saves.restore(backup)
        atomic_json(root / "private/expanded-native-smoke.json", report)
    print(
        json.dumps(
            {
                "harness": report.get("harness"),
                "diagnostics": {k: v.get("error", "captured") for k, v in report["diagnostics"].items()},
                "traces": report["traces"],
                "rollback": report.get("rollback"),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.checkpoint, args.candidate))
