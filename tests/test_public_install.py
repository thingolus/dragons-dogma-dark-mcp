"""Core public installation must work without the optional private co-op checkout."""

import asyncio
from pathlib import Path

import pytest

from ddda_mcp.common import ToolFailure
from ddda_mcp.config import Config, Settings
from ddda_mcp.server import Application
from ddda_mcp.source import Source


def test_bundled_research_and_sdk_without_checkout(tmp_path):
    app = Application(Config(tmp_path, Settings(profile="development", coop_source_root="missing")))
    status = app.project_status()
    assert status["source_access"] == "bundled_snapshot"
    assert status["upstream_compatibility"]["status"] == "unchanged"
    assert status["upstream"]["verified_files"] == 50
    assert app.source.symbols()
    sdk = app.sdk.generate()
    folder = Path(sdk["directory"])
    assert (folder / "native_sdk.cpp").is_file()
    assert (folder / "example_mod.cpp").is_file()
    assert "Thingolus" in (folder / "LICENSE").read_text()
    with pytest.raises(ToolFailure, match="checkout"):
        app.source.git("status")
    asyncio.run(app.close())


def test_bundled_source_rejects_tampering_and_other_commit(tmp_path):
    config = Config(tmp_path, Settings(coop_source_root="missing"))
    source = Source(config)
    source.snapshot()["files"]["LICENSE"]["text"] += "tampered"
    with pytest.raises(ToolFailure, match="hash mismatch"):
        source.verify()
    source = Source(config)
    source.commit = "a" * 40
    with pytest.raises(ToolFailure, match="reviewed commit"):
        source.verify()


def test_existing_invalid_source_is_not_silently_replaced(tmp_path):
    (tmp_path / "bad-source").mkdir()
    source = Source(Config(tmp_path, Settings(coop_source_root="bad-source")))
    with pytest.raises(ToolFailure):
        source.tree()
