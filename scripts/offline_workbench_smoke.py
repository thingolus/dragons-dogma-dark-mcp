"""Real stdio replay and private ITL2 round trip. Never launches or controls DDDA.

Requires the configured local game assets and development profile. All writes go
to private artifacts; no profile application, deployment or save operation occurs.
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ddda_mcp.common import atomic_json, digest
from ddda_mcp.config import Config

ROOT = Path(__file__).resolve().parents[1]


async def main():
    config = Config.load(ROOT)
    archive_path = config.game / "nativePC/rom/bbs_rpg.arc"
    original = digest(archive_path)
    report = {"game_launches": 0, "evidence_class": "offline_validation", "model_tokens": None}
    transport = StdioServerParameters(command=sys.executable, args=["-m", "ddda_mcp", "--project", str(ROOT)])
    async with Client(transport, read_timeout_seconds=30) as client:

        async def call(name, arguments):
            result = await client.call_tool(name, arguments)
            if result.is_error:
                raise RuntimeError(f"{name}: {result.structured_content}")
            return result.structured_content["data"]

        report["tools"] = len((await client.list_tools()).tools)
        sdk = await call("ddda_sdk_catalog", {})
        assert sdk["observation_extension"]["native_stream_available"] is False
        report["sdk_extension"] = sdk["observation_extension"]["version"]
        plan = await call(
            "create_experiment_plan",
            {
                "plan": {
                    "label": "Synthetic healing observation",
                    "goal": {"kind": "healing", "subject": {"role": 0}},
                    "steps": [{"kind": "wait", "timeout_ms": 1000}],
                }
            },
        )
        frames = [
            {
                "sequence": n,
                "elapsed_ms": n * 500,
                "stage": 220,
                "generation": 1,
                "complete": True,
                "actors": [
                    {
                        "kind": "party",
                        "role": 0,
                        "hp": hp,
                        "entity": {
                            "key": "party-one",
                            "epoch": "synthetic-one",
                            "scope": "session",
                            "incarnation": 1,
                        },
                    }
                ],
            }
            for n, hp in enumerate((100.0, 150.0))
        ]
        recording = await call(
            "record_gameplay_observations",
            {
                "recording": {
                    "label": "Synthetic data only",
                    "identity": {
                        "session": "synthetic-one",
                        "clock": "fixture",
                        "game_sha256": "a" * 64,
                        "source_commit": "b" * 40,
                        "backend": "synthetic",
                    },
                    "frames": frames,
                    "cleanup": {
                        "input_released": True,
                        "observers_sealed": True,
                        "restoration": "not_applicable",
                    },
                }
            },
        )
        replay = await call(
            "replay_gameplay_experiment",
            {"plan_id": plan["artifact_id"], "recording_id": recording["artifact_id"]},
        )
        assert replay["summary"]["outcome"] == "passed"
        assert replay["summary"]["native_acceptance"] == "unverified"
        events = await call(
            "query_gameplay_events", {"recording_id": recording["artifact_id"], "kind": "hp_increased"}
        )
        assert events["total"] == 1 and events["matches_recorded_decode"]
        report["replay"] = replay

        archive = await call("open_asset_archive", {"relative_path": "nativePC/rom/bbs_rpg.arc"})
        entries = await call(
            "inspect_asset",
            {"artifact_id": archive["artifact_id"], "operation": "entries", "query": "itemList"},
        )
        assert entries["total"] == 1
        index = entries["entries"][0]["index"]
        item = await call(
            "inspect_asset", {"artifact_id": archive["artifact_id"], "operation": "extract", "index": index}
        )
        inspected = await call("inspect_item_parameters", {"entry_id": item["artifact_id"], "item_id": 43})
        before = inspected["items"][0]["fields"]["mAddHp"]
        patch = await call(
            "edit_item_parameters",
            {
                "entry_id": item["artifact_id"],
                "edits": [{"item_id": 43, "field": "mAddHp", "expected": before, "value": before + 1}],
            },
        )
        differences = await call(
            "diff_item_parameters", {"before_id": item["artifact_id"], "after_id": patch["artifact_id"]}
        )
        assert differences["total"] == 1 and differences["unmodeled_changed_bytes"] == 0
        restored = await call(
            "edit_item_parameters",
            {
                "entry_id": patch["artifact_id"],
                "edits": [{"item_id": 43, "field": "mAddHp", "expected": before + 1, "value": before}],
            },
        )
        back = await call("inspect_item_parameters", {"entry_id": restored["artifact_id"], "item_id": 43})
        assert back["sha256"] == inspected["sha256"]
        packed = await call(
            "repack_asset_archive",
            {
                "archive_id": archive["artifact_id"],
                "replacements": [
                    {
                        "index": index,
                        "artifact_id": patch["artifact_id"],
                        "expected_sha256": inspected["sha256"],
                    }
                ],
            },
        )
        extracted = await call(
            "inspect_asset", {"artifact_id": packed["artifact_id"], "operation": "extract", "index": index}
        )
        after = await call("inspect_item_parameters", {"entry_id": extracted["artifact_id"], "item_id": 43})
        assert after["items"][0]["fields"]["mAddHp"] == before + 1
        mod = await call(
            "register_mod",
            {
                "label": "Private item parameter smoke",
                "files": [{"target": "nativePC/rom/bbs_rpg.arc", "asset_id": packed["artifact_id"]}],
            },
        )
        profile = await call(
            "compose_mod_profile", {"label": "Private item parameter smoke", "mod_ids": [mod["artifact_id"]]}
        )
        assert profile["summary"]["compatible"]
        report["item_roundtrip"] = {
            "items": inspected["total"],
            "source_sha256": inspected["sha256"],
            "edit": patch,
            "diff": differences,
            "restored_bytes_equal": True,
            "repacked": packed["artifact_id"],
            "profile": profile["artifact_id"],
            "profile_applied": False,
            "native_acceptance": "unverified",
        }
    report["installed_archive_unchanged"] = digest(archive_path) == original
    assert report["installed_archive_unchanged"]
    atomic_json(ROOT / "artifacts/validation/offline-workbench-smoke.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
