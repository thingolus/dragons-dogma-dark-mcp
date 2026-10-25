"""Fault-injected host runner tests. These do not establish native acceptance."""

import asyncio
from types import SimpleNamespace

import pytest

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure
from ddda_mcp.experiments import Experiments
from ddda_mcp.native_experiments import NativeExperiments, native_frame


def world(hp=10.0):
    return {
        "available": True,
        "samples": 4,
        "stage": 702,
        "generation": 1,
        "party": [
            {
                "id": "actor-1",
                "role": 0,
                "age_ms": 10,
                "position": [0.0, 0.0, 0.0],
                "resources": {"hp": hp, "hp_max": 100.0, "stamina": 50.0},
                "inventory": {"available": True, "items": []},
            },
            None,
        ],
        "enemies": {"available": True, "rows": [], "age_ms": 10, "truncated": False},
    }


def status():
    return {"stage": 702, "generation": 1, "menu_gated": False, "native_errors": 0, "faults": 0}


@pytest.mark.parametrize("problem", ["stage", "generation", "faults", "stale", "truncated"])
def test_copied_native_frames_refuse_or_expose_missing_evidence(problem):
    w, s = world(), status()
    if problem in ("stage", "generation", "faults"):
        s[problem] += 1
        with pytest.raises(ToolFailure):
            native_frame(w, s, "capture-a", 0, 500, 1000)
    else:
        if problem == "stale":
            w["party"][0]["age_ms"] = 1001
        else:
            w["enemies"]["truncated"] = True
        frame = native_frame(w, s, "capture-a", 0, 500, 1000)
        assert not frame.actors if problem == "stale" else not frame.complete


def setup(config, monkeypatch, fault=None):
    import ddda_mcp.native_experiments as module

    clock = [0.0]

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(
        module, "asyncio", SimpleNamespace(sleep=sleep, CancelledError=asyncio.CancelledError)
    )

    class Sessions:
        receipt = {
            "session_id": "a" * 32,
            "backend": "coop",
            "game_sha256": "b" * 64,
            "runtime_sha256": "c" * 64,
        }
        operation_lock = asyncio.Lock()
        claimed = False
        acted = False
        stopped = False
        operations = []

        def _admit(self):
            pass

        async def _snapshot(self):
            return status()

        async def _stop(self):
            self.stopped = True

        async def _request(self, op, **params):
            self.operations.append(op)
            if op == "control_status":
                return {
                    "running": self.claimed,
                    "phase": "ready",
                    "errors": [],
                    "action": None,
                    "menu_blocked": False,
                }
            if op == "world_start":
                return {"started": True}
            if op == "world_latest":
                if fault == "read" and self.acted:
                    raise ToolFailure("read_failed", "read failed")
                return world(15.0 if self.acted else 10.0)
            if op == "world_stop":
                return {"cleanup": {"sealed": fault != "seal", "errors": []}}
            if op == "control_action":
                self.acted = True
                if fault == "cancel":
                    raise asyncio.CancelledError()
                if fault == "action":
                    raise ToolFailure("native_refused", "action refused")
                return {"accepted": True}
            raise AssertionError(op)

    sessions = Sessions()

    class Controls:
        released = False

        async def _claim(self, mode):
            sessions.claimed = True
            if fault == "claim":
                raise ToolFailure("claim_failed", "partial claim")

        async def _release(self):
            self.released = True
            sessions.claimed = False
            if fault == "release":
                raise ToolFailure("release_failed", "release failed")
            return {"engine_release_verified": True}

    controls = Controls()
    artifacts = Artifacts(config)
    app = SimpleNamespace(sessions=sessions, controls=controls, artifacts=artifacts)
    plan = Experiments(artifacts, None).create(
        {
            "label": "host test",
            "goal": {"kind": "healing", "subject": {"role": 0}},
            "steps": [{"kind": "action", "command": {"action": "confirm"}}],
        }
    )
    return NativeExperiments(app), plan["artifact_id"], sessions, controls, artifacts


@pytest.mark.parametrize("fault", [None, "claim", "action", "read", "seal", "release", "cancel"])
def test_runner_records_outcomes_and_cleans_every_exit(development, monkeypatch, fault):
    runner, ident, sessions, controls, artifacts = setup(development, monkeypatch, fault)

    async def run():
        if fault == "cancel":
            with pytest.raises(asyncio.CancelledError) as error:
                await runner.run(ident)
            result = error.value.details
        else:
            result = await runner.run(ident)
        doc = artifacts.get(result["artifact_id"])
        assert doc["kind"] == "native_experiment"
        assert doc["data"]["summary"]["outcome"] == ("passed" if fault is None else "inconclusive")
        assert controls.released
        if fault != "claim":
            assert "world_stop" in sessions.operations
        if fault in ("seal", "release"):
            assert sessions.stopped
        if doc["data"]["recording"]:
            recorded = artifacts.get(doc["data"]["recording"]["artifact_id"])
            assert recorded["provenance"]["evidence_class"] == "native_callback_observation"

    asyncio.run(run())


def test_unsupported_semantics_refused_before_input(development, monkeypatch):
    runner, _, sessions, controls, artifacts = setup(development, monkeypatch)
    plan = Experiments(artifacts, None).create(
        {
            "label": "item",
            "goal": {"kind": "healing", "subject": {"role": 0}},
            "steps": [{"kind": "action", "command": {"action": "use_item", "item_id": 43}}],
        }
    )
    with pytest.raises(ToolFailure, match="dispatcher"):
        asyncio.run(runner.run(plan["artifact_id"]))
    assert not sessions.operations and not controls.released
