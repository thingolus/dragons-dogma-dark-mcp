"""Expiring, exclusive developer input with copied-state effect checks. MIT, Thingolus."""

import asyncio
import math
import time

from .artifacts import Artifacts
from .common import ToolFailure, digest, read_json
from .config import BASELINE

ACTIONS = {
    "forward",
    "backward",
    "left",
    "right",
    "light_attack",
    "heavy_attack",
    "jump",
    "interact",
    "sheath",
    "grab",
    "dodge",
    "menu",
    "inventory",
    "menu_up",
    "menu_down",
    "confirm",
    "cancel",
    "neutral",
}


def verify_control_build(config, receipt):
    """Do not infer provider ownership from a source-commit label alone."""
    runtime_hash = receipt.get("runtime_sha256", "")
    if len(runtime_hash) != 64 or any(c not in "0123456789abcdef" for c in runtime_hash):
        raise ToolFailure("control_unreviewed", "Runtime identity is missing.")
    path = config.artifacts / "control-builds" / (runtime_hash + ".json")
    if not path.exists():
        raise ToolFailure(
            "control_unreviewed", "Build the pinned source through this MCP before taking input ownership."
        )
    proof = read_json(path)
    artifacts = Artifacts(config)
    doc = artifacts.get(proof["artifact_id"])
    if (
        digest(artifacts.path(proof["artifact_id"])) != proof["sha256"]
        or doc["kind"] != "build"
        or doc["provenance"].get("source_commit") != BASELINE
        or not doc["provenance"].get("control_reviewed")
        or not doc["data"]["summary"]["passed"]
        or doc["data"]["binaries"].get("ddcoop_runtime.dll") != runtime_hash
        or receipt.get("runtime_source_commit") != BASELINE
    ):
        raise ToolFailure("control_unreviewed", "Runtime does not match a reviewed provider build receipt.")
    return proof


class Controls:
    def __init__(self, sessions, artifacts):
        self.sessions, self.artifacts = sessions, artifacts

    async def _claim(self):
        await self.sessions._request("control_claim")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = await self.sessions._request("control_status")
            if not state["running"]:
                raise ToolFailure("control_join_failed", str(state))
            if state["phase"] == "ready":
                return state
            await asyncio.sleep(0.1)
        raise ToolFailure("control_join_failed", "No verified assignment before the join deadline.")

    async def claim(self):
        self.sessions._admit()
        async with self.sessions.operation_lock:
            if (await self.sessions._request("control_status")).get("running"):
                raise ToolFailure("control_busy", "A gameplay control lease is already active.")
            try:
                return await self._claim()
            except BaseException:
                await self._release()
                raise

    async def _release(self):
        try:
            acknowledged = await self.sessions._request("control_release")
            deadline = time.monotonic() + 3
            previous = None
            while time.monotonic() < deadline:
                row = await self.sessions._snapshot()
                if (
                    previous
                    and row["p1"] < 0
                    and row["p2"] < 0
                    and all(
                        a["held"] == 0 and a["frames"] > b["frames"]
                        for a, b in zip(row["actors"], previous["actors"], strict=True)
                    )
                ):
                    return {**acknowledged, "engine_release_verified": True}
                previous = row
                await asyncio.sleep(0.1)
            # Menu callbacks may be gated; process termination is the fallback proof.
            await self.sessions._stop()
            return {**acknowledged, "engine_release_verified": False, "owned_process_stopped": True}
        except BaseException:
            await self.sessions._stop()
            raise

    async def release(self):
        self.sessions._admit()
        async with self.sessions.operation_lock:
            return await self._release()

    async def _action(self, action, role=0, duration_ms=250):
        if (
            action not in ACTIONS
            or type(role) is not int
            or role not in {0, 1}
            or type(duration_ms) is not int
            or not 50 <= duration_ms <= 1000
            or (action == "dodge" and duration_ms < 350)
        ):
            raise ToolFailure(
                "invalid_parameters",
                "Use a cataloged action, role 0/1 and duration 50–1000 ms (dodge: 350–1000).",
            )
        before = await self.sessions._snapshot()
        request = await self.sessions._request(
            "control_action", action=action, role=role, duration_ms=duration_ms
        )
        samples = []
        deadline = time.monotonic() + duration_ms / 1000 + 0.5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            samples.append(await self.sessions._snapshot())
        state = await self.sessions._request("control_status")
        if not state["running"] or state["errors"]:
            raise ToolFailure("control_interrupted", str(state))
        after = samples[-1]
        base = before["actors"][role]
        return {
            "request": request,
            "before": before,
            "samples": samples,
            "effects": {
                "distance": max(math.dist(base["position"], r["actors"][role]["position"]) for r in samples),
                "action_changed": any(r["actors"][role]["action"] != base["action"] for r in samples),
                "menu_changed": any(r["menu_gated"] != before["menu_gated"] for r in samples),
                "callbacks_advanced": after["actors"][role]["frames"] > base["frames"],
                "provider_neutral": state["action"] is None,
            },
            "limitations": "Action transitions are observations, not proof of damage, interaction success or learned dodge.",
        }

    async def action(self, action, role=0, duration_ms=250):
        self.sessions._admit()
        async with self.sessions.operation_lock:
            try:
                data = await self._action(action, role, duration_ms)
            except BaseException:
                await self._release()
                raise
        return self.artifacts.put(
            "gameplay_action", data, {**self.sessions.receipt, "evidence_class": "native_input_observation"}
        )

    async def world(self, seconds=2):
        self.sessions._admit()
        if not 0.2 <= seconds <= 10:
            raise ToolFailure("invalid_parameters", "World capture lasts 0.2–10 seconds.")
        provenance = dict(self.sessions.receipt or {})
        async with self.sessions.operation_lock:
            await self.sessions._request("world_start", duration_ms=round(seconds * 1000))
            failure = None
            try:
                await asyncio.sleep(seconds)
            except BaseException as exc:
                failure = exc
            try:
                result = await self.sessions._request("world_stop")
                if not result["cleanup"].get("sealed"):
                    await self.sessions._stop()
                    raise ToolFailure(
                        "hook_cleanup_failed", "World observer did not seal; owned game stopped."
                    )
            except BaseException:
                await self.sessions._stop()
                raise
            artifact = self.artifacts.put(
                "world_capture", result, {**provenance, "evidence_class": "native_callback_observation"}
            )
            if failure:
                failure.details = artifact
                raise failure
            return {
                **artifact,
                "world": result["world"],
                "cleanup": {k: v for k, v in result["cleanup"].items() if k != "rows"},
            }
