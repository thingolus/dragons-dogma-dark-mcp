"""Synthetic archive, evidence and profile boundaries. No installed game mutation."""

import asyncio
import hashlib
import struct
import zlib
from types import SimpleNamespace

import pytest

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.assets import Assets, arc_table, gmd_edit, gmd_read, relative_name, unpack_entry
from ddda_mcp.behavior import Behaviors, check_pair, projection
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.mods import Mods, require_profile_clear
from ddda_mcp.suites import Suites, outcome


def gmd(strings):
    payload = ("\0".join(strings) + "\0").encode()
    return (
        struct.pack("<10I", 0x444D47, 0x10201, 1, 0, 0, 0, len(strings), 0, len(payload), 7)
        + b"TextWeb\0"
        + payload
    )


def arc(values):
    result = bytearray(8 + len(values) * 80)
    struct.pack_into("<4sHH", result, 0, b"ARC\0", 7, len(values))
    for index, value in enumerate(values):
        compressed = zlib.compress(value)
        struct.pack_into(
            "<64sIIII",
            result,
            8 + index * 80,
            f"item\\entry{index}".encode(),
            0x242BB29A,
            len(compressed),
            len(value) | 0x40000000,
            len(result),
        )
        result.extend(compressed)
    return bytes(result)


@pytest.fixture
def assets(development):
    service = Assets(development, Artifacts(development))
    root = development.game / "nativePC"
    root.mkdir()
    (root / "fixture.arc").write_bytes(arc([gmd(["Apple", "Sword"]), b"opaque bytes"]))
    return service


@pytest.mark.parametrize(
    "path", ["../x", "/x", "C:/x", "a\\b", "a/../b", "a/NUL.ini", "a/COM1.arc", "x./a", "a//b", "a:stream"]
)
def test_asset_paths_reject_escaped_and_device_names(path):
    with pytest.raises(ToolFailure):
        relative_name(path)


@pytest.mark.parametrize("change", ["version", "offset", "overlap", "size", "truncated_zlib"])
def test_arc_rejects_invalid_layouts_and_decompression(change):
    value = bytearray(arc([b"abc", b"def"]))
    if change == "version":
        value[4] = 8
    elif change == "offset":
        struct.pack_into("<I", value, 84, 1)
    elif change == "overlap":
        struct.pack_into("<I", value, 164, struct.unpack_from("<I", value, 84)[0])
    elif change == "size":
        struct.pack_into("<I", value, 80, 0x40000001)
    else:
        first = struct.unpack_from("<I", value, 84)[0]
        value[first] = 0
    with pytest.raises(ToolFailure):
        rows = arc_table(value)
        unpack_entry(value, rows[0])


def test_text_edits_preserve_ids_and_refuse_unknown_layouts():
    raw = gmd(["Apple", "Espée"])
    edited = gmd_edit(raw, [{"index": 0, "expected": "Apple", "text": "Golden Apple"}])
    assert gmd_read(edited)[1] == ["Golden Apple", "Espée"]
    assert edited[:32] == raw[:32]
    with pytest.raises(ToolFailure, match="expected original"):
        gmd_edit(raw, [{"index": 0, "expected": "Pear", "text": "Golden Apple"}])
    labelled = bytearray(raw)
    struct.pack_into("<I", labelled, 20, 1)
    with pytest.raises(ToolFailure):
        gmd_read(labelled)


def test_archive_edit_roundtrip_does_not_touch_installation(assets):
    original = (assets.config.game / "nativePC/fixture.arc").read_bytes()
    archive = assets.open("nativePC/fixture.arc")["artifact_id"]
    entry = assets.extract(archive, 0)["artifact_id"]
    data, _ = assets.read(entry)
    edit = assets.edit_text(entry, [{"index": 0, "expected": "Apple", "text": "Golden Apple"}])
    result = assets.repack(
        archive, [{"index": 0, "artifact_id": edit["artifact_id"], "expected_sha256": data["sha256"]}]
    )
    _, changed = assets.read(result["artifact_id"])
    rows = arc_table(changed)
    assert gmd_read(unpack_entry(changed, rows[0]))[1][0] == "Golden Apple"
    assert unpack_entry(changed, rows[1]) == b"opaque bytes"
    assert (assets.config.game / "nativePC/fixture.arc").read_bytes() == original
    assert assets.read(assets.repack(archive, [])["artifact_id"])[1] == original


def text_mod(assets, mods, archive, index, expected, text):
    entry = assets.extract(archive, 0)["artifact_id"]
    data, _ = assets.read(entry)
    edit = assets.edit_text(entry, [{"index": index, "expected": expected, "text": text}])
    patched = assets.repack(
        archive, [{"index": 0, "artifact_id": edit["artifact_id"], "expected_sha256": data["sha256"]}]
    )
    return mods.register(text, [{"target": "nativePC/fixture.arc", "asset_id": patched["artifact_id"]}])[
        "artifact_id"
    ]


def test_profile_merges_independent_text_and_detects_real_conflicts(assets):
    mods = Mods(assets.config, assets.artifacts, assets)
    archive = assets.open("nativePC/fixture.arc")["artifact_id"]
    a = text_mod(assets, mods, archive, 0, "Apple", "Golden Apple")
    b = text_mod(assets, mods, archive, 1, "Sword", "Silver Sword")
    c = text_mod(assets, mods, archive, 0, "Apple", "Rotten Apple")
    profile = mods.compose("combined", [a, b])
    assert profile["summary"]["compatible"]
    row = assets.artifacts.get(profile["artifact_id"])["data"]["files"][0]
    _, raw = assets.read(row["asset_id"])
    assert gmd_read(unpack_entry(raw, arc_table(raw)[0]))[1] == ["Golden Apple", "Silver Sword"]
    assert not mods.compose("conflict", [a, c])["summary"]["compatible"]
    first = mods.package(profile["artifact_id"])
    assert mods.package(profile["artifact_id"])["sha256"] == first["sha256"]


def make_profile(assets, disable=False):
    mods = Mods(assets.config, assets.artifacts, assets)
    blob = assets.blob(b"[mod]\nenabled=1\n")
    mod = mods.register("test", [{"target": "test.ini", "asset_id": blob["artifact_id"]}])
    profile = mods.compose("test profile", [mod["artifact_id"]], ["dinput8.dll"] if disable else [])
    return mods, profile["artifact_id"]


def test_profile_restores_existing_absent_and_disabled_files(assets, monkeypatch):
    monkeypatch.setattr("ddda_mcp.mods.require_closed", lambda: None)
    mods, profile = make_profile(assets, True)
    loader = assets.config.game / "dinput8.dll"
    loader.write_bytes(b"original loader")
    mods.apply(profile)
    assert not loader.exists()
    require_profile_clear(assets.config, True)
    with pytest.raises(ToolFailure):
        require_profile_clear(assets.config)
    assert mods.restore()["verified"]
    assert loader.read_bytes() == b"original loader"
    assert not (assets.config.game / "test.ini").exists()
    assert mods.status()["state"] == "clear"


@pytest.mark.parametrize("crash_at", [1, 2])
def test_profile_partial_apply_recovers_in_new_service(assets, monkeypatch, crash_at):
    monkeypatch.setattr("ddda_mcp.mods.require_closed", lambda: None)
    mods, profile = make_profile(assets, True)
    (assets.config.game / "test.ini").write_bytes(b"original config")
    (assets.config.game / "dinput8.dll").write_bytes(b"original loader")
    replace = mods._replace
    calls = 0

    def crash(*args):
        nonlocal calls
        replace(*args)
        calls += 1
        if calls == crash_at:
            raise RuntimeError("simulated crash after replacement")

    monkeypatch.setattr(mods, "_replace", crash)
    with pytest.raises(RuntimeError):
        mods.apply(profile)
    with pytest.raises(ToolFailure):
        require_profile_clear(assets.config, True)
    restarted = Mods(assets.config, assets.artifacts, assets)
    restarted.restore()
    assert (assets.config.game / "test.ini").read_bytes() == b"original config"
    assert (assets.config.game / "dinput8.dll").read_bytes() == b"original loader"


def test_profile_preserves_unknown_user_edit_and_resumes_restore(assets, monkeypatch):
    monkeypatch.setattr("ddda_mcp.mods.require_closed", lambda: None)
    mods, profile = make_profile(assets)
    mods.apply(profile)
    path = assets.config.game / "test.ini"
    candidate = path.read_bytes()
    path.write_bytes(b"user changed this")
    with pytest.raises(ToolFailure):
        require_profile_clear(assets.config, True)
    with pytest.raises(ToolFailure):
        mods.restore()
    assert path.read_bytes() == b"user changed this"
    path.write_bytes(candidate)
    assert mods.restore()["verified"]


def test_profile_declared_hooks_and_dependencies_are_not_silently_ignored(assets):
    mods = Mods(assets.config, assets.artifacts, assets)
    blob = assets.blob(b"[x]\na=1")
    a = mods.register("first", [{"target": "a.ini", "asset_id": blob["artifact_id"]}], ["pawn_delete"])[
        "artifact_id"
    ]
    b = mods.register("second", [{"target": "b.ini", "asset_id": blob["artifact_id"]}], ["pawn_delete"], [a])[
        "artifact_id"
    ]
    assert not mods.compose("missing dependency", [b])["summary"]["compatible"]
    assert not mods.compose("hook conflict", [a, b])["summary"]["compatible"]


def world(hp=10, quantity=1):
    return {
        "stage": 220,
        "generation": 1,
        "party": [
            {
                "role": 0,
                "resources": {"hp": hp},
                "inventory": {"available": True, "items": [{"item_id": 7, "quantity": quantity}]},
            }
        ],
        "enemies": {"available": True, "rows": []},
    }


@pytest.mark.parametrize(
    "predicate,expected", [("healed", True), ("revived", None), ("inventory_gain", True), ("damage", None)]
)
def test_suite_outcomes_require_observed_effects(predicate, expected):
    result = outcome(predicate, world(), world(15, 2), {}, item_id=7)
    assert result["passed"] is expected
    assert outcome(predicate, world(), {**world(), "generation": 2}, {}, item_id=7)["passed"] is None


def test_damage_requires_complete_main_resource_events():
    trace = {
        "sealed": True,
        "rows": [
            {"kind": "health", "main_resource": True, "applied_damage": 10},
            {"kind": "health", "main_resource": False, "applied_damage": 40},
        ],
    }
    assert outcome("damage", world(), world(), {"native_trace": trace})["damage"] == 10
    trace["omitted"] = 1
    assert outcome("damage", world(), world(), {"native_trace": trace})["passed"] is None


def test_behavior_normalizes_inventory_and_preserves_unknowns(assets):
    artifacts = assets.artifacts
    provenance = {
        "game_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
        "session_id": "c" * 32,
        "evidence_class": "native_callback_observation",
    }
    before = artifacts.put("world_capture", {"world": world()}, provenance)
    after = artifacts.put("world_capture", {"world": world(15, 3)}, provenance)
    app = SimpleNamespace(
        artifacts=artifacts, features=SimpleNamespace(investigate=lambda *args: {"candidates": []})
    )
    study = Behaviors(app).compare(before["artifact_id"], after["artifact_id"], "healing")
    diff = artifacts.get(study["artifact_id"])["data"]["differences"]
    assert any(d["path"].endswith("/hp") and d["delta"] == 5 for d in diff)
    assert any(d["path"].endswith("/inventory/7") and d["delta"] == 2 for d in diff)
    unknown = world()
    unknown["party"][0]["inventory"] = {"available": False}
    assert projection({"kind": "world_capture", "data": {"world": unknown}})["party"][0]["inventory"] is None


@pytest.mark.parametrize(
    "field", ["game_sha256", "runtime_sha256", "bridge_sha256", "backend", "evidence_class"]
)
def test_behavior_rejects_incompatible_identity(field):
    first = {"kind": "world_capture", "created_at": "1", "provenance": {field: "a"}}
    second = {"kind": "world_capture", "created_at": "2", "provenance": {field: "b"}}
    with pytest.raises(ToolFailure):
        check_pair(first, second)


def test_suite_matrix_keeps_profiles_separate_and_detects_evidence_change(assets):
    checkpoint = assets.artifacts.put("gameplay_checkpoint", {}, {})
    app = SimpleNamespace(
        config=assets.config,
        artifacts=assets.artifacts,
        harness=SimpleNamespace(load=lambda _: {"stage": 220}),
        deployment=SimpleNamespace(candidate=lambda _: None),
    )
    service = Suites(app)
    fixture = service.fixture(checkpoint["artifact_id"], "inn")
    cases = [{"fixture_id": fixture["artifact_id"], "recipe": "movement_pair"}]
    suite = service.create("paired", cases, repeats=2)
    assert len(suite["queue"]) == 2
    doc = assets.artifacts.get(fixture["artifact_id"])
    doc["data"]["label"] = "changed"
    atomic_json(assets.artifacts.path(fixture["artifact_id"]), doc)
    with pytest.raises(ToolFailure, match="changed"):
        asyncio.run(service.advance(suite["id"], "prepare"))


def test_blob_mutation_is_detected(assets):
    receipt = assets.blob(b"data")
    path = assets.root / (hashlib.sha256(b"data").hexdigest() + ".bin")
    path.write_bytes(b"modified")
    with pytest.raises(ToolFailure):
        assets.read(receipt["artifact_id"])


def suite_app(assets, monkeypatch, failure=None, launch_gate=None):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("ddda_mcp.mods.require_closed", lambda: None)
    mods, profile = make_profile(assets)
    events = []
    checkpoint = assets.artifacts.put("gameplay_checkpoint", {}, {})
    sessions = SimpleNamespace(receipt=None)

    async def launch(_):
        events.append("launch")
        if launch_gate:
            launch_gate[0].set()
            await launch_gate[1].wait()
        if failure == "launch":
            raise ToolFailure("launch_failed", "Synthetic launch failure")
        sessions.receipt = {"session_id": "owned"}
        return {"session": sessions.receipt}

    async def stop():
        events.append("stop")
        sessions.receipt = None

    async def scenario(*args, **kwargs):
        events.append("scenario")
        if failure == "scenario":
            raise ToolFailure("scenario_failed", "Synthetic observation failure")
        return {**assets.artifacts.put("gameplay_scenario", {}, {}), "outcome": "passed"}

    def backup():
        events.append("backup")
        return {"backup_id": "original"}

    def restore(_):
        assert sessions.receipt is None
        assert mods.status()["state"] == "clear"
        events.append("restore")

    sessions.stop = stop
    app = SimpleNamespace(
        config=assets.config,
        artifacts=assets.artifacts,
        mods=mods,
        sessions=sessions,
        harness=SimpleNamespace(load=lambda _: {"stage": 220}, launch=launch, wait_ready=AsyncMock()),
        saves=SimpleNamespace(backup=backup, restore=restore),
        regressions=SimpleNamespace(_shared_hash=lambda: "unchanged"),
        controls=SimpleNamespace(
            world=AsyncMock(
                return_value={
                    "world": {**world(), "samples": 2},
                    "cleanup": {"sealed": True},
                    "artifact_id": "world",
                }
            )
        ),
        scenarios=SimpleNamespace(run=scenario),
        diagnosis=SimpleNamespace(analyze=lambda _: {}),
    )
    service = Suites(app)
    fixture = service.fixture(checkpoint["artifact_id"], "synthetic inn")
    suite = service.create(
        "recovery", [{"fixture_id": fixture["artifact_id"], "recipe": "movement_pair"}], [profile], repeats=2
    )
    return app, service, suite, events


@pytest.mark.parametrize("failure", [None, "launch", "scenario"])
def test_suite_restores_profile_and_saves_after_each_fresh_trial(assets, monkeypatch, failure):
    async def run():
        app, service, suite, events = suite_app(assets, monkeypatch, failure)
        if failure == "launch":
            with pytest.raises(ToolFailure, match="launch failure"):
                await service.advance(suite["id"], "prepare")
            assert service.status(suite["id"])["active"]["cleanup_verified"]
        else:
            for _ in range(2):
                assert (await service.advance(suite["id"], "prepare"))["state"] == "awaiting_world"
                result = await service.advance(suite["id"], "evaluate")
                assert result["trials"][-1]["cleanup_verified"]
            assert result["state"] == "completed"
            assert result["summary"]["inconclusive" if failure else "passed"] == 2
            assert events == ["backup", "launch", "scenario", "stop", "restore"] * 2
        assert app.mods.status()["state"] == "clear"
        assert not (assets.config.game / "test.ini").exists()
        assert events[-1] == "restore"

    asyncio.run(run())


@pytest.mark.parametrize("missing", ["samples", "sealed", "errors"])
def test_suite_incomplete_world_never_passes(assets, monkeypatch, missing):
    async def run():
        app, service, suite, events = suite_app(assets, monkeypatch)
        capture = app.controls.world.return_value
        if missing == "samples":
            capture["world"]["samples"] = 0
        elif missing == "sealed":
            capture["cleanup"]["sealed"] = False
        else:
            capture["cleanup"]["errors"] = ["observation_failed"]
        await service.advance(suite["id"], "prepare")
        result = await service.advance(suite["id"], "evaluate")
        assert result["trials"][0]["outcome"] == "inconclusive"
        assert result["trials"][0]["predicate"]["reason"] == "incomplete_world_capture"
        assert result["trials"][0]["cleanup_verified"]
        assert app.mods.status()["state"] == "clear"
        assert events[-1] == "restore"

    asyncio.run(run())


def test_suite_cancelled_prepare_waits_then_restores(assets, monkeypatch):
    async def run():
        gate = (asyncio.Event(), asyncio.Event())
        app, service, suite, events = suite_app(assets, monkeypatch, launch_gate=gate)
        task = asyncio.create_task(service.advance(suite["id"], "prepare"))
        await gate[0].wait()
        task.cancel()
        gate[1].set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.status(suite["id"])["state"] == "aborted"
        assert app.mods.status()["state"] == "clear"
        assert events == ["backup", "launch", "stop", "restore"]

    asyncio.run(run())


def test_suite_cleanup_never_restores_another_owner(assets, monkeypatch):
    async def run():
        app, service, suite, _ = suite_app(assets, monkeypatch)
        prepared = await service.advance(suite["id"], "prepare")
        marker = app.mods.status()
        atomic_json(app.mods.marker, {**marker, "owner_id": "different transaction"})
        with pytest.raises(ToolFailure, match="different active profile"):
            await service.cleanup(prepared)
        assert (assets.config.game / "test.ini").exists()
        atomic_json(app.mods.marker, marker)
        await service.advance(suite["id"], "abort")

    asyncio.run(run())
