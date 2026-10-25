"""Fixture libraries and resumable mod/profile gameplay matrices. MIT, Thingolus."""

import asyncio
import math
import uuid

import portalocker

from .common import ToolFailure, atomic_json, digest, identifier, read_json
from .scenarios import SCENARIOS


def outcome(predicate, before, after, scenario, role=0, item_id=None, minimum=1.0):
    """Unknown/precondition failure is never a successful gameplay assertion."""
    if predicate == "scenario":
        return {
            "passed": scenario.get("outcome") == "passed"
            if scenario.get("outcome") in {"passed", "failed"}
            else None
        }
    if before.get("stage") != after.get("stage") or before.get("generation") != after.get("generation"):
        return {"passed": None, "reason": "world_changed"}
    if predicate == "damage":
        trace = scenario.get("native_trace", {})
        if not trace.get("sealed") or trace.get("errors") or trace.get("omitted"):
            return {"passed": None, "reason": "incomplete_health_trace"}
        hits = [
            r["applied_damage"]
            for r in trace.get("rows", [])
            if r.get("kind") == "health"
            and r.get("main_resource")
            and not r.get("lifetime_changed")
            and type(r.get("applied_damage")) in (int, float)
        ]
        amount = sum(max(0, v) for v in hits)
        return {
            "passed": amount >= minimum,
            "damage": amount,
            "scope": "Observed main-resource damage for reviewed actor classes; attacker attribution unverified.",
        }
    party_a, party_b = before.get("party", []), after.get("party", [])
    if len(party_a) <= role or len(party_b) <= role or not party_a[role] or not party_b[role]:
        return {"passed": None, "reason": "party_unavailable"}
    a, b = party_a[role], party_b[role]
    if predicate in {"healed", "revived"}:
        a, b = a.get("resources"), b.get("resources")
        if not a or not b or (predicate == "revived" and a["hp"] > 0):
            return {"passed": None, "reason": "resource_or_precondition_unavailable"}
        delta = b["hp"] - a["hp"]
        return {
            "passed": delta >= minimum if predicate == "healed" else b["hp"] > 0,
            "hp_delta": delta,
            "scope": "HP transition; complete engine revival state is not inferred.",
        }
    if predicate == "inventory_gain":
        a, b = a.get("inventory", {}), b.get("inventory", {})
        if item_id is None or not a.get("available") or not b.get("available"):
            return {"passed": None, "reason": "inventory_or_item_unavailable"}

        def total(inv):
            return sum(x["quantity"] for x in inv["items"] if x["item_id"] == item_id)

        delta = total(b) - total(a)
        return {"passed": delta >= minimum, "quantity_delta": delta, "item_id": item_id}
    raise ToolFailure("predicate_unknown", "Select a supported suite predicate.")


class Suites:
    def __init__(self, app):
        self.app = app
        self.root = app.config.artifacts / "suites"
        self.lock = asyncio.Lock()

    def fixture(self, checkpoint_id, label, world_id=None):
        self.app.config.require_development()
        checkpoint = self.app.harness.load(checkpoint_id)
        if not label.strip() or len(label) > 120:
            raise ToolFailure("fixture_invalid", "Use a short descriptive fixture name.")
        evidence, traits = None, {}
        if world_id:
            doc = self.app.artifacts.get(world_id)
            world = doc["data"].get("world", {})
            cleanup = doc["data"].get("cleanup", {})
            if (
                doc["kind"] not in {"world_capture", "standalone_world"}
                or doc["provenance"].get("evidence_class") != "native_callback_observation"
                or not cleanup.get("sealed")
                or cleanup.get("errors")
                or not world.get("samples")
                or world.get("stage") != checkpoint["stage"]
                or not world.get("party", [None])[0]
                or math.dist(world["party"][0]["position"], checkpoint["position"])
                > checkpoint["position_tolerance"]
            ):
                raise ToolFailure("fixture_invalid", "World evidence does not match the checkpoint location.")
            traits = {
                "vocations": [p.get("vocation") if p else None for p in world["party"]],
                "nearby_enemies": len((world.get("enemies") or {}).get("rows", [])),
            }
            evidence = {"id": world_id, "sha256": digest(self.app.artifacts.path(world_id))}
        data = {
            "checkpoint_id": checkpoint_id,
            "checkpoint_sha256": digest(self.app.artifacts.path(checkpoint_id)),
            "world_evidence": evidence,
            "traits": traits,
            "label": label,
            "summary": {"label": label, "stage": checkpoint["stage"], **traits},
            "limitations": "Save fixture with observed location/traits; no guarantee of identical AI, RNG, enemy or quest state on reload.",
        }
        return self.app.artifacts.put("gameplay_fixture", data, {"evidence_class": "registered_fixture"})

    def fixtures(self):
        rows = []
        for path in sorted(self.app.config.artifacts.glob("*.json")):
            doc = read_json(path)
            if doc.get("kind") == "gameplay_fixture":
                rows.append({"artifact_id": doc["id"], **doc["data"]["summary"]})
        return {"fixtures": rows[-100:], "total": len(rows)}

    def create(self, label, cases, profiles=None, repeats=1, candidate=None):
        self.app.config.require_development()
        profiles = profiles or [None]
        if (
            not label.strip()
            or len(label) > 120
            or not 1 <= len(cases) <= 12
            or not 1 <= repeats <= 3
            or len(cases) * len(profiles) * repeats > 24
        ):
            raise ToolFailure("suite_invalid", "Use a label and at most 24 total trials.")
        candidate_sha = None
        if candidate:
            folder, _ = self.app.deployment.candidate(candidate)
            candidate_sha = digest(folder / "candidate.json")
        refs = {}
        for case in cases:
            doc = self.app.artifacts.get(case["fixture_id"])
            if doc["kind"] != "gameplay_fixture" or case["recipe"] not in {"observe_idle", *SCENARIOS}:
                raise ToolFailure("suite_invalid", "Select registered fixtures and reviewed recipes.")
            if case.get("plan_id"):
                plan = self.app.native_experiments.plan(case["plan_id"])
                if plan.fixture_id != case["fixture_id"]:
                    raise ToolFailure(
                        "suite_invalid", "Native plans must bind the same fixture as their trial."
                    )
                refs[case["plan_id"]] = digest(self.app.artifacts.path(case["plan_id"]))
            if case.get("predicate", "scenario") not in {
                "scenario",
                "damage",
                "healed",
                "revived",
                "inventory_gain",
            }:
                raise ToolFailure("suite_invalid", "Unknown outcome predicate.")
            if case.get("predicate") == "damage" and case["recipe"] != "attack_pair":
                raise ToolFailure("suite_invalid", "Damage assertions require the attack health trace.")
            refs[case["fixture_id"]] = digest(self.app.artifacts.path(case["fixture_id"]))
        for profile in profiles:
            if profile:
                doc = self.app.artifacts.get(profile)
                if doc["kind"] != "mod_profile" or not doc["data"]["summary"]["compatible"]:
                    raise ToolFailure("suite_invalid", "Profile is unresolved.")
                refs[profile] = digest(self.app.artifacts.path(profile))
        ident = uuid.uuid4().hex
        data = {
            "id": ident,
            "label": label,
            "state": "ready",
            "references": refs,
            "candidate": candidate,
            "candidate_sha256": candidate_sha,
            "queue": [
                {"case": c, "profile_id": p, "repeat": n}
                for p in profiles
                for c in cases
                for n in range(repeats)
            ],
            "trials": [],
            "active": None,
        }
        atomic_json(self.path(ident), data)
        return data

    def path(self, ident):
        return self.root / (identifier(ident) + ".json")

    def status(self, ident):
        return read_json(self.path(ident))

    async def cleanup(self, data):
        active = data.get("active")
        if not active:
            return
        current = self.app.sessions.receipt
        if current:
            if current.get("session_id") != active.get("session_id"):
                raise ToolFailure("session_busy", "Another owned game prevents suite cleanup.")
            await self.app.sessions.stop()
        if active.get("profile_started") and not active.get("profile_restored"):
            marker = self.app.mods.status()
            if marker["state"] != "clear" and (
                marker.get("profile_id") != active.get("profile_id")
                or marker.get("owner_id") != active.get("profile_owner")
            ):
                raise ToolFailure("profile_owner", "A different active profile prevents suite cleanup.")
            await asyncio.to_thread(self.app.mods.restore)
            active["profile_restored"] = True
            atomic_json(self.path(data["id"]), data)
        if active.get("deployment") and not active.get("deployment_restored"):
            receipt = self.app.deployment._read(active["deployment"])
            if receipt["state"] != "prepared":
                await asyncio.to_thread(self.app.deployment.rollback, active["deployment"])
            active["deployment_restored"] = True
            atomic_json(self.path(data["id"]), data)
        if active.get("save_backup") and not active.get("saves_restored"):
            await asyncio.to_thread(self.app.saves.restore, active["save_backup"])
            active["saves_restored"] = True
            atomic_json(self.path(data["id"]), data)
        active["shared_life_unchanged"] = self.app.regressions._shared_hash() == active.get(
            "shared_life_sha256"
        )
        active["cleanup_verified"] = True
        atomic_json(self.path(data["id"]), data)

    async def advance(self, ident, action="prepare"):
        # Shield filesystem transactions, then perform journaled cleanup on cancellation.
        task = asyncio.create_task(self._advance(ident, action))
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                cancelled = True
                if task.done():
                    result = task.result()
                    break
        if cancelled:
            recovery = asyncio.create_task(self._advance(ident, "abort"))
            while not recovery.done():
                try:
                    await asyncio.shield(recovery)
                except asyncio.CancelledError:
                    pass
            recovery.result()
            raise asyncio.CancelledError()
        return result

    async def _advance(self, ident, action):
        self.app.config.require_development()
        if action not in {"prepare", "evaluate", "abort"}:
            raise ToolFailure("suite_invalid", "Use prepare, evaluate or abort.")
        if self.lock.locked():
            raise ToolFailure("suite_busy", "A suite operation is already running.")
        async with self.lock:
            with portalocker.Lock(str(self.path(ident).with_suffix(".lock")), mode="a", timeout=0):
                data = self.status(ident)
                if action == "abort":
                    await self.cleanup(data)
                    data["state"] = "aborted"
                    atomic_json(self.path(ident), data)
                    return data
                for ref, sha in data["references"].items():
                    if digest(self.app.artifacts.path(ref)) != sha:
                        raise ToolFailure("suite_changed", "Suite input changed.")
                if action == "prepare":
                    if data["state"] != "ready" or data.get("active"):
                        raise ToolFailure("suite_state", "Finish or recover the active trial first.")
                    active = dict(data["queue"][len(data["trials"])])
                    fixture = self.app.artifacts.get(active["case"]["fixture_id"])["data"]
                    checkpoint_id = fixture["checkpoint_id"]
                    if digest(self.app.artifacts.path(checkpoint_id)) != fixture["checkpoint_sha256"]:
                        raise ToolFailure("suite_changed", "Checkpoint changed after fixture registration.")
                    self.app.harness.load(checkpoint_id)
                    active.update(
                        checkpoint_id=checkpoint_id, shared_life_sha256=self.app.regressions._shared_hash()
                    )
                    data.update(state="preparing", active=active)
                    atomic_json(self.path(ident), data)
                    try:
                        active["save_backup"] = (await asyncio.to_thread(self.app.saves.backup))["backup_id"]
                        atomic_json(self.path(ident), data)
                        if data["candidate"]:
                            folder, _ = self.app.deployment.candidate(data["candidate"])
                            if digest(folder / "candidate.json") != data["candidate_sha256"]:
                                raise ToolFailure("suite_changed", "Deployment candidate changed.")
                            active["deployment"] = (
                                await asyncio.to_thread(self.app.deployment.prepare, data["candidate"])
                            )["receipt_id"]
                            atomic_json(self.path(ident), data)
                            await asyncio.to_thread(self.app.deployment.apply, active["deployment"])
                        if active["profile_id"]:
                            # Persist intent before any profile replacement; recovery handles partial applies.
                            active["profile_started"] = True
                            active["profile_owner"] = uuid.uuid4().hex
                            atomic_json(self.path(ident), data)
                            active["profile"] = await asyncio.to_thread(
                                self.app.mods.apply, active["profile_id"], active["profile_owner"]
                            )
                        launched = await self.app.harness.launch(checkpoint_id)
                        active["session_id"] = launched["session"]["session_id"]
                        data["state"] = "awaiting_world"
                        data["client_navigation"] = {
                            "mode": "observe_then_act",
                            "instructions": [
                                "Observe the owned game window. At PRESS ANY BUTTON, press Return once.",
                                "Wait through checking/loading screens. At Main Menu highlighted, press Return once.",
                                "At Load Game highlighted, press Return once; never select New Game or overwrite a save.",
                                "Observe the loaded world, then evaluate. Native readiness is independently verified.",
                            ],
                            "execution": "The AI client's computer-use adapter performs each step from a fresh screen observation; the server sends no blind menu keys.",
                        }
                    except BaseException:
                        data["state"] = "recovery_required"
                        atomic_json(self.path(ident), data)
                        await self.cleanup(data)
                        raise
                else:
                    if data["state"] != "awaiting_world":
                        raise ToolFailure("suite_state", "Prepare and load the checkpoint first.")
                    active = data["active"]
                    if self.app.sessions.receipt and self.app.sessions.receipt.get(
                        "session_id"
                    ) != active.get("session_id"):
                        raise ToolFailure(
                            "suite_state", "Trial session is no longer owned; abort to restore."
                        )
                    data["state"] = "evaluating"
                    atomic_json(self.path(ident), data)
                    case = active["case"]
                    try:
                        await self.app.harness.wait_ready(self.app.harness.load(active["checkpoint_id"]), 60)
                        if case.get("plan_id"):
                            result = await self.app.native_experiments.run(case["plan_id"], ident)
                            active.update(
                                outcome=result["summary"]["outcome"],
                                evidence={"experiment": result["artifact_id"]},
                                predicate=result["summary"].get("measurement"),
                            )
                        else:
                            before = await self.app.controls.world(0.5)
                            scenario = await self.app.scenarios.run(
                                active["checkpoint_id"], case["recipe"], stop_after=False
                            )
                            after = await self.app.controls.world(0.5)
                            native = self.app.artifacts.get(scenario["artifact_id"])["data"].get(
                                "native_trace", {}
                            )
                            checked = outcome(
                                case.get("predicate", "scenario"),
                                before["world"],
                                after["world"],
                                {**scenario, "native_trace": native},
                                case.get("role", 0),
                                case.get("item_id"),
                                case.get("minimum", 1),
                            )
                            if any(
                                not capture.get("cleanup", {}).get("sealed")
                                or capture["cleanup"].get("errors")
                                or not capture["world"].get("samples")
                                for capture in (before, after)
                            ):
                                checked = {"passed": None, "reason": "incomplete_world_capture"}
                            active.update(
                                evidence={
                                    "before": before["artifact_id"],
                                    "after": after["artifact_id"],
                                    "scenario": scenario["artifact_id"],
                                },
                                predicate=checked,
                                outcome="inconclusive"
                                if checked["passed"] is None
                                else "passed"
                                if checked["passed"]
                                else "failed",
                            )
                            active["diagnosis"] = self.app.diagnosis.analyze(scenario["artifact_id"])
                    except BaseException as exc:
                        active.update(
                            outcome="inconclusive",
                            error=getattr(exc, "code", "interrupted"),
                            partial_evidence=getattr(exc, "details", None),
                        )
                    finally:
                        try:
                            active["crash_reports"] = self.app.crashes.reports(active["session_id"])[
                                "reports"
                            ]
                        except Exception as exc:
                            active["crash_report_error"] = type(exc).__name__
                        atomic_json(self.path(ident), data)
                        await self.cleanup(data)
                    if not active["shared_life_unchanged"]:
                        active.update(outcome="inconclusive", error="shared_life_changed")
                    data["trials"].append(active)
                    data["active"] = None
                    data["state"] = "completed" if len(data["trials"]) == len(data["queue"]) else "ready"
                    data["summary"] = {
                        key: sum(t["outcome"] == key for t in data["trials"])
                        for key in ("passed", "failed", "inconclusive")
                    }
                atomic_json(self.path(ident), data)
                return data
