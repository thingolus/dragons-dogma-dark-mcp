"""Synthetic failure-boundary tests for gameplay control and isolated patch workflows."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

import ddda_mcp
from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure
from ddda_mcp.control import verify_control_build
from ddda_mcp.patches import Patches, edit_path
from ddda_mcp.regression import Regressions
from ddda_mcp.scenarios import Diagnosis, evaluate_step
from ddda_mcp.source import Source


@pytest.mark.parametrize(
    "path",
    [
        "../src/x.cpp",
        "src/../../x.cpp",
        "C:/src/x.cpp",
        "src/x.cpp:stream",
        "src/x.ps1",
        "tests/a./x.cpp",
        "src\\x.cpp",
    ],
)
def test_overlay_rejects_escaped_or_executable_paths(path):
    with pytest.raises(ToolFailure):
        edit_path(path)


def test_patch_only_changes_isolated_source_and_checks_hashes(development, tmp_path):
    source = Source(development)
    artifacts = Artifacts(development)
    patches = Patches(source, artifacts)
    original = source.read("src/example.cpp")
    sha = hashlib.sha256(original.encode()).hexdigest()
    edit = {"path": "src/example.cpp", "expected_sha256": sha, "content": "int answer(){return 43;}\n"}
    receipt = patches.create("bounded overlay", [edit])
    isolated = tmp_path / "isolated"
    (isolated / "src").mkdir(parents=True)
    target = isolated / "src/example.cpp"
    target.write_bytes(original.encode())
    patches.apply(receipt["artifact_id"], isolated, source.commit)
    assert target.read_text() == edit["content"]
    assert source.read("src/example.cpp") == original
    with pytest.raises(ToolFailure, match="differs"):
        patches.apply(receipt["artifact_id"], isolated, source.commit)
    edit["expected_sha256"] = "0" * 64
    with pytest.raises(ToolFailure, match="differs"):
        patches.create("conflict", [edit])


def test_provider_source_label_alone_does_not_authorize_ownership(development):
    with pytest.raises(ToolFailure, match="Build the pinned"):
        verify_control_build(development, {"runtime_sha256": "a" * 64})


def test_predicates_do_not_equate_input_delivery_with_effect():
    result = {
        "effects": {
            "provider_neutral": True,
            "callbacks_advanced": True,
            "distance": 0,
            "action_changed": False,
        },
        "samples": [{"menu_gated": 0}],
    }
    assert evaluate_step(result, "moved") is False
    assert evaluate_step(result, "action_transition") is False
    assert evaluate_step(result, "menu_open") is False
    result["effects"]["provider_neutral"] = False
    assert evaluate_step(result, "moved") is None


def test_patch_comparison_tracks_variants_not_duplicate_commit_names():
    service = object.__new__(Regressions)
    data = {"mode": "patch_verification", "revisions": ["a" * 40], "repeats": 1, "trials": []}
    assert service._decision(data)["variant"] == "baseline"
    data["trials"].append({"variant": "baseline", "outcome": "passed"})
    assert service._decision(data)["variant"] == "candidate"
    data["trials"].append({"variant": "candidate", "outcome": "failed"})
    assert service._decision(data)["comparison"] == "regressed"
    data["trials"][-1]["outcome"] = "inconclusive"
    assert service._decision(data)["state"] == "inconclusive"


def test_diagnosis_preserves_unknown_and_foreign_session_evidence(development):
    artifacts = Artifacts(development)
    provenance = {"session_id": "a" * 32, "evidence_class": "synthetic"}
    result = artifacts.put(
        "gameplay_scenario",
        {
            "steps": [{"index": 0, "action": "forward", "role": 0, "predicate": "moved", "passed": None}],
            "summary": {"outcome": "inconclusive"},
        },
        provenance,
    )
    unrelated = artifacts.put("function_trace", {"summary": {"events": 4}}, {"session_id": "b" * 32})
    receipt = Diagnosis(Source(development), artifacts).analyze(
        result["artifact_id"], [unrelated["artifact_id"]]
    )
    data = artifacts.get(receipt["artifact_id"])["data"]
    assert data["first_observed_divergence"]["passed"] is None
    assert not data["evidence"][1]["same_session"]
    assert not data["native_events"]


def test_actual_control_js_expiry_guards_and_release():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    result = subprocess.run(
        [
            node,
            str(Path(__file__).with_name("control_contract.cjs")),
            str(Path(ddda_mcp.__file__).with_name("control.js")),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_legacy_campaign_recipe_defaults_to_idle():
    # Migration compatibility: pre-0.8 journals have no recipe key.
    service = object.__new__(Regressions)
    decision = service._decision({"revisions": ["a", "b"], "trials": [], "repeats": 2})
    assert decision == {"state": "ready", "revision": "a"}


@pytest.mark.parametrize("mode", ["pass", "no_effect", "cancel", "unsealed", "busy", "raced_lease"])
def test_scenario_keeps_evidence_and_cleans_up_on_every_outcome(development, mode):
    import asyncio
    from types import SimpleNamespace

    from ddda_mcp.scenarios import Scenarios

    artifacts = Artifacts(development)
    checkpoint = artifacts.put("gameplay_checkpoint", {}, {})["artifact_id"]
    events = []

    async def request(operation, **parameters):
        events.append(operation)
        if operation == "control_status":
            return {"running": mode == "busy" or (mode == "raced_lease" and events.count(operation) == 2)}
        return {"sealed": mode != "unsealed", "rows": []}

    async def stop():
        events.append("stop")
        return {"stopped": True}

    async def ready(*args):
        return []

    async def claim():
        events.append("claim")
        return {"phase": "ready"}

    async def release():
        events.append("release")
        return {"engine_release_verified": True}

    async def action(*args):
        if mode == "cancel":
            raise asyncio.CancelledError()
        return {
            "effects": {
                "provider_neutral": True,
                "callbacks_advanced": True,
                "distance": 2 if mode == "pass" else 0,
            },
            "samples": [],
        }

    async def run():
        session = SimpleNamespace(
            receipt={"session_id": "a" * 32},
            _admit=lambda: None,
            operation_lock=asyncio.Lock(),
            _request=request,
            _stop=stop,
            stop=stop,
        )
        harness = SimpleNamespace(sessions=session, load=lambda _: {}, wait_ready=ready, config=development)
        controls = SimpleNamespace(_claim=claim, _action=action, _release=release)
        service = Scenarios(harness, controls, artifacts)
        if mode in {"busy", "raced_lease"}:
            with pytest.raises(ToolFailure) as error:
                await service.run(checkpoint, "movement_pair")
            assert error.value.code == "control_busy"
            assert not {"claim", "release", "stop", "trace_start"}.intersection(events)
            assert not session.operation_lock.locked()
            return
        if mode in {"cancel", "unsealed"}:
            with pytest.raises(asyncio.CancelledError if mode == "cancel" else ToolFailure) as error:
                await service.run(checkpoint, "movement_pair")
            result = artifacts.get(error.value.details["artifact_id"])
            assert result["data"]["summary"]["outcome"] == "inconclusive"
        else:
            result = await service.run(checkpoint, "movement_pair")
            assert result["outcome"] == ("passed" if mode == "pass" else "failed")
        assert "trace_stop" in events and "stop" in events
        if mode != "unsealed":
            assert "release" in events

    asyncio.run(run())
