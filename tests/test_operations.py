import asyncio
import sys

import pytest

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.build import run_process
from ddda_mcp.common import ToolFailure
from ddda_mcp.deployment import Deployment, installed
from ddda_mcp.jobs import Jobs
from ddda_mcp.ownership import game_lease
from ddda_mcp.saves import Saves
from ddda_mcp.session import Sessions


def test_game_lease_refuses_second_owner(config):
    with game_lease(config.game), pytest.raises(ToolFailure, match="owns"):
        with game_lease(config.game):
            pass


def test_deploy_round_trip_and_idempotent_apply(candidate):
    config, _ = candidate
    deployment = Deployment(config)
    receipt = deployment.prepare("fixture")["receipt_id"]
    assert not (config.game / "ddcoop_runtime.dll").exists()
    assert deployment.apply(receipt)["state"] == "applied"
    installed(config)
    assert deployment.apply(receipt)["already_applied"]
    assert deployment.rollback(receipt)["state"] == "rolled_back"
    assert not (config.game / "ddcoop_runtime.dll").exists()
    assert deployment.rollback(receipt)["already_rolled_back"]


def test_changed_candidate_refused(candidate):
    config, root = candidate
    deployment = Deployment(config)
    receipt = deployment.prepare("fixture")["receipt_id"]
    (root / "ddcoop_runtime.dll").write_bytes(b"changed")
    with pytest.raises(ToolFailure, match="hash mismatch"):
        deployment.apply(receipt)
    assert not (config.game / "ddcoop_runtime.dll").exists()


def test_foreign_loader_preserved(candidate):
    config, _ = candidate
    (config.game / "dinput8.dll").write_bytes(b"foreign mod")
    with pytest.raises(ToolFailure, match="overwrite"):
        Deployment(config).prepare("fixture")
    assert (config.game / "dinput8.dll").read_bytes() == b"foreign mod"


def test_modified_owned_file_blocks_rollback(candidate):
    config, _ = candidate
    deployment = Deployment(config)
    receipt = deployment.prepare("fixture")["receipt_id"]
    deployment.apply(receipt)
    (config.game / "ddcoop.ini").write_bytes(b"user edits")
    with pytest.raises(ToolFailure, match="changed file"):
        deployment.rollback(receipt)
    assert (config.game / "ddcoop.ini").read_bytes() == b"user edits"


def test_interrupted_apply_recovers_from_journal(candidate, monkeypatch):
    config, _ = candidate
    deployment = Deployment(config)
    receipt = deployment.prepare("fixture")["receipt_id"]
    original = deployment._write_file
    calls = []

    def interrupted(*args):
        original(*args)
        calls.append(args[0])
        if len(calls) == 2:
            raise OSError("simulated crash after replacement before journal")

    monkeypatch.setattr(deployment, "_write_file", interrupted)
    with pytest.raises(OSError):
        deployment.apply(receipt)
    monkeypatch.setattr(deployment, "_write_file", original)
    assert deployment.rollback(receipt)["state"] == "rolled_back"
    assert not (config.game / "ddcoop_runtime.dll").exists()


def test_read_only_profile_rejects_deployment(config):
    with pytest.raises(ToolFailure, match="development"):
        Deployment(config).prepare("anything")


def test_backup_restore_with_undo(development, monkeypatch):
    import ddda_mcp.saves as saves_module

    monkeypatch.setattr(saves_module, "require_closed", lambda: None)
    root = development.root / "saves"
    root.mkdir()
    (root / "game.sav").write_bytes(b"original")
    development.settings.save_roots = [str(root)]
    saves = Saves(development)
    backup = saves.backup()["backup_id"]
    (root / "game.sav").write_bytes(b"trial")
    undo = saves.restore(backup)["previous_saves_backup"]
    assert (root / "game.sav").read_bytes() == b"original"
    saves.restore(undo)
    assert (root / "game.sav").read_bytes() == b"trial"


def test_artifacts_no_path_escape_and_evidence_compatibility(config):
    artifacts = Artifacts(config)
    before = artifacts.put(
        "runtime_trace", {"summary": {"samples": 2}}, {"game_sha256": "a", "recipe": "idle"}
    )
    after = artifacts.put(
        "runtime_trace", {"summary": {"samples": 3}}, {"game_sha256": "a", "recipe": "idle"}
    )
    assert artifacts.compare(before["artifact_id"], after["artifact_id"])["metrics"]["samples"]["delta"] == 1
    other = artifacts.put("runtime_trace", {"summary": {}}, {"game_sha256": "b"})
    with pytest.raises(ToolFailure):
        artifacts.compare(before["artifact_id"], other["artifact_id"])
    with pytest.raises(ToolFailure):
        artifacts.get("../../secret")


def test_job_success_failure_and_unknown_previous_owner(config):
    async def run():
        jobs = Jobs(config)

        async def succeeds():
            return {"value": 1}

        job = jobs.submit("fixture", succeeds)["job_id"]
        await jobs.tasks[job]
        assert jobs.status(job)["state"] == "completed"

        async def fails():
            raise ToolFailure("fixture_failure", "Expected failure")

        failed = jobs.submit("fixture", fails)["job_id"]
        await jobs.tasks[failed]
        assert jobs.status(failed)["error"]["code"] == "fixture_failure"
        pending = jobs.submit("fixture", lambda: asyncio.sleep(10))["job_id"]
        assert Jobs(config).status(pending)["state"] == "outcome_unknown"
        await jobs.cancel(pending)
        assert jobs.status(pending)["state"] == "cancelled"
        await jobs.close()

    asyncio.run(run())


def test_job_cancel_runs_cleanup(config):
    async def run():
        jobs = Jobs(config)
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def work():
            try:
                entered.set()
                await asyncio.sleep(20)
            finally:
                cleaned.set()

        job = jobs.submit("fixture", work)["job_id"]
        await entered.wait()
        result = await jobs.cancel(job)
        assert result["state"] == "cancelled" and cleaned.is_set()

    asyncio.run(run())


def test_subprocess_timeout_kills_owned_process(tmp_path):
    async def run():
        with pytest.raises(TimeoutError):
            await run_process(
                [sys.executable, "-c", "import time; print('ready',flush=True); time.sleep(20)"],
                tmp_path,
                tmp_path / "process.log",
                timeout=1,
            )
        assert b"ready" in (tmp_path / "process.log").read_bytes()

    asyncio.run(run())


class FakeSession(Sessions):
    def __init__(self, config):
        super().__init__(config, Artifacts(config))
        self.calls = []
        self.receipt = {"session_id": "1" * 32, "game_sha256": "fake", "runtime_sha256": "fake-runtime"}

    async def _request(self, operation, **parameters):
        self.calls.append((operation, parameters))
        if operation == "snapshot":
            return {
                "size": 132,
                "version": 2,
                "runtime": 2,
                "transport": 2,
                "guard_transport": 2,
                "native_offline": 1,
                "native_errors": 0,
                "faults": 0,
                "generation": 1,
                "stage": 220,
                "developer_input": 1,
                "actors": [],
            }
        return True


def test_read_only_snapshot_never_supplies_input(development):
    async def run():
        session = FakeSession(development)
        assert (await session.snapshot())["version"] == 2
        assert [op for op, _ in session.calls] == ["snapshot"]

    asyncio.run(run())


def test_cancelled_neutral_recipe_releases_input(development):
    async def run():
        session = FakeSession(development)
        task = asyncio.create_task(session.capture(10, 100, neutral=True))
        while not any(op == "neutral" for op, _ in session.calls):
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.calls[-1] == ("neutral", {"connected": False})

    asyncio.run(run())


def test_capture_is_bounded_and_has_provenance(development):
    async def run():
        session = FakeSession(development)
        result = await session.capture(0.15, 100)
        assert 1 <= result["summary"]["sample_count"] <= 2
        artifact = session.artifacts.get(result["artifact_id"])
        assert artifact["provenance"]["runtime_sha256"] == "fake-runtime"
        assert not any(op == "neutral" for op, _ in session.calls)
        with pytest.raises(ToolFailure):
            await session.capture(121)

    asyncio.run(run())


def test_native_abi_mismatch_disables_session(development):
    async def run():
        session = FakeSession(development)

        async def wrong(*args, **kwargs):
            return {"size": 100, "version": 1}

        session._request = wrong
        with pytest.raises(ToolFailure, match="CoopStatus"):
            await session.snapshot()
        assert session.unusable

    asyncio.run(run())


def test_invalid_candidate_binary_rejected(development):
    from ddda_mcp.deployment import verify_payload

    (development.root / "ddcoop_runtime.dll").write_bytes(b"not a DLL")
    with pytest.raises(ToolFailure, match="Malformed DLL"):
        verify_payload(development.root, {"ddcoop_runtime.dll": "irrelevant"})


def test_online_settings_refused(development):
    from ddda_mcp.deployment import verify_offline_settings

    (development.root / "ddcoop.ini").write_text("[coop]\nonline_mode=1\n")
    with pytest.raises(ToolFailure, match="online_mode=0"):
        verify_offline_settings(development.root)


def test_update_rollback_preserves_original_install(candidate):
    import hashlib
    import json

    config, root = candidate
    deployment = Deployment(config)
    first = deployment.prepare("fixture")["receipt_id"]
    deployment.apply(first)
    original = {p.name: p.read_bytes() for p in config.game.iterdir() if p.name != ".ddda-dark-mcp.lock"}
    path = root / "ddcoop_runtime.dll"
    path.write_bytes(b"second candidate")
    manifest = json.loads((root / "candidate.json").read_text())
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "candidate.json").write_text(json.dumps(manifest))
    second = deployment.prepare("fixture")["receipt_id"]
    deployment.apply(second)
    deployment.rollback(second)
    assert all((config.game / name).read_bytes() == value for name, value in original.items())


def test_cancelled_trace_keeps_partial_evidence_in_job(development):
    async def run():
        session = FakeSession(development)
        jobs = Jobs(development)
        job = jobs.submit("trace", lambda: session.capture(10, 100, neutral=True))["job_id"]
        while len(session.calls) < 3:
            await asyncio.sleep(0.001)
        result = await jobs.cancel(job)
        evidence = session.artifacts.get(result["partial_evidence"]["artifact_id"])
        assert evidence["data"]["summary"]["outcome"] == "cancelled"
        assert evidence["data"]["samples"]

    asyncio.run(run())


def test_offline_guard_failure_disables_live_adapter(development):
    async def run():
        session = FakeSession(development)
        original = session._request

        async def offline_failure(operation, **params):
            result = await original(operation, **params)
            result["guard_transport"] = 0
            return result

        session._request = offline_failure
        with pytest.raises(ToolFailure, match="guard"):
            await session.snapshot()
        assert session.unusable

    asyncio.run(run())


def test_stale_broker_response_is_not_replayed(development):
    from types import SimpleNamespace

    async def run():
        writes = []

        class Writer:
            def write(self, message):
                writes.append(message)

            async def drain(self):
                pass

        class Reader:
            async def readline(self):
                return b'{"id":"old-request","ok":true,"value":{}}\n'

        session = Sessions(development, Artifacts(development))
        session.process = SimpleNamespace(returncode=None, stdin=Writer(), stdout=Reader())
        with pytest.raises(ToolFailure, match="match"):
            await session._request("snapshot")
        assert session.unusable and len(writes) == 1

    asyncio.run(run())


def test_pending_native_state_allows_observation_but_refuses_neutral(development):
    async def run():
        session = FakeSession(development)
        original = session._request

        async def pending(op, **params):
            result = await original(op, **params)
            if op == "snapshot":
                result.update(native_offline=0, transport=0, stage=0, generation=0)
            return result

        session._request = pending
        status = await session.snapshot()
        assert status["native_state"] == "pending_game_initialization"
        assert not status["input_admitted"] and not session.unusable
        with pytest.raises(ToolFailure, match="readiness"):
            await session.capture(1, 100, True)
        assert all(op == "snapshot" for op, _ in session.calls)

    asyncio.run(run())


def test_title_start_is_one_shot_and_releases_on_cancellation(development):
    async def run():
        session = FakeSession(development)
        original = session._request

        async def title(op, **params):
            result = await original(op, **params)
            if op == "snapshot":
                result.update(stage=0, generation=0, native_offline=0)
            return result

        session._request = title
        task = asyncio.create_task(session.dismiss_title())
        while not any(op == "title_start" for op, _ in session.calls):
            await asyncio.sleep(0.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.calls[-1] == ("title_start", {"pressed": False})
        with pytest.raises(ToolFailure, match="once"):
            await session.dismiss_title()

    asyncio.run(run())


def test_title_start_refuses_loaded_world(development):
    async def run():
        session = FakeSession(development)
        with pytest.raises(ToolFailure, match="loaded world"):
            await session.dismiss_title()
        assert all(op == "snapshot" for op, _ in session.calls)

    asyncio.run(run())


def test_full_suite_holds_game_lease_and_core_does_not(development, monkeypatch):
    import ddda_mcp.build as module
    from ddda_mcp.ownership import game_lease
    from ddda_mcp.source import Source

    monkeypatch.setattr(module, "require_closed", lambda: None)

    async def run():
        builds = module.Builds(development, Source(development), Artifacts(development))

        async def inner(configuration, group, revision=None):
            if group == "all":
                with pytest.raises(ToolFailure, match="owns"):
                    with game_lease(development.game):
                        pass
            else:
                with game_lease(development.game):
                    pass
            return {"group": group}

        builds._build_locked = inner
        assert (await builds.build(test_group="all"))["group"] == "all"
        assert (await builds.build(test_group="core"))["group"] == "core"

    asyncio.run(run())


def test_small_trace_budget_retains_readable_partial_evidence(development):
    development.settings.limits.max_trace_bytes = 8192

    async def run():
        session = FakeSession(development)
        with pytest.raises(ToolFailure) as caught:
            await session.capture(3, 100)
        assert caught.value.code == "trace_overflow"
        evidence = session.artifacts.get(caught.value.details["artifact_id"])
        assert evidence["data"]["samples"]
        assert evidence["data"]["summary"]["outcome"] == "failed"

    asyncio.run(run())
