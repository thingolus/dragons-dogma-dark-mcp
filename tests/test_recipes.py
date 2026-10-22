import asyncio

import pytest
from test_operations import FakeSession

from ddda_mcp.common import ToolFailure
from ddda_mcp.recipes import MOVEMENT, catalog


def ready(config):
    session = FakeSession(config)
    original = session._request

    async def request(op, **params):
        result = await original(op, **params)
        if op == "snapshot":
            result.update(
                p1=2, p2=3, physical_mask=0, menu_gated=0, actors=[{"observed": 1}, {"observed": 1}]
            )
        return result

    session._request = request
    return session


@pytest.mark.parametrize("recipe", list(MOVEMENT))
def test_recipe_cleanup_provenance_and_one_shot(development, recipe):
    async def run():
        session = ready(development)
        result = await session.movement(recipe)
        assert result["summary"]["input_released"]
        assert result["summary"]["outcome"] == "completed"
        pulses = [p for op, p in session.calls if op == "movement_pulse"]
        assert len(pulses) == 3 and all(p["recipe"] == recipe for p in pulses)
        assert ("neutral", {"connected": False}) in session.calls
        artifact = session.artifacts.get(result["artifact_id"])
        assert artifact["provenance"]["recipe"] == recipe
        with pytest.raises(ToolFailure, match="once"):
            await session.movement(recipe)

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        dict(stage=0),
        dict(generation=0),
        dict(menu_gated=1),
        dict(physical_mask=1),
        dict(p1=-1),
        dict(p1=3),
        dict(actors=[{"observed": 0}, {"observed": 1}]),
    ],
)
def test_recipe_refuses_unready_world_before_input(development, change):
    async def run():
        session = ready(development)
        original = session._request

        async def request(op, **params):
            result = await original(op, **params)
            if op == "snapshot":
                result.update(change)
            return result

        session._request = request
        with pytest.raises(ToolFailure, match="Movement needs"):
            await session.movement("p1_step_forward")
        assert all(op == "snapshot" for op, _ in session.calls)

    asyncio.run(run())


def test_cancelled_movement_releases_and_retains_evidence(development):
    async def run():
        session = ready(development)
        task = asyncio.create_task(session.movement("p1_step_right"))
        while not any(op == "movement_pulse" for op, _ in session.calls):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert session.calls[-1] == ("neutral", {"connected": False})
        artifact = session.artifacts.get(caught.value.artifact["artifact_id"])
        assert artifact["data"]["summary"]["outcome"] == "cancelled"

    asyncio.run(run())


def test_world_change_releases_and_fails(development):
    async def run():
        session = ready(development)
        original = session._request

        async def request(op, **params):
            result = await original(op, **params)
            if op == "snapshot" and any(call == "movement_pulse" for call, _ in session.calls):
                result["generation"] = 99
            return result

        session._request = request
        with pytest.raises(ToolFailure, match="World"):
            await session.movement("p1_step_forward")
        assert session.calls[-1] == ("neutral", {"connected": False})

    asyncio.run(run())


def test_release_failure_stops_owned_game(development):
    async def run():
        session = ready(development)
        original = session._request
        stopped = []

        async def request(op, **params):
            if op == "neutral":
                raise RuntimeError("release failed")
            return await original(op, **params)

        async def stop():
            stopped.append(True)

        session._request, session._stop = request, stop
        with pytest.raises(ToolFailure, match="release failed"):
            await session.movement("p2_step_forward")
        assert stopped and session.unusable

    asyncio.run(run())


def test_catalog_does_not_claim_native_acceptance():
    entries = {r["name"]: r for r in catalog()["recipes"]}
    assert len(entries) == 6
    assert all("unverified" in entries[name]["native_acceptance"] for name in MOVEMENT)
