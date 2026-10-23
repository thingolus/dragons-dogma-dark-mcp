"""Bounded reproducible gameplay predicates. MIT, Thingolus."""

import asyncio
import re

from .common import ToolFailure, digest

SCENARIOS = {
    "movement_pair": {
        "steps": [("forward", 0, "moved"), ("right", 1, "moved")],
        "scope": "Both assigned actors move at least one game unit.",
    },
    "attack_pair": {
        "steps": [("light_attack", 0, "action_transition"), ("light_attack", 1, "action_transition")],
        "scope": "Actor action transitions after light attack; no damage attribution.",
    },
    "jump_pair": {
        "steps": [("jump", 0, "action_transition"), ("jump", 1, "action_transition")],
        "scope": "Actor action transitions after jump; not a landing or height test.",
    },
    "menu_roundtrip": {
        "steps": [("menu", 0, "menu_open"), ("cancel", 0, "menu_closed")],
        "scope": "Copied menu gate opens and closes.",
    },
    "interaction_menu": {
        "steps": [("interact", 0, "menu_open"), ("cancel", 0, "menu_closed")],
        "scope": "Fixture must face an interactable opening a menu; no quest-completion assertion.",
    },
}


def evaluate_step(result, predicate):
    effects, rows = result["effects"], result["samples"]
    if not effects["provider_neutral"]:
        return None
    if predicate == "moved":
        return effects["callbacks_advanced"] and effects["distance"] >= 1.0
    if predicate == "action_transition":
        return effects["callbacks_advanced"] and effects["action_changed"]
    if predicate == "menu_open":
        return any(row["menu_gated"] != 0 for row in rows)
    if predicate == "menu_closed":
        return rows[-1]["menu_gated"] == 0
    raise ToolFailure("predicate_unknown", "Scenario contains an unsupported predicate.")


class Scenarios:
    def __init__(self, harness, controls, artifacts):
        self.harness, self.controls, self.artifacts = harness, controls, artifacts

    def catalog(self):
        return {
            "scenarios": SCENARIOS,
            "duration_limit_seconds": 30,
            "cleanup": "Release the provider, verify copied state, stop the owned game by default.",
            "semantics": "Only explicit predicates count; unavailable observations are inconclusive.",
        }

    async def run(self, checkpoint_id, recipe, seconds=2, timeout=30, stop_after=True):
        if recipe in {"observe_idle", "neutral_input"}:
            return await self.harness.run(checkpoint_id, recipe, seconds, timeout, stop_after)
        if recipe not in SCENARIOS:
            raise ToolFailure("scenario_unknown", "Select a reviewed gameplay scenario.")
        checkpoint = self.harness.load(checkpoint_id)
        sessions = self.harness.sessions
        sessions._admit()
        async with sessions.operation_lock:
            if (await sessions._request("control_status")).get("running"):
                raise ToolFailure("control_busy", "Release the existing lease before running a scenario.")
        provenance = dict(sessions.receipt or {})
        data = {
            "checkpoint_id": checkpoint_id,
            "checkpoint_sha256": digest(self.artifacts.path(checkpoint_id)),
            "recipe": recipe,
            "steps": [],
            "scope": SCENARIOS[recipe]["scope"],
            "summary": {"outcome": "inconclusive"},
        }
        failure = None
        claimed = False
        trace_started = False
        locked = False
        preserve_session = False
        try:
            data["readiness"] = await self.harness.wait_ready(checkpoint, timeout)
            sessions._admit()
            await sessions.operation_lock.acquire()
            locked = True
            if (await sessions._request("control_status")).get("running"):
                preserve_session = True
                raise ToolFailure("control_busy", "Another operation acquired gameplay control.")
            claimed = True
            async with asyncio.timeout(30):
                data["assignment"] = await self.controls._claim()
                symbol = "goblin_health_subtract" if recipe == "attack_pair" else "native_stamina_apply"
                await sessions._request("trace_start", symbol=symbol, duration_ms=25000)
                trace_started = True
                for index, (action, role, predicate) in enumerate(SCENARIOS[recipe]["steps"]):
                    step = {
                        "index": index,
                        "action": action,
                        "role": role,
                        "predicate": predicate,
                        "passed": None,
                    }
                    data["steps"].append(step)
                    step["observation"] = await self.controls._action(action, role, 350)
                    step["passed"] = evaluate_step(step["observation"], predicate)
                    if step["passed"] is not True:
                        break
                verdicts = [step["passed"] for step in data["steps"]]
                data["summary"]["outcome"] = (
                    "inconclusive" if None in verdicts else "passed" if all(verdicts) else "failed"
                )
        except BaseException as exc:
            failure = exc
            data["error"] = {
                "code": getattr(
                    exc,
                    "code",
                    "cancelled" if isinstance(exc, asyncio.CancelledError) else "scenario_interrupted",
                )
            }
        finally:
            try:
                if trace_started:
                    data["native_trace"] = await sessions._request("trace_stop")
                    if not data["native_trace"].get("sealed"):
                        await sessions._stop()
                        raise ToolFailure(
                            "hook_cleanup_failed", "Scenario observer failed to seal; owned game stopped."
                        )
                if claimed:
                    data["release"] = await self.controls._release()
                if stop_after and not preserve_session:
                    data["cleanup"] = await (sessions._stop() if locked else sessions.stop())
            except BaseException as exc:
                data["summary"]["outcome"] = "inconclusive"
                data["cleanup"] = {"verified": False, "error": getattr(exc, "code", "cleanup_failed")}
                failure = exc
            finally:
                if locked:
                    sessions.operation_lock.release()
        # Read only this broker's private log, never arbitrary client-selected paths.
        session_id = provenance.get("session_id", "")
        if re.fullmatch(r"[0-9a-f]{32}", session_id):
            log = self.harness.config.artifacts / "sessions" / (session_id + ".log")
            if log.is_file():
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 8192))
                    tail = stream.read(8192).decode("utf-8", errors="replace")
                data["broker_log"] = {
                    "sha256": digest(log),
                    "tail": re.sub(r"0x[0-9a-fA-F]{6,16}", "<address>", tail),
                }
        receipt = self.artifacts.put(
            "gameplay_scenario", data, {**provenance, "evidence_class": "native_harness"}
        )
        if failure:
            failure.details = receipt
            raise failure
        return {**receipt, **data["summary"], "scope": data["scope"], "release": data.get("release")}


class Diagnosis:
    def __init__(self, source, artifacts):
        self.source, self.artifacts = source, artifacts

    def analyze(self, artifact_id, related_ids=None):
        related_ids = related_ids or []
        if len(related_ids) > 8:
            raise ToolFailure("invalid_parameters", "Use at most eight related captures.")
        doc = self.artifacts.get(artifact_id)
        if doc["kind"] not in {"gameplay_scenario", "gameplay_harness"}:
            raise ToolFailure("diagnosis_input", "Select a scenario or harness result.")
        data, first = doc["data"], None
        for step in data.get("steps", []):
            if step["passed"] is not True:
                first = {k: step[k] for k in ("index", "action", "role", "predicate", "passed")}
                first["effects"] = step.get("observation", {}).get("effects")
                break
        links, events = [], []
        for ident in [artifact_id, *related_ids]:
            other = self.artifacts.get(ident)
            same_session = other["provenance"].get("session_id") is not None and other["provenance"].get(
                "session_id"
            ) == doc["provenance"].get("session_id")
            links.append(
                {
                    "artifact_id": ident,
                    "sha256": digest(self.artifacts.path(ident)),
                    "kind": other["kind"],
                    "same_session": same_session,
                    "evidence_class": other["provenance"].get("evidence_class"),
                }
            )
            if same_session and other["kind"] == "function_trace":
                events.append(
                    {
                        "artifact_id": ident,
                        "summary": other["data"].get("summary"),
                        "interpretation": "Same-session events; temporal overlap is not proof of causation.",
                    }
                )
        paths = ["src/session.cpp", "src/runtime.cpp", "research/strider_dodge_trial.js"]
        sources = [self.source.reference(p) for p in paths if p in self.source.tree()]
        diagnosis = {
            "summary": {
                "outcome": data.get("summary", {}).get("outcome", "inconclusive"),
                "first_divergence_step": first["index"] if first else None,
            },
            "first_observed_divergence": first,
            "error": data.get("error"),
            "cleanup": data.get("cleanup"),
            "release": data.get("release"),
            "broker_log": data.get("broker_log"),
            "evidence": links,
            "native_events": events,
            "scenario_native_trace": data.get("native_trace"),
            "source_references": sources,
            "crash_evidence": "No dump was collected. A broker error or process exit alone does not identify a crash cause.",
            "limitations": "First observed predicate divergence, not root-cause proof. Separate sessions and static Ghidra artifacts are references, not a unified execution clock.",
        }
        return self.artifacts.put(
            "scenario_diagnosis", diagnosis, {**doc["provenance"], "evidence_class": "derived_diagnosis"}
        )
