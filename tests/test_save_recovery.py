import asyncio
import json
import subprocess
import sys

import pytest

from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.saves import Saves


@pytest.fixture
def saves(development, monkeypatch):
    monkeypatch.setattr("ddda_mcp.saves.require_closed", lambda: None)
    roots = [development.root / "save-a", development.root / "save-b"]
    for i, root in enumerate(roots):
        root.mkdir()
        (root / "game.sav").write_bytes(f"old-{i}".encode())
    development.settings.save_roots = list(map(str, roots))
    manager = Saves(development)
    backup = manager.backup()["backup_id"]
    for i, root in enumerate(roots):
        (root / "game.sav").write_bytes(f"new-{i}".encode())
    return manager, backup, roots


def crash(saves, after, action=None):
    manager, backup, _ = saves
    config = manager.config.root / "crash-config.json"
    atomic_json(config, manager.config.settings.model_dump())
    script = """
import os, sys
from pathlib import Path
from ddda_mcp.config import Config
from ddda_mcp.saves import Saves
import ddda_mcp.saves as module
module.require_closed = lambda: None
manager = Saves(Config.load(Path(sys.argv[1]), Path(sys.argv[2])))
original = manager._replace
count = 0
def replace(temp, target):
    global count
    if int(sys.argv[4]) == 0: os._exit(73)
    original(temp, target)
    count += 1
    if count == int(sys.argv[4]): os._exit(73)
manager._replace = replace
if len(sys.argv) > 5: manager.recover(sys.argv[3], sys.argv[5])
else: manager.restore(sys.argv[3])
"""
    args = [sys.executable, "-c", script, str(manager.config.root), str(config), backup, str(after)]
    if action:
        args[5] = manager.status()["pending"][0]["receipt_id"]
        args.append(action)
    result = subprocess.run(args, capture_output=True, timeout=20)
    assert result.returncode == 73, result.stderr.decode()


@pytest.mark.parametrize("after", [0, 1, 2])
@pytest.mark.parametrize("action", ["resume", "rollback"])
def test_real_process_death_recovery(saves, after, action):
    manager, _, roots = saves
    crash(saves, after)
    status = manager.status()
    assert status["game_blocked"]
    with pytest.raises(ToolFailure, match="Recover"):
        manager.require_clear()
    with pytest.raises(ToolFailure):
        manager.backup()
    receipt = status["pending"][0]["receipt_id"]
    result = Saves(manager.config).recover(receipt, action)
    expected = "old" if action == "resume" else "new"
    assert [(r / "game.sav").read_bytes() for r in roots] == [f"{expected}-{i}".encode() for i in range(2)]
    assert result["state"] == ("completed" if action == "resume" else "rolled_back")
    assert not manager.status()["game_blocked"]
    assert manager.recover(receipt, action) == result


def test_interrupted_rollback_can_only_continue_rollback(saves):
    manager, _, roots = saves
    crash(saves, 2)
    crash(saves, 1, "rollback")
    receipt = manager.status()["pending"][0]["receipt_id"]
    with pytest.raises(ToolFailure, match="Rollback"):
        manager.recover(receipt, "resume")
    manager.recover(receipt, "rollback")
    assert [(r / "game.sav").read_bytes() for r in roots] == [b"new-0", b"new-1"]


def test_unrelated_save_edit_refuses_entire_recovery(saves):
    manager, _, roots = saves
    crash(saves, 1)
    (roots[1] / "game.sav").write_bytes(b"external-progress")
    before = [(r / "game.sav").read_bytes() for r in roots]
    receipt = manager.status()["pending"][0]["receipt_id"]
    with pytest.raises(ToolFailure, match="differs"):
        manager.recover(receipt, "rollback")
    assert [(r / "game.sav").read_bytes() for r in roots] == before
    assert manager.status()["game_blocked"]


def test_recovery_handles_partial_staging_copy(saves):
    manager, _, roots = saves
    crash(saves, 0)
    receipt = manager.status()["pending"][0]["receipt_id"]
    (roots[0] / f".ddda-mcp-{receipt}-game.sav.tmp").write_bytes(b"partial")
    manager.recover(receipt, "resume")
    assert (roots[0] / "game.sav").read_bytes() == b"old-0"


def test_backup_corruption_prevents_any_write(saves):
    manager, backup, roots = saves
    (manager.folder(backup) / "1/game.sav").write_bytes(b"corrupt")
    with pytest.raises(ToolFailure, match="hash"):
        manager.restore(backup)
    assert [(r / "game.sav").read_bytes() for r in roots] == [b"new-0", b"new-1"]
    assert not manager.status()["game_blocked"]


def test_duplicate_manifest_paths_refused(saves):
    manager, backup, _ = saves
    path = manager.folder(backup) / "manifest.json"
    value = json.loads(path.read_text())
    value["files"].append(value["files"][0])
    atomic_json(path, value)
    with pytest.raises(ToolFailure, match="Duplicate"):
        manager.restore(backup)


def test_other_artifact_root_still_sees_game_blocker(saves):
    from ddda_mcp.config import Config

    manager, _, _ = saves
    crash(saves, 0)
    settings = manager.config.settings.model_copy(update={"artifact_root": "private/other"})
    other = Saves(Config(manager.config.root, settings))
    with pytest.raises(ToolFailure, match="Recover"):
        other.require_clear()


def test_native_worker_refuses_launch_with_pending_restore(saves, monkeypatch):
    from types import SimpleNamespace

    from ddda_mcp import native_worker

    manager, _, _ = saves
    crash(saves, 1)
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace())
    monkeypatch.setattr(native_worker, "require_closed", lambda: None)
    with pytest.raises(ToolFailure, match="Recover"):
        native_worker.run(manager.config, "1" * 32, manager.config.root / "unused-session.json")
    assert not (manager.config.root / "unused-session.json").exists()


def test_terminal_receipt_with_leftover_marker_clears_without_rewriting(saves, monkeypatch):
    manager, backup, roots = saves
    result = manager.restore(backup)
    atomic_json(
        manager.marker, {"receipt_id": result["receipt_id"], "artifact_root": str(manager.config.artifacts)}
    )
    before = [(r / "game.sav").read_bytes() for r in roots]
    monkeypatch.setattr(manager, "_replace", lambda *args: pytest.fail("Must not replace terminal saves"))
    assert manager.recover(result["receipt_id"])["state"] == "completed"
    assert not manager.status()["game_blocked"]
    assert [(r / "game.sav").read_bytes() for r in roots] == before


@pytest.mark.skipif(sys.platform != "win32", reason="Real stdio save operations require a Windows host")
def test_recovery_and_undo_through_actual_stdio(saves):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    manager, _, roots = saves
    crash(saves, 1)

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "ddda_mcp",
                "--project",
                str(manager.config.root),
                "--config",
                str(manager.config.root / "crash-config.json"),
            ],
        )
        async with Client(parameters, read_timeout_seconds=20) as client:
            status = await client.call_tool("save_restore_status", {})
            receipt = status.structured_content["data"]["pending"][0]["receipt_id"]
            recovered = await client.call_tool(
                "recover_save_restore", {"receipt_id": receipt, "action": "resume"}
            )
            assert not recovered.is_error, recovered.structured_content
            assert [(r / "game.sav").read_bytes() for r in roots] == [b"old-0", b"old-1"]
            result = await client.call_tool(
                "restore_saves", {"backup_id": recovered.structured_content["data"]["previous_saves_backup"]}
            )
            assert not result.is_error, result.structured_content
            assert [(r / "game.sav").read_bytes() for r in roots] == [b"new-0", b"new-1"]
            status = await client.call_tool("save_restore_status", {})
            assert not status.structured_content["data"]["game_blocked"]

    asyncio.run(run())
