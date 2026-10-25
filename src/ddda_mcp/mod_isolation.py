"""Durable dependency-aware delta debugging through restored native suites. MIT, Thingolus."""

import asyncio
import uuid

import portalocker

from .common import ToolFailure, atomic_json, digest, identifier, read_json


def partitions(mods, granularity):
    """Subsets and complements support interacting mods, not just single culprits."""
    n = min(len(mods), granularity)
    if not n:
        return []
    chunks = [mods[i * len(mods) // n : (i + 1) * len(mods) // n] for i in range(n)]
    result = []
    for group in chunks + [[m for m in mods if m not in group] for group in chunks]:
        if group and group != mods and group not in result:
            result.append(group)
    return result


def verdict(trials, criterion):
    if not trials or any(not t.get("cleanup_verified") or not t.get("shared_life_unchanged") for t in trials):
        return "inconclusive"
    if criterion == "crash":
        rows = []
        for t in trials:
            fatal = any(r.get("kind") == "native_crash" for r in t.get("crash_reports", []))
            rows.append(
                "failed"
                if fatal
                else "passed"
                if t.get("outcome") in {"passed", "failed"}
                else "inconclusive"
            )
    else:
        rows = [t.get("outcome", "inconclusive") for t in trials]
    return rows[0] if len(set(rows)) == 1 and rows[0] in {"passed", "failed"} else "inconclusive"


class ModIsolation:
    def __init__(self, app):
        self.app = app
        self.root = app.config.artifacts / "mod-isolations"
        self.lock = asyncio.Lock()

    def path(self, ident):
        return self.root / (identifier(ident) + ".json")

    def status(self, ident):
        return read_json(self.path(ident))

    def create(self, label, mod_ids, case, repeats=2, criterion="test_failure", max_suites=64):
        self.app.config.require_development()
        if (
            not label.strip()
            or len(label) > 120
            or not 2 <= len(mod_ids) <= 16
            or len(set(mod_ids)) != len(mod_ids)
            or repeats not in (2, 3)
            or criterion not in {"test_failure", "crash"}
            or not 4 <= max_suites <= 64
        ):
            raise ToolFailure(
                "isolation_invalid", "Use 2–16 distinct mods, 2–3 repeats, and a bounded suite budget."
            )
        dependencies = {}
        refs = {}
        for ident in mod_ids:
            doc = self.app.artifacts.get(ident)
            if doc["kind"] != "mod_definition":
                raise ToolFailure("mod_invalid", "Select registered mods.")
            dependencies[ident] = doc["data"]["requires"]
            if set(dependencies[ident]) - set(mod_ids):
                raise ToolFailure("dependency_missing", "Include every required mod in the candidate set.")
            refs[ident] = digest(self.app.artifacts.path(ident))
        # Validate the fixture/plan and full composition before creating state.
        profile = self.app.mods.compose(label, mod_ids)
        if not profile["summary"]["compatible"]:
            raise ToolFailure("mod_conflict", "Resolve static profile conflicts before native isolation.")
        validation = self.app.suites.create(label, [case], [profile["artifact_id"]], repeats)
        refs.update(validation["references"])
        ident = uuid.uuid4().hex
        data = {
            "id": ident,
            "label": label,
            "state": "ready",
            "phase": "baseline",
            "all_mods": mod_ids,
            "best": mod_ids,
            "dependencies": dependencies,
            "references": refs,
            "full_suite_id": validation["id"],
            "case": case,
            "repeats": repeats,
            "criterion": criterion,
            "max_suites": max_suites,
            "granularity": 2,
            "pending": [[]],
            "tested": [],
            "trials": [],
            "active": None,
            "scope": "Minimal reproducing subset relative to the original installation and selected fixture, not proof of root cause. Manual observed Load Game is required for each trial.",
        }
        atomic_json(self.path(ident), data)
        return data

    def _accept(self, data, subset, result, evidence):
        data["tested"].append(subset)
        data["trials"].append({"mods": subset, "verdict": result, **evidence})
        data["active"] = None
        if data["phase"] == "baseline":
            if result != "passed":
                data.update(state="inconclusive", reason="baseline_does_not_pass")
                return
            data.update(phase="full", pending=[data["all_mods"]])
        elif data["phase"] == "full":
            if result != "failed":
                data.update(state="inconclusive", reason="full_set_not_reproducibly_failing")
                return
            data.update(phase="reduce", pending=partitions(data["best"], 2))
        elif result == "failed":
            data.update(best=subset, granularity=2, pending=partitions(subset, 2))
        if len(data["trials"]) >= data["max_suites"]:
            data.update(state="budget_exhausted", reason="suite_budget_exhausted")
            return
        if data["phase"] == "reduce":
            data["pending"] = [s for s in data["pending"] if s not in data["tested"]]
            while not data["pending"]:
                if data["granularity"] >= len(data["best"]):
                    # Unknown subset outcomes prevent a claim of 1-minimality.
                    unknown = any(
                        t["verdict"] == "inconclusive" and set(t["mods"]) < set(data["best"])
                        for t in data["trials"]
                    )
                    data.update(
                        state="inconclusive" if unknown else "completed",
                        reason="subset_evidence_incomplete" if unknown else "one_minimal_reproducing_set",
                    )
                    return
                data["granularity"] = min(len(data["best"]), data["granularity"] * 2)
                data["pending"] = [
                    s for s in partitions(data["best"], data["granularity"]) if s not in data["tested"]
                ]
        data["state"] = "ready"

    async def advance(self, ident, action):
        self.app.config.require_development()
        if action not in {"prepare", "evaluate", "abort"}:
            raise ToolFailure("isolation_invalid", "Use prepare, evaluate or abort.")
        async with self.lock:
            with portalocker.Lock(str(self.path(ident).with_suffix(".lock")), mode="a", timeout=0):
                data = self.status(ident)
                if action == "abort":
                    if data["active"]:
                        await self.app.suites.advance(data["active"]["suite_id"], "abort")
                    data["state"] = "aborted"
                    atomic_json(self.path(ident), data)
                    return data
                for ref, sha in data["references"].items():
                    if digest(self.app.artifacts.path(ref)) != sha:
                        raise ToolFailure("evidence_changed", "An isolation input changed.")
                # The suite may have committed its result before a host interruption.
                # Consume that durable result exactly once, without rerunning a trial.
                if data["active"]:
                    previous = self.app.suites.status(data["active"]["suite_id"])
                    if previous["state"] == "completed":
                        self._accept(
                            data,
                            data["active"]["mods"],
                            verdict(previous["trials"], data["criterion"]),
                            {
                                "suite_id": previous["id"],
                                "suite_sha256": digest(self.app.suites.path(previous["id"])),
                            },
                        )
                        atomic_json(self.path(ident), data)
                        return data
                if data["state"] not in {"ready", "awaiting_world"}:
                    raise ToolFailure("isolation_state", "This isolation has ended or requires recovery.")
                if not data["active"]:
                    if action != "prepare":
                        raise ToolFailure("isolation_state", "Prepare a trial first.")
                    while data["pending"]:
                        subset = data["pending"].pop(0)
                        if subset in data["tested"]:
                            continue
                        if any(set(data["dependencies"][m]) - set(subset) for m in subset):
                            self._accept(data, subset, "inconclusive", {"reason": "dependency_not_present"})
                            if data["state"] != "ready":
                                break
                            continue
                        profile = self.app.mods.compose(data["label"], subset) if subset else None
                        if profile and not profile["summary"]["compatible"]:
                            self._accept(data, subset, "inconclusive", {"reason": "static_conflict"})
                            continue
                        suite = (
                            self.app.suites.status(data["full_suite_id"])
                            if subset == data["all_mods"]
                            else self.app.suites.create(
                                data["label"],
                                [data["case"]],
                                [profile["artifact_id"] if profile else None],
                                data["repeats"],
                            )
                        )
                        data["active"] = {"suite_id": suite["id"], "mods": subset}
                        atomic_json(self.path(ident), data)
                        break
                    if not data["active"]:
                        atomic_json(self.path(ident), data)
                        return data
                active = data["active"]
                try:
                    suite = await self.app.suites.advance(active["suite_id"], action)
                except BaseException as exc:
                    data["state"] = self.app.suites.status(active["suite_id"])["state"]
                    data["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
                    atomic_json(self.path(ident), data)
                    raise
                if suite["state"] == "completed":
                    result = verdict(suite["trials"], data["criterion"])
                    self._accept(
                        data,
                        active["mods"],
                        result,
                        {"suite_id": suite["id"], "suite_sha256": digest(self.app.suites.path(suite["id"]))},
                    )
                else:
                    data["state"] = suite["state"]
                atomic_json(self.path(ident), data)
                return data


def register_tools(mcp, app):
    from typing import Annotated, Literal

    from pydantic import Field

    from .server import Read, Result, Write
    from .workbench import SuiteCase

    @mcp.tool(annotations=Write)
    async def create_mod_isolation(
        label: str,
        mod_ids: Annotated[list[str], Field(min_length=2, max_length=16)],
        case: SuiteCase,
        repeats: Literal[2, 3] = 2,
        criterion: Literal["test_failure", "crash"] = "test_failure",
        max_suites: Annotated[int, Field(ge=4, le=64)] = 64,
    ) -> Result:
        """Create dependency-aware mod delta debugging, with passing baseline, reproduced failure and restored repeated native trials."""
        return await app.invoke(
            "create_mod_isolation",
            app.mod_isolation.create,
            label,
            mod_ids,
            case.model_dump(),
            repeats,
            criterion,
            max_suites,
        )

    @mcp.tool(annotations=Write)
    async def advance_mod_isolation(
        isolation_id: str, action: Literal["prepare", "evaluate", "abort"]
    ) -> Result:
        """Advance one restored trial; observe and load the game between prepare and evaluate. Unknown outcomes never establish a culprit."""
        return await app.invoke(
            "advance_mod_isolation",
            lambda: app.jobs.submit("mod_isolation", lambda: app.mod_isolation.advance(isolation_id, action)),
        )

    @mcp.tool(annotations=Read)
    async def mod_isolation_status(isolation_id: str) -> Result:
        """Read the best reproducing subset, repeated evidence, remaining trials and cleanup state."""
        return await app.invoke("mod_isolation_status", app.mod_isolation.status, isolation_id)
