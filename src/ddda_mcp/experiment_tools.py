"""Offline experiment tools; never acquire a native session. MIT, Thingolus."""

from typing import Annotated, Literal

from pydantic import Field

from .experiments import ExperimentPlan
from .gameplay_data import GameplayRecording, Token


def register_tools(mcp, app):
    from .server import Read, Result, Write

    @mcp.tool(annotations=Read)
    async def experiment_catalog() -> Result:
        """Describe replay/native plans, bounded steps, outcome meanings and supported backend capabilities. No game access."""
        return await app.invoke("experiment_catalog", app.experiments.catalog)

    @mcp.tool(annotations=Write)
    async def create_experiment_plan(plan: ExperimentPlan) -> Result:
        """Validate and save a condition-driven movement/combat/healing/revival/loot plan; bind optional fixture hashes without loading saves."""
        return await app.invoke("create_experiment_plan", app.experiments.create, plan)

    @mcp.tool(annotations=Write)
    async def record_gameplay_observations(recording: GameplayRecording) -> Result:
        """Store typed copied observations and action receipts as offline-supplied evidence; derive bounded noncausal gameplay events."""
        return await app.invoke("record_gameplay_observations", app.recordings.save, recording)

    @mcp.tool(annotations=Read)
    async def query_gameplay_events(
        recording_id: str,
        kind: Literal[
            "hp_decreased", "hp_increased", "zero_hp_to_positive", "inventory_delta", "action_changed"
        ]
        | None = None,
        entity_key: Token | None = None,
        offset: Annotated[int, Field(ge=0, le=4096)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Replay and page derived events, retaining identity boundaries, gaps and original decoder comparison. No game access."""
        return await app.invoke(
            "query_gameplay_events", app.recordings.query, recording_id, kind, entity_key, offset, limit
        )

    @mcp.tool(annotations=Write)
    async def replay_gameplay_experiment(plan_id: str, recording_id: str) -> Result:
        """Execute a saved plan against a recorded tape only; return a compact verdict, cleanup limitations, timing and evidence receipt."""
        return await app.invoke("replay_gameplay_experiment", app.experiments.run, plan_id, recording_id)
