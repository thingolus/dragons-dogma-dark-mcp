"""Model tests of isolation decisions; no simulated result is native acceptance."""

import asyncio
from types import SimpleNamespace

import pytest

from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.mod_isolation import ModIsolation, partitions, verdict


def trial(outcome="failed", **extra):
    return {"outcome": outcome, "cleanup_verified": True, "shared_life_unchanged": True, **extra}


def test_repeats_cleanup_and_native_crash_distinctions():
    assert verdict([trial(), trial()], "test_failure") == "failed"
    assert verdict([trial(), trial("passed")], "test_failure") == "inconclusive"
    assert verdict([trial(cleanup_verified=False)], "test_failure") == "inconclusive"
    assert (
        verdict([trial("inconclusive", crash_reports=[{"kind": "observed_native_exception"}])], "crash")
        == "inconclusive"
    )
    assert verdict([trial("inconclusive", crash_reports=[{"kind": "native_crash"}])] * 2, "crash") == "failed"
    assert verdict([trial(crash_reports=[])], "crash") == "passed"


@pytest.mark.parametrize("culprit", [{"c"}, {"b", "d"}, {"a", "b", "c", "d"}])
def test_delta_debugger_finds_single_and_interacting_mods(development, culprit):
    engine = ModIsolation(SimpleNamespace(config=development))
    mods = list("abcd")
    state = {
        "state": "ready",
        "phase": "baseline",
        "all_mods": mods,
        "best": mods,
        "granularity": 2,
        "pending": [],
        "tested": [],
        "trials": [],
        "max_suites": 64,
        "active": None,
    }
    engine._accept(state, [], "passed", {})
    for _ in range(64):
        if state["state"] != "ready":
            break
        subset = state["pending"].pop(0)
        engine._accept(state, subset, "failed" if culprit <= set(subset) else "passed", {})
    assert state["state"] == "completed"
    assert set(state["best"]) == culprit
    assert state["reason"] == "one_minimal_reproducing_set"


def test_unknown_subset_never_becomes_a_minimality_claim(development):
    engine = ModIsolation(SimpleNamespace(config=development))
    state = {
        "state": "ready",
        "phase": "reduce",
        "all_mods": ["a", "b"],
        "best": ["a", "b"],
        "granularity": 2,
        "pending": [["b"]],
        "tested": [],
        "trials": [],
        "max_suites": 64,
        "active": None,
    }
    engine._accept(state, ["a"], "inconclusive", {})
    state["pending"].pop(0)
    engine._accept(state, ["b"], "passed", {})
    assert state["state"] == "inconclusive"


def test_partitions_are_unique_and_include_complements():
    assert partitions(list("abcde"), 2) == [list("ab"), list("cde")]
    assert list("abc") in partitions(list("abcde"), 3)


@pytest.mark.parametrize("mode", ["completed_before_host_exit", "cancelled", "abort_changed_reference"])
def test_durable_suite_boundary_and_recovery(development, mode):
    suite_id, ident = "a" * 32, "b" * 32
    suite_path = development.artifacts / "fake-suite.json"
    suite = {
        "id": suite_id,
        "state": "completed" if mode == "completed_before_host_exit" else "awaiting_world",
        "trials": [trial("passed"), trial("passed")],
    }
    atomic_json(suite_path, suite)
    calls = []

    async def advance(selected, action):
        calls.append(action)
        suite["state"] = "aborted"
        atomic_json(suite_path, suite)
        if action != "abort":
            raise asyncio.CancelledError()
        return suite

    app = SimpleNamespace(
        config=development,
        suites=SimpleNamespace(status=lambda _: suite, path=lambda _: suite_path, advance=advance),
        artifacts=SimpleNamespace(path=lambda _: development.artifacts / "missing"),
    )
    engine = ModIsolation(app)
    data = {
        "id": ident,
        "state": "awaiting_world",
        "phase": "baseline",
        "active": {"suite_id": suite_id, "mods": []},
        "all_mods": ["m", "n"],
        "best": ["m", "n"],
        "tested": [],
        "trials": [],
        "pending": [],
        "max_suites": 64,
        "criterion": "test_failure",
        "references": {"missing": "bad"} if mode == "abort_changed_reference" else {},
    }
    atomic_json(engine.path(ident), data)
    if mode == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(engine.advance(ident, "evaluate"))
        assert engine.status(ident)["state"] == "aborted"
        assert engine.status(ident)["error"]["type"] == "CancelledError"
    else:
        result = asyncio.run(
            engine.advance(ident, "abort" if mode == "abort_changed_reference" else "evaluate")
        )
        if mode == "completed_before_host_exit":
            assert result["phase"] == "full" and result["active"] is None
            assert len(result["trials"]) == 1 and calls == []
            with pytest.raises(ToolFailure):
                asyncio.run(engine.advance(ident, "evaluate"))
        else:
            assert result["state"] == "aborted" and calls == ["abort"]
