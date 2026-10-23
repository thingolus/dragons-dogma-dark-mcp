"""Differential behavior experiments and evidence-linked code candidates. MIT, Thingolus."""

import asyncio
from collections import Counter

from .common import ToolFailure, digest

IGNORED = {"id", "observed_ms", "age_ms", "time_ms", "thread", "samples", "started_ms", "stopped_ms"}


def changes(before, after, prefix="", output=None):
    output = [] if output is None else output
    if len(output) >= 200:
        return output
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            if key not in IGNORED:
                changes(before.get(key), after.get(key), prefix + "/" + key, output)
    elif isinstance(before, list) and isinstance(after, list):
        for index in range(min(max(len(before), len(after)), 256)):
            changes(
                before[index] if index < len(before) else None,
                after[index] if index < len(after) else None,
                prefix + "/" + str(index),
                output,
            )
    elif before != after:
        row = {"path": prefix, "before": before, "after": after}
        if type(before) in (int, float) and type(after) in (int, float):
            row["delta"] = after - before
        output.append(row)
    return output


def projection(doc):
    data, kind = doc["data"], doc["kind"]
    if kind in {"world_capture", "standalone_world"}:
        world = data["world"]
        party = []
        for p in world.get("party", []):
            if p is None:
                party.append(None)
                continue
            inventory = p.get("inventory", {})
            totals = Counter()
            if inventory.get("available"):
                for item in inventory.get("items", []):
                    totals[str(item["item_id"])] += item["quantity"]
            party.append(
                {k: p.get(k) for k in ("role", "vocation", "action", "position", "resources")}
                | {"inventory": dict(totals) if inventory.get("available") else None}
            )
        # Enemy IDs are capture-local: do not silently pair unrelated enemies by array position.
        enemies = world.get("enemies") or {}
        return {
            "stage": world.get("stage"),
            "party": party,
            "enemies_observed": len(enemies.get("rows", [])) if enemies.get("available") else None,
        }
    if kind == "function_trace":
        rows = data.get("native", {}).get("rows", [])
        return {
            "symbol": data["symbol"]["symbol"],
            "events": len(rows),
            "kinds": dict(Counter(r.get("kind", "unknown") for r in rows)),
            "observed_damage": sum(r.get("applied_damage", 0) for r in rows),
            "omitted": data.get("native", {}).get("omitted", 0),
        }
    if kind == "gameplay_scenario":
        return {
            "recipe": data["recipe"],
            "outcome": data["summary"]["outcome"],
            "steps": [
                {
                    "action": s["action"],
                    "role": s["role"],
                    "passed": s["passed"],
                    "effects": s.get("observation", {}).get("effects"),
                }
                for s in data["steps"]
            ],
        }
    raise ToolFailure("behavior_input", "Use world, function trace or scenario artifacts.")


def check_pair(before, after):
    if before["kind"] != after["kind"]:
        raise ToolFailure("behavior_input", "Compare the same capture kind.")
    for field in ("game_sha256", "runtime_sha256", "bridge_sha256", "backend", "evidence_class"):
        if before["provenance"].get(field) != after["provenance"].get(field):
            raise ToolFailure("behavior_input", "Capture identity differs: " + field)
    if before["created_at"] > after["created_at"]:
        raise ToolFailure("behavior_input", "Before capture must precede after capture.")


class Behaviors:
    def __init__(self, app):
        self.app = app

    def compare(self, before_id, after_id, feature, terms=None, ghidra_ids=None):
        artifacts = self.app.artifacts
        before, after = artifacts.get(before_id), artifacts.get(after_id)
        check_pair(before, after)
        first, second = projection(before), projection(after)
        if first.get("stage") != second.get("stage"):
            raise ToolFailure("behavior_input", "World stage changed; select comparable fixtures.")
        diff = changes(first, second)
        candidates = self.app.features.investigate(feature, terms)
        references = []
        if len(ghidra_ids or []) > 8:
            raise ToolFailure("invalid_parameters", "At most eight Ghidra exports.")
        for ident in ghidra_ids or []:
            doc = artifacts.get(ident)
            if doc["kind"] != "decompilation" or not doc["data"]["summary"].get("passed"):
                raise ToolFailure("behavior_input", "Use successful Ghidra exports.")
            if doc["provenance"].get("game_sha256") != before["provenance"].get("game_sha256"):
                raise ToolFailure("behavior_input", "Ghidra and capture executable identities differ.")
            export = doc["data"]["export"]
            references.append(
                {
                    "artifact_id": ident,
                    "sha256": digest(artifacts.path(ident)),
                    "symbol": doc["provenance"]["symbol"],
                    "references": export.get("references", []),
                    "references_truncated": export.get("references_truncated", False),
                }
            )
        session = before["provenance"].get("session_id")
        summary = {
            "feature": feature,
            "changed_fields": len(diff),
            "truncated": len(diff) >= 200,
            "same_session": bool(session and session == after["provenance"].get("session_id")),
        }
        data = {
            "summary": summary,
            "differences": diff,
            "captures": [{"id": i, "sha256": digest(artifacts.path(i))} for i in (before_id, after_id)],
            "code_candidates": candidates,
            "analyzed_references": references,
            "next_experiment": "Repeat from the same fixture with one changed action; retain a no-action control capture.",
            "limitations": "Differences and code references generate hypotheses, not causal attribution. Missing values remain unknown; enemy identities are not paired across captures. Static references may omit indirect calls.",
        }
        return {
            **artifacts.put("behavior_study", data, {"evidence_class": "derived_research"}),
            "summary": summary,
        }

    async def experiment(self, action, role=0, duration_ms=350):
        controls, sessions, artifacts = self.app.controls, self.app.sessions, self.app.artifacts
        sessions._admit()
        async with sessions.operation_lock:
            if (await sessions._request("control_status")).get("running"):
                raise ToolFailure("control_busy", "Release the existing control lease first.")
            provenance = dict(sessions.receipt or {})
            data, failure, claimed, observer = {"action": action, "role": role}, None, False, None

            async def world():
                nonlocal observer
                await sessions._request("world_start", duration_ms=600)
                observer = "world"
                await asyncio.sleep(0.6)
                result = await sessions._request("world_stop")
                if not result["cleanup"].get("sealed"):
                    raise ToolFailure("cleanup_failed", "World observer did not seal.")
                observer = None
                return artifacts.put(
                    "world_capture", result, {**provenance, "evidence_class": "native_callback_observation"}
                )

            try:
                claimed = True
                await controls._claim()
                data["before"] = await world()
                await sessions._request("trace_start", symbol="goblin_health_subtract", duration_ms=3000)
                observer = "trace"
                data["action_observation"] = await controls._action(action, role, duration_ms)
                data["native_trace"] = await sessions._request("trace_stop")
                if not data["native_trace"].get("sealed"):
                    raise ToolFailure("cleanup_failed", "Action observer did not seal.")
                observer = None
                data["after"] = await world()
                data["summary"] = {"outcome": "completed"}
            except BaseException as exc:
                failure = exc
                data["summary"] = {"outcome": "inconclusive", "error": getattr(exc, "code", "interrupted")}
            finally:
                try:
                    if observer:
                        result = await sessions._request(
                            "world_stop" if observer == "world" else "trace_stop"
                        )
                        sealed = result.get("cleanup", result).get("sealed")
                        if not sealed:
                            await sessions._stop()
                            raise ToolFailure(
                                "cleanup_failed", "Observer cleanup failed; owned game stopped."
                            )
                    if claimed:
                        data["release"] = await controls._release()
                except BaseException as exc:
                    await sessions._stop()
                    failure = exc
                    data["summary"] = {"outcome": "inconclusive", "error": "cleanup_failed"}
            receipt = artifacts.put(
                "behavior_experiment", data, {**provenance, "evidence_class": "native_experiment"}
            )
            if failure:
                failure.details = receipt
                raise failure
            return {**receipt, **data}
