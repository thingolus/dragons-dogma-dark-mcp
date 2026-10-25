"""Failure boundaries for the live development expansion (synthetic evidence)."""

import asyncio
import copy
import struct
from types import SimpleNamespace

import pytest
from test_operations import FakeSession

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure, atomic_json, digest
from ddda_mcp.config import GAME_SHA256
from ddda_mcp.copied_groups import GROUPS
from ddda_mcp.deployment import Deployment
from ddda_mcp.diagnostics import decode
from ddda_mcp.harness import Harness, world_ready
from ddda_mcp.memory import InvestigationMemory
from ddda_mcp.regression import Regressions, candidate_settings, choose_trial
from ddda_mcp.saves import Saves
from ddda_mcp.source import Source


def sample(frame=1):
    return {
        "runtime": 2,
        "guard_transport": 2,
        "transport": 2,
        "native_offline": 1,
        "native_errors": 0,
        "faults": 0,
        "menu_gated": 0,
        "stage": 220,
        "generation": 1,
        "p1": -1,
        "p2": -1,
        "actors": [
            {"observed": 1, "frames": frame, "position": [1.0, 2.0, 3.0]},
            {"observed": 1, "frames": frame, "position": [4.0, 5.0, 6.0]},
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"stage": 0},
        {"faults": 1},
        {"menu_gated": 1},
        {"native_offline": 0},
        {"native_errors": 1},
        {"generation": 2},
        {"p1": 1},
        {"actors": []},
    ],
)
def test_readiness_rejects_wrong_or_unhealthy_world(change):
    before = sample(1)
    after = sample(2)
    after.update(change)
    assert not world_ready(after, before, 220)


def test_readiness_requires_fresh_callbacks():
    assert not world_ready(sample(), sample())
    assert world_ready(sample(2), sample(1), 220)
    before = sample()
    before["actors"][1]["observed"] = 0
    assert not world_ready(sample(2), before)


def fixture_checkpoint(development, monkeypatch):
    # These files and observations are synthetic pytest fixtures. Keep the real
    # native-host guards in production, including stdio subprocesses, unchanged.
    monkeypatch.setattr("ddda_mcp.saves.require_closed", lambda: None)
    monkeypatch.setattr("ddda_mcp.harness.require_closed", lambda: None)
    saves_root = development.root / "saves"
    saves_root.mkdir()
    (saves_root / "DDDA.sav").write_bytes(b"known-save")
    development.settings.save_roots = [str(saves_root)]
    artifacts = Artifacts(development)
    saves = Saves(development)
    backup = saves.backup()["backup_id"]
    trace = artifacts.put(
        "runtime_trace",
        {"summary": {"outcome": "completed"}, "samples": [sample(i) for i in range(1, 5)]},
        {"session_id": "a" * 32, "game_sha256": GAME_SHA256, "evidence_class": "synthetic_native"},
    )
    session = FakeSession(development)
    harness = Harness(development, artifacts, session, saves)
    checkpoint = harness.checkpoint(backup, trace["artifact_id"], "inn")["artifact_id"]
    return harness, checkpoint, trace, backup


def test_checkpoint_rejects_changed_save_and_evidence(development, monkeypatch):
    harness, checkpoint, trace, backup = fixture_checkpoint(development, monkeypatch)
    assert harness.load(checkpoint)["stage"] == 220
    root = harness.saves.roots()[0]
    (root / "DDDA.sav").write_bytes(b"unknown save")
    with pytest.raises(ToolFailure, match="differ"):
        harness.checkpoint(backup, trace["artifact_id"], "changed")
    doc = harness.artifacts.get(trace["artifact_id"])
    doc["data"]["samples"][0]["stage"] = 999
    atomic_json(harness.artifacts.path(trace["artifact_id"]), doc)
    with pytest.raises(ToolFailure, match="changed"):
        harness.load(checkpoint)


def test_checkpoint_rejects_supplied_offline_evidence(development, monkeypatch):
    harness, _, trace, backup = fixture_checkpoint(development, monkeypatch)
    doc = harness.artifacts.get(trace["artifact_id"])
    doc["provenance"]["evidence_class"] = "offline_supplied"
    atomic_json(harness.artifacts.path(trace["artifact_id"]), doc)
    with pytest.raises(ToolFailure, match="native trace"):
        harness.checkpoint(backup, trace["artifact_id"], "offline")


def test_harness_timeout_cleans_owned_session_and_retains_failure(development, monkeypatch):
    harness, checkpoint, _, _ = fixture_checkpoint(development, monkeypatch)

    async def run():
        async def snapshot():
            return sample()

        harness.sessions._snapshot = snapshot
        with pytest.raises(ToolFailure, match="deadline") as caught:
            await harness.run(checkpoint, timeout=1)
        assert harness.sessions.receipt is None
        artifact = harness.artifacts.get(caught.value.details["artifact_id"])
        assert artifact["data"]["summary"]["outcome"] == "inconclusive"
        assert artifact["data"]["cleanup"]["stopped"]
        assert not harness.sessions.calls

    asyncio.run(run())


@pytest.mark.parametrize("name", list(GROUPS))
def test_copied_group_header_and_replay(name):
    spec = GROUPS[name]
    assert len(spec["fields"]) * 4 == spec["size"]
    words = [spec["size"], spec["version"]] + [0] * (spec["size"] // 4 - 2)
    original = copy.deepcopy(words)
    result = decode(name, {"words": words, "pointer": "private-address"})
    assert words == original and "pointer" not in result["payload"]
    assert result["decoded"]["values"]["size"] == spec["size"]
    if "availability" in spec:
        assert result["decoded"]["available"] is False
    words[1] = 99
    with pytest.raises(ToolFailure, match="ABI"):
        decode(name, {"words": words})


def test_copied_float_and_exact_u64():
    words = [64, 2] + [0] * 14
    words[7] = struct.unpack("<I", struct.pack("<f", 100.5))[0]
    assert decode("pawn_resources", {"words": words})["decoded"]["values"]["hp"] == 100.5
    words[7] = 0x7FC00000
    with pytest.raises(ToolFailure, match="Nonfinite"):
        decode("pawn_resources", {"words": words})
    words = [224, 1] + [0] * 54
    words[53] = 1
    words[54] = 0x200000
    assert decode("shared_life", {"words": words})["decoded"]["values"]["last_sequence"] == "9007199254740993"


def test_memory_revision_conflict_restart_and_changed_evidence(config):
    artifacts = Artifacts(config)
    source = Source(config)
    memory = InvestigationMemory(config, source, artifacts)
    evidence = artifacts.put("fixture", {"summary": {"passed": False}}, {"evidence_class": "synthetic"})
    note = memory.record(
        "Pawn issue", "A hypothesis", evidence_ids=[evidence["artifact_id"]], source_paths=["src/example.cpp"]
    )
    changed = memory.record(
        "Pawn issue",
        "The hypothesis was refuted",
        status="refuted",
        note_id=note["note_id"],
        expected_revision=1,
    )
    assert changed["revision"] == 2
    with pytest.raises(ToolFailure, match="latest"):
        memory.record("stale", "conflict", note_id=note["note_id"], expected_revision=1)
    restarted = InvestigationMemory(config, source, artifacts)
    assert restarted.search("pawn", status="refuted")["total"] == 1
    assert restarted.read(note["note_id"], 1)["status"] == "open"
    doc = artifacts.get(evidence["artifact_id"])
    doc["data"]["summary"]["passed"] = True
    atomic_json(artifacts.path(evidence["artifact_id"]), doc)
    assert restarted.read(note["note_id"], 1)["evidence_integrity"][0]["unchanged"] is False


def test_memory_findings_need_evidence_and_bounded_query(config):
    memory = InvestigationMemory(config, Source(config), Artifacts(config))
    with pytest.raises(ToolFailure, match="require evidence"):
        memory.record("claim", "unsupported", kind="finding")
    with pytest.raises(ToolFailure):
        memory.search(limit=100000)
    with pytest.raises(ToolFailure):
        memory.record("claim", "body", source_paths=["../secret"])


def test_bisection_repeats_endpoints_then_midpoint():
    revisions = ["a", "b", "c", "d", "e"]
    trials = []
    for revision, outcome in [
        ("a", "passed"),
        ("a", "passed"),
        ("e", "failed"),
        ("e", "failed"),
        ("c", "passed"),
        ("c", "passed"),
        ("d", "failed"),
        ("d", "failed"),
    ]:
        assert choose_trial(revisions, trials, 2)["revision"] == revision
        trials.append({"revision": revision, "outcome": outcome})
    result = choose_trial(revisions, trials, 2)
    assert result["last_passing"] == "c" and result["first_failing"] == "d"


def test_historical_settings_omit_unknowns_and_force_offline():
    target = "[coop]\nonline_mode=0\ndeveloper_input=0\n[recovery]\nshared_lives=1\n"
    current = "[coop]\nonline_mode=1\ndeveloper_input=0\n[recovery]\nshared_lives=0\nendless_lives=1\n"
    selected, omitted = candidate_settings(current, target)
    assert selected.getint("coop", "online_mode") == 0
    assert selected.getint("coop", "developer_input") == 1
    assert selected.getint("recovery", "shared_lives") == 0
    assert omitted == [{"setting": "recovery.endless_lives", "value": "1"}]
    with pytest.raises(ToolFailure):
        candidate_settings(current, "[coop]\nonline_mode=0\n")


@pytest.mark.parametrize("outcomes", [["passed", "failed"], ["inconclusive"], ["cancelled"]])
def test_bisection_never_treats_flakes_as_regression(outcomes):
    result = choose_trial(["a", "b"], [{"revision": "a", "outcome": v} for v in outcomes], 2)
    assert result["state"] == "inconclusive"


def test_campaign_build_deploy_launch_evaluate_and_restore(candidate, monkeypatch):
    config, candidate_root = candidate
    deployment = Deployment(config)
    initial = deployment.prepare("fixture")["receipt_id"]
    deployment.apply(initial)
    before = {
        name: digest(config.game / name)
        for name in ("dinput8.dll", "ddcoop_runtime.dll", "ddcoop.ini", "ddcoop-deployment.json")
    }
    harness, checkpoint, _, _ = fixture_checkpoint(config, monkeypatch)
    artifacts = harness.artifacts
    revision = "a" * 40
    second = "b" * 40
    output = config.artifacts / "synthetic-build"
    output.mkdir(parents=True)
    for name in ("dinput8.dll", "ddcoop_runtime.dll"):
        (output / name).write_bytes(("new-" + name).encode())
    build = artifacts.put(
        "build",
        {
            "summary": {"passed": True},
            "build_directory": str(output),
            "binaries": {p.name: digest(p) for p in output.iterdir()},
        },
        {"source_commit": revision},
    )

    async def build_fn(*args):
        return build

    async def launch(_):
        harness.sessions.receipt = {"session_id": "c" * 32}
        return {"session": harness.sessions.receipt}

    async def run(*args):
        await harness.sessions.stop()
        return {"outcome": "passed", "artifact_id": "d" * 32}

    harness.launch = launch
    harness.run = run
    harness.sessions.receipt = None
    service = Regressions(
        config, Source(config), artifacts, SimpleNamespace(build=build_fn), deployment, harness
    )
    campaign_id = "e" * 32
    service._settings_for_revision = lambda revision: "[coop]\nonline_mode=0\ndeveloper_input=0\n"
    data = {
        "id": campaign_id,
        "checkpoint_id": checkpoint,
        "checkpoint_sha256": digest(artifacts.path(checkpoint)),
        "revisions": [revision, second],
        "repeats": 2,
        "trials": [],
        "builds": {},
        "state": "ready",
        "active": None,
    }
    atomic_json(service.path(campaign_id), data)

    async def check():
        prepared = await service.advance(campaign_id)
        assert prepared["state"] == "awaiting_world"
        assert (config.game / "ddcoop_runtime.dll").read_bytes() == b"new-ddcoop_runtime.dll"
        finished = await service.advance(campaign_id, "evaluate")
        assert finished["state"] == "ready" and finished["trials"][0]["cleanup_verified"]
        assert before == {name: digest(config.game / name) for name in before}
        assert (harness.saves.roots()[0] / "DDDA.sav").read_bytes() == b"known-save"

    asyncio.run(check())


def test_campaign_cancellation_waits_for_transaction_then_aborts(config):
    service = Regressions(config, None, None, None, None, None)

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        events = []

        async def advance(_, action):
            if action == "prepare":
                started.set()
                await release.wait()
                events.append("committed")
                return {"state": "awaiting_world", "active": {"session_id": "owned"}}
            events.append("aborted")
            return {"state": "aborted"}

        service._advance = advance
        task = asyncio.create_task(service.advance("campaign"))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not events
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == ["committed", "aborted"]

    asyncio.run(run())


def test_checkpoint_cancel_waits_for_restore_and_stops(development):
    harness = Harness(development, None, FakeSession(development), None)

    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def launch(_):
            started.set()
            await release.wait()
            return {"save_restore": {"undo_backup": "retained"}}

        harness._launch = launch
        task = asyncio.create_task(harness.launch("checkpoint"))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert harness.sessions.receipt is None
        assert caught.value.details["save_restore"]["undo_backup"] == "retained"

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["start_refusal", "cancelled", "cleanup_failure"])
def test_trace_partial_evidence_and_cleanup(development, monkeypatch, mode):
    from ddda_mcp.tracing import Tracing

    monkeypatch.setattr(
        "ddda_mcp.tracing.reviewed", lambda *_: {"name": "native_stamina_apply", "limitation": "fixture"}
    )
    session = FakeSession(development)
    session.unusable = False
    events = []

    async def snapshot():
        return {**sample(), "input_admitted": True}

    async def request(operation, **kwargs):
        events.append(operation)
        if operation == "trace_start":
            if mode == "start_refusal":
                raise ToolFailure("signature_mismatch", "refused")
            raise asyncio.CancelledError()
        if mode == "cleanup_failure":
            raise ToolFailure("disconnected", "fixture disconnect")
        return {"sealed": True, "rows": [{"previous": "row"}]}

    session._snapshot = snapshot
    session._request = request
    service = Tracing(Source(development), session, None, Artifacts(development))

    async def run():
        expected = asyncio.CancelledError if mode == "cancelled" else ToolFailure
        with pytest.raises(expected) as caught:
            await service.capture("native_stamina_apply", 0.1)
        doc = service.artifacts.get(caught.value.details["artifact_id"])
        assert doc["data"]["summary"]["outcome"] == "failed"
        assert doc["data"]["summary"]["events"] == 0
        assert events == ["trace_start", "trace_stop"]
        if mode == "cleanup_failure":
            assert session.unusable and session.receipt is None

    asyncio.run(run())
