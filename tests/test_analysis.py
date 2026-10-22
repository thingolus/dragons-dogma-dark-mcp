import asyncio
import hashlib
import json
import shutil
import struct

import pytest
from conftest import git, make_pe

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.comparison import Comparisons, pe_summary, settings_summary
from ddda_mcp.investigation import candidate_calls
from ddda_mcp.server import create_server


def test_candidate_calls_are_bounded_and_not_claimed_as_call_graph(pe):
    path = pe.game / "DDDA.exe"
    raw = bytearray(path.read_bytes())
    for offset in (32, 48):
        raw[512 + offset] = 0xE8
        struct.pack_into("<i", raw, 513 + offset, 0x1000 - (0x1000 + offset + 5))
    result = candidate_calls(bytes(raw), 0x1000, limit=1)
    assert result["truncated"] and len(result["results"]) == 1
    assert "unverified" in result["results"][0]["evidence"]
    assert result["results"][0]["callsite_rva"] == "0x1020"


def test_call_scan_does_not_scan_non_executable_sections(pe):
    raw = bytearray((pe.game / "DDDA.exe").read_bytes())
    struct.pack_into("<I", raw, 0x84 + 20 + 224 + 36, 0x40000040)
    assert not candidate_calls(bytes(raw), 0x1000)["results"]


def test_investigation_partial_when_no_game(config):
    async def run():
        _, app = create_server(config)
        result = await app.investigations.bundle("pawn_movement_consume", "ownership")
        assert not result["summary"]["complete"]
        data = app.artifacts.get(result["artifact_id"])["data"]
        assert data["research"]["results"] and data["source_excerpts"]
        assert data["unavailable"][0]["code"] == "game_missing"
        assert data["summary"]["native_acceptance"] == "unverified"

    asyncio.run(run())


def test_investigation_does_not_apply_pinned_rvas_to_unknown_pe(pe):
    async def run():
        _, app = create_server(pe)
        result = await app.investigations.bundle("pawn_movement_consume")
        data = app.artifacts.get(result["artifact_id"])["data"]
        assert data["unavailable"][0]["code"] == "unsupported_build"
        assert "disassembly" not in data

    asyncio.run(run())


def test_investigation_decompile_profile_and_missing_symbol(config):
    async def run():
        _, app = create_server(config)
        with pytest.raises(ToolFailure, match="development"):
            await app.investigations.bundle("pawn_movement_consume", include_decompilation=True)
        with pytest.raises(ToolFailure, match="exact"):
            await app.investigations.bundle("not_a_symbol")

    asyncio.run(run())


def test_investigation_through_mcp_job(config):
    from mcp import Client

    async def run():
        server, app = create_server(config)
        async with Client(server) as client:
            result = await client.call_tool("investigate_symbol", {"symbol_name": "pawn_movement_consume"})
            job_id = result.structured_content["data"]["job_id"]
            await app.jobs.tasks[job_id]
            result = await client.call_tool("job_status", {"job_id": job_id})
            assert result.structured_content["data"]["state"] == "completed"

    asyncio.run(run())


def test_revision_diff_ignores_dirty_worktree(config):
    # Work in a private clone; never alter the shared upstream fixture.
    import subprocess

    clone = config.root / "comparison-source"
    subprocess.run(["git", "clone", "--quiet", str(config.source), str(clone)], check=True)
    config.source = clone
    git(clone, "config", "user.name", "Fixture")
    git(clone, "config", "user.email", "fixture@example.invalid")
    before = git(clone, "rev-parse", "HEAD")
    (clone / "src/example.cpp").write_text("int answer() { return 43; }\n")
    path = clone / "include/coop/supported_build.hpp"
    path.write_text(path.read_text().replace("0x1000", "0x1100"))
    git(clone, "add", ".")
    git(clone, "commit", "-m", "Change source fixture")
    after = git(clone, "rev-parse", "HEAD")
    (clone / "src/example.cpp").write_text("DIRTY VALUE MUST NOT ENTER REPORT")
    _, app = create_server(config)
    result = app.comparisons.compare_source(before, after)
    artifact = app.artifacts.get(result["artifact_id"])
    assert artifact["data"]["summary"]["changed_files"] == 2
    assert artifact["data"]["signature_changes"]["total"] == 1
    assert "43" in json.dumps(artifact) and "DIRTY VALUE" not in json.dumps(artifact)
    assert "answer" in json.dumps(artifact["data"]["files"])
    assert artifact["data"]["summary"]["risks"]
    first = app.comparisons.compare_source(before, after, limit=1)
    second = app.comparisons.compare_source(before, after, offset=1, limit=1)
    assert first["summary"]["next_offset"] == 1
    assert second["summary"]["next_offset"] is None
    assert second["summary"]["reported_files"] == 1
    assert (
        app.artifacts.get(first["artifact_id"])["data"]["files"][0]["path"]
        != app.artifacts.get(second["artifact_id"])["data"]["files"][0]["path"]
    )


@pytest.mark.parametrize("revision", ["HEAD", "--help", "a" * 39, "../outside"])
def test_revision_comparison_rejects_mutable_or_option_inputs(config, revision):
    _, app = create_server(config)
    with pytest.raises(ToolFailure, match="immutable"):
        app.comparisons.compare_source(revision, config.settings.coop_source_commit)


@pytest.fixture
def named_builds(config):
    for name in ("before", "after"):
        root = config.root / name
        root.mkdir()
        make_pe(root / "ddcoop_runtime.dll")
        shutil.copyfile(root / "ddcoop_runtime.dll", root / "dinput8.dll")
        (root / "ddcoop.ini").write_text("[coop]\nonline_mode=0\ndeveloper_input=0\n")
        config.settings.analysis_builds[name] = str(root)
    return config


def seal_build(config, name):
    root = config.root / name
    atomic_json(
        root / "candidate.json",
        {
            "game_sha256": "a" * 64,
            "files": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.iterdir()
                if p.suffix in {".dll", ".ini"}
            },
        },
    )


def test_build_comparison_reports_sections_and_settings_without_deployment(named_builds):
    config = named_builds
    path = config.root / "after/ddcoop_runtime.dll"
    raw = bytearray(path.read_bytes())
    raw[512] = 0x90
    path.write_bytes(raw)
    (config.root / "after/ddcoop.ini").write_text("[coop]\nonline_mode=1\ndeveloper_input=1\n")
    for name in ("before", "after"):
        seal_build(config, name)
    _, app = create_server(config)
    result = app.comparisons.compare_builds("before", "after")
    assert result["summary"]["changed_payloads"] == 2
    assert any("online_mode" in risk for risk in result["summary"]["risks"])
    assert "Developer input setting changed." in result["summary"]["risks"]
    assert not result["summary"]["deployment_approved"]
    rows = app.artifacts.get(result["artifact_id"])["data"]["files"]
    assert next(r for r in rows if r["name"] == "ddcoop_runtime.dll")["sections"]["total"] == 1
    assert not (config.game / "ddcoop_runtime.dll").exists()


def test_build_tampering_refused(named_builds):
    seal_build(named_builds, "before")
    (named_builds.root / "before/ddcoop.ini").write_text("changed")
    with pytest.raises(ToolFailure, match="changed"):
        Comparisons(named_builds, None, Artifacts(named_builds)).snapshot_build("before")


def test_build_comparison_detects_removed_export(named_builds):
    path = named_builds.root / "before/ddcoop_runtime.dll"
    raw = bytearray(path.read_bytes())
    # One synthetic named export in the fixture's existing mapped section.
    struct.pack_into("<II", raw, 0x98 + 96, 0x1080, 40)
    struct.pack_into("<IIHHIIIIIII", raw, 640, 0, 0, 0, 0, 0x10C0, 1, 1, 1, 0x10B0, 0x10B4, 0x10B8)
    struct.pack_into("<IIH", raw, 688, 0x1000, 0x10D0, 0)
    raw[704:716] = b"fixture.dll\x00"
    raw[720:734] = b"CoopGetStatus\x00"
    path.write_bytes(raw)
    assert "CoopGetStatus" in pe_summary(bytes(raw))["exports"]
    for name in ("before", "after"):
        seal_build(named_builds, name)
    _, app = create_server(named_builds)
    result = app.comparisons.compare_builds("before", "after")
    assert any("1 exports removed" in risk for risk in result["summary"]["risks"])
    rows = app.artifacts.get(result["artifact_id"])["data"]["files"]
    assert next(r for r in rows if r["name"] == "ddcoop_runtime.dll")["exports"]["items"][0] == {
        "name": "CoopGetStatus",
        "before": {"rva": "0x1000", "ordinal": 1, "forwarder": None},
        "after": None,
    }


def test_named_build_path_inventory_refused(named_builds):
    root = named_builds.root / "before"
    atomic_json(root / "candidate.json", {"game_sha256": "a" * 64, "files": {"../../secret": "a" * 64}})
    with pytest.raises(ToolFailure, match="Expected"):
        Comparisons(named_builds, None, Artifacts(named_builds)).snapshot_build("before")


def test_parsers_refuse_malformed_input():
    with pytest.raises(ToolFailure, match="malformed"):
        pe_summary(b"not a PE")
    with pytest.raises(ToolFailure, match="parse"):
        settings_summary(b"no section")
