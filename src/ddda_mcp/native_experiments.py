"""Condition-driven plans on the owned native session. MIT, Thingolus.

Only callback-copied observations enter native evidence. Input is the reviewed
expiring developer provider, and all exit paths seal observers and release it.
"""

import asyncio
import time
import uuid

from .common import ToolFailure, digest
from .config import BASELINE
from .control import ACTIONS
from .diagnostics import fingerprint
from .experiments import (
    ActionStep,
    ExperimentPlan,
    RequireStep,
    check_condition,
    command_guard,
    measure_goal,
    replay,
)
from .gameplay_data import GameplayRecording, ObservationFrame
from .gameplay_events import derive_events


def native_frame(world, status, epoch, sequence, elapsed_ms, max_age_ms):
    """Convert copied values; no process addresses or caller-supplied recordings."""
    if not world.get("available") or not world.get("samples"):
        raise ToolFailure("observation_unavailable", "No native world callback has sampled this capture.")
    if (world["stage"], world["generation"]) != (status["stage"], status["generation"]):
        raise ToolFailure("world_changed", "Stage or generation changed during the experiment.")
    if status.get("native_errors") or status.get("faults"):
        raise ToolFailure("native_fault", "Native observer/provider reported a fault.")
    actors = []

    def actor(row, kind):
        resources = row.get("resources") or {}
        inv = row.get("inventory")
        return {
            "entity": {"key": row["id"], "scope": "capture", "epoch": epoch},
            "kind": kind,
            "role": row.get("role"),
            "position": row.get("position"),
            "hp": resources.get("hp"),
            "hp_max": resources.get("hp_max"),
            "stamina": resources.get("stamina"),
            "action": row.get("action"),
            "vocation": row.get("vocation"),
            "inventory": {"complete": True, "items": inv["items"]} if inv and inv.get("available") else None,
        }

    for row in world["party"]:
        if row and 0 <= row["age_ms"] <= max_age_ms:
            actors.append(actor(row, "party"))
    enemies = world.get("enemies") or {}
    fresh = enemies.get("available") and 0 <= enemies.get("age_ms", max_age_ms + 1) <= max_age_ms
    if fresh:
        actors.extend(actor(row, "registry_actor") for row in enemies["rows"])
    # Completeness is the bounded nearby selection, not all actors in the world.
    # Truncation remains explicit and prevents a positive verdict.
    omitted = 1 if fresh and enemies.get("truncated") else 0
    return ObservationFrame.model_validate(
        {
            "sequence": sequence,
            "elapsed_ms": elapsed_ms,
            "stage": status["stage"],
            "generation": status["generation"],
            "complete": not omitted,
            "omitted": omitted,
            "menu_open": bool(status["menu_gated"]),
            "actors": actors,
        }
    )


class NativeExperiments:
    def __init__(self, app):
        self.app = app

    def plan(self, plan_id):
        doc = self.app.artifacts.get(plan_id)
        if doc["kind"] != "experiment_plan":
            raise ToolFailure("plan_invalid", "Use a saved experiment plan.")
        data = doc["data"]
        if fingerprint(data["plan"]) != data["payload_sha256"]:
            raise ToolFailure("evidence_changed", "Plan payload changed.")
        for ident, sha in data["references"].items():
            if digest(self.app.artifacts.path(ident)) != sha:
                raise ToolFailure("evidence_changed", "A fixture or checkpoint reference changed.")
        plan = ExperimentPlan.model_validate(data["plan"])
        for step in plan.steps:
            if isinstance(step, ActionStep) and step.command.action not in ACTIONS:
                raise ToolFailure(
                    "backend_capability", f"Native command {step.command.action} has no reviewed dispatcher."
                )
        if plan.max_sample_gap_ms < 500:
            raise ToolFailure("sampling_budget", "Native plans require at least 500 ms sample-gap tolerance.")
        return plan

    async def run(self, plan_id, suite_id=None):
        plan = self.plan(plan_id)
        sessions, controls, artifacts = self.app.sessions, self.app.controls, self.app.artifacts
        sessions._admit()
        if (sessions.receipt or {}).get("backend", "coop") != "coop":
            raise ToolFailure(
                "backend_capability", "Native input plans require the reviewed co-op developer provider."
            )
        if plan.fixture_id:
            suite = self.app.suites.status(suite_id) if suite_id else {}
            active = suite.get("active") or {}
            if (
                suite.get("state") != "evaluating"
                or active.get("case", {}).get("fixture_id") != plan.fixture_id
                or active.get("case", {}).get("plan_id") != plan_id
                or active.get("session_id") != sessions.receipt["session_id"]
                or not active.get("save_backup")
            ):
                raise ToolFailure(
                    "fixture_unverified", "Run fixture-bound plans through a verified fixture trial."
                )
        async with sessions.operation_lock:
            return await self._execute(plan_id, plan, sessions, controls, artifacts)

    async def _execute(self, plan_id, plan, sessions, controls, artifacts):
        if (await sessions._request("control_status")).get("running"):
            raise ToolFailure("control_busy", "Release the existing control lease before a plan.")
        provenance = dict(sessions.receipt)
        epoch = "capture-" + uuid.uuid4().hex
        frames, actions, cleanup, dispatch = [], [], {}, []
        failure = None
        claimed = observing = False
        start = None

        async def stop_owned():
            try:
                await sessions._stop()
                cleanup["owned_process_stopped"] = True
            except BaseException as exc:
                cleanup.setdefault("recovery_errors", []).append(str(exc)[:300])
                cleanup["recovery_required"] = True

        async def sample():
            elapsed = round((time.monotonic() - start) * 1000)
            if elapsed > plan.max_duration_ms or len(frames) >= 256:
                raise ToolFailure("experiment_deadline", "Native observation budget exhausted.")
            world = await sessions._request("world_latest")
            status = await sessions._snapshot()
            lease = await sessions._request("control_status")
            if not lease.get("running") or lease.get("errors") or lease.get("phase") != "ready":
                raise ToolFailure("control_interrupted", "Provider lease is no longer ready.")
            if type(lease.get("menu_blocked")) is not bool:
                raise ToolFailure("menu_unavailable", "Canonical menu observation is unavailable.")
            status = {**status, "menu_gated": lease["menu_blocked"]}
            frame = native_frame(
                world, status, epoch, len(frames), elapsed, min(1000, plan.max_sample_gap_ms)
            )
            if frames and frame.elapsed_ms <= frames[-1].elapsed_ms:
                raise ToolFailure("clock_invalid", "Native sample clock did not advance.")
            frames.append(frame)
            return frame

        try:
            claimed = True  # Even a partially failed claim needs release.
            await controls._claim(plan.control_mode)
            observing = True
            await sessions._request("world_start", duration_ms=plan.max_duration_ms)
            start = time.monotonic()
            await asyncio.sleep(0.5)
            frame = await sample()
            for index, step in enumerate(plan.steps):
                if isinstance(step, RequireStep):
                    passed, reason = check_condition(step.condition, frame)
                    if passed is not True:
                        raise ToolFailure("condition_unmet", reason)
                elif isinstance(step, ActionStep):
                    reason = command_guard(step.command, frame)
                    if reason:
                        raise ToolFailure("command_refused", reason)
                    before = frame.sequence
                    deadline = time.monotonic() + step.timeout_ms / 1000
                    command = step.command
                    receipt = await sessions._request(
                        "control_action",
                        action=command.action,
                        role=command.role,
                        duration_ms=command.duration_ms,
                    )
                    dispatch.append({"step": index, "receipt": receipt})
                    until = time.monotonic() + command.duration_ms / 1000
                    while True:
                        await asyncio.sleep(0.5)
                        frame = await sample()
                        state = await sessions._request("control_status")
                        if not state.get("running") or state.get("errors"):
                            raise ToolFailure("control_interrupted", "Provider lease ended during input.")
                        if time.monotonic() >= deadline:
                            raise ToolFailure("action_deadline", "Action observation exceeded its deadline.")
                        if time.monotonic() >= until and state.get("action") is None:
                            break
                    actions.append(
                        {
                            "command": command.model_dump(),
                            "before_sequence": before,
                            "after_sequence": frame.sequence,
                            "outcome": "accepted",
                        }
                    )
                else:
                    deadline = time.monotonic() + step.timeout_ms / 1000
                    while True:
                        passed, reason = (
                            check_condition(step.condition, frame)
                            if step.condition
                            else (measure_goal(plan, frames)["passed"], "goal_not_observed")
                        )
                        if passed is True:
                            break
                        if passed is None:
                            raise ToolFailure("observation_unavailable", reason)
                        if time.monotonic() >= deadline:
                            raise ToolFailure("wait_deadline", reason)
                        await asyncio.sleep(0.5)
                        frame = await sample()
        except BaseException as exc:
            failure = exc
        finally:
            if observing:
                try:
                    sealed = await sessions._request("world_stop")
                    cleanup["observer"] = sealed["cleanup"]
                    if not sealed["cleanup"].get("sealed") or sealed["cleanup"].get("errors"):
                        raise ToolFailure("observer_cleanup", "Observer did not seal without errors.")
                except BaseException as exc:
                    failure = failure or exc
                    await stop_owned()
            if claimed:
                try:
                    cleanup["input"] = await controls._release()
                except BaseException as exc:
                    failure = failure or exc
                    await stop_owned()
        recording_receipt = None
        report = {
            "summary": {
                "outcome": "inconclusive",
                "reason": str(failure)[:500] if failure else "no_observations",
                "evidence_class": "native_experiment",
                "native_acceptance": "unverified",
            }
        }
        if frames:
            identity = {
                "session": "session-" + provenance["session_id"],
                "clock": "monotonic-host",
                "game_sha256": provenance["game_sha256"],
                "source_commit": BASELINE,
                "backend": "coop",
                "runtime_sha256": provenance["runtime_sha256"],
            }
            released = cleanup.get("input", {})
            recording = GameplayRecording.model_validate(
                {
                    "label": plan.label,
                    "identity": identity,
                    "frames": [f.model_dump() for f in frames],
                    "actions": actions,
                    "cleanup": {
                        "input_released": bool(
                            released.get("engine_release_verified")
                            or released.get("owned_process_stopped")
                            or cleanup.get("owned_process_stopped")
                        ),
                        "observers_sealed": bool(cleanup.get("observer", {}).get("sealed")),
                        "restoration": "not_applicable",
                    },
                    "terminal": "cancelled"
                    if isinstance(failure, asyncio.CancelledError)
                    else "failed"
                    if failure
                    else "completed",
                }
            )
            payload = recording.model_dump()
            decoded = derive_events(recording)
            recording_receipt = artifacts.put(
                "gameplay_recording",
                {
                    "recording": payload,
                    "payload_sha256": fingerprint(payload),
                    "decoded": decoded,
                    "summary": decoded["summary"],
                },
                {**provenance, "evidence_class": "native_callback_observation"},
            )
            report = replay(plan, recording)
            report["summary"].update(
                evidence_class="native_experiment",
                native_acceptance="measured" if report["summary"]["outcome"] == "passed" else "unverified",
            )
            report["limitations"] = [
                "HP and inventory deltas are observations, not action/attacker attribution.",
                "Entity identities are capture-scoped; address reuse between callbacks cannot be excluded.",
                "This individual run does not back up or restore saves or installed files; gameplay may autosave. Use a fixture suite for isolation.",
            ]
        report.update(
            cleanup=cleanup,
            dispatch=dispatch,
            recording=recording_receipt,
            error={"type": type(failure).__name__, "message": str(failure)[:500]} if failure else None,
        )
        result = artifacts.put(
            "native_experiment",
            report,
            {
                **provenance,
                "plan_id": plan_id,
                "plan_sha256": digest(artifacts.path(plan_id)),
                "evidence_class": "native_experiment",
            },
        )
        if isinstance(failure, asyncio.CancelledError):
            failure.details = result
            raise failure
        return {**result, "summary": report["summary"], "recording": recording_receipt, "cleanup": cleanup}


def register_tools(mcp, app):
    from .server import Result, Write

    @mcp.tool(annotations=Write)
    async def run_native_experiment(plan_id: str) -> Result:
        """Run a saved bounded plan on the owned offline game, measure copied outcomes, seal hooks and release input on every exit."""
        return await app.invoke("run_native_experiment", app.native_experiments.run, plan_id)
