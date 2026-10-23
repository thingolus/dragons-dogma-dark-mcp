"""Evidence-backed checkpoints and bounded gameplay acceptance. MIT, Thingolus."""

import asyncio
import math
import time

from .common import ToolFailure, digest
from .config import GAME_SHA256
from .ownership import game_lease, require_closed


def world_ready(row, previous=None, stage=None):
    """Copied menu flags alone are insufficient: require advancing actor callbacks."""
    actors = row.get("actors", [])
    healthy = (
        row.get("runtime") == 2
        and row.get("guard_transport") == 2
        and row.get("transport") == 2
        and row.get("native_offline") == 1
        and row.get("native_errors") == 0
        and row.get("faults") == 0
        and row.get("menu_gated") == 0
        and row.get("stage", 0) > 0
        and row.get("generation", 0) > 0
        and (stage is None or row["stage"] == stage)
        and len(actors) == 2
        and all(a.get("observed") == 1 for a in actors)
    )
    if not healthy or previous is None:
        return False
    return (
        all(row[k] == previous.get(k) for k in ("stage", "generation", "p1", "p2"))
        and len(previous.get("actors", [])) == 2
        and all(
            p.get("observed") == 1 and a["frames"] > p["frames"]
            for a, p in zip(actors, previous["actors"], strict=True)
        )
    )


class Harness:
    def __init__(self, config, artifacts, sessions, saves):
        self.config, self.artifacts, self.sessions, self.saves = config, artifacts, sessions, saves

    def checkpoint(self, backup_id, trace_id, label):
        self.config.require_development()
        if not 1 <= len(label.strip()) <= 120:
            raise ToolFailure("invalid_parameters", "Checkpoint label must contain 1–120 characters.")
        with game_lease(self.config.game):
            require_closed()
            self.saves.require_clear()
            roots = self.saves.roots()
            files = self.saves._manifest(backup_id, roots)
            if any(digest(roots[r["root"]] / r["name"]) != r["sha256"] for r in files):
                raise ToolFailure("save_changed", "Current saves differ from the supplied checkpoint backup.")
            trace = self.artifacts.get(trace_id)
            rows = trace["data"].get("samples", [])
            provenance = trace["provenance"]
            if (
                trace["kind"] != "runtime_trace"
                or provenance.get("evidence_class") not in {"native_observation", "synthetic_native"}
                or provenance.get("game_sha256") != GAME_SHA256
                or not provenance.get("session_id")
                or trace["data"].get("summary", {}).get("outcome") != "completed"
                or len(rows) < 3
                or not all(
                    world_ready(b, a, rows[0].get("stage")) for a, b in zip(rows, rows[1:], strict=False)
                )
            ):
                raise ToolFailure(
                    "checkpoint_unverified", "Use a completed, advancing loaded-world native trace."
                )
            data = {
                "label": label,
                "backup_id": backup_id,
                "save_files": files,
                "trace_id": trace_id,
                "trace_sha256": digest(self.artifacts.path(trace_id)),
                "stage": rows[-1]["stage"],
                "position": rows[-1]["actors"][0]["position"],
                "position_tolerance": 100.0,
                "summary": {"label": label, "stage": rows[-1]["stage"]},
                "limitations": [
                    "Stage and position identify a fixture, not full quest state.",
                    "Save association is hash-checked at registration; no claim of native save provenance.",
                    "Shared-life reserve is outside the save backup.",
                ],
            }
            return self.artifacts.put("gameplay_checkpoint", data, provenance)

    def load(self, checkpoint_id):
        doc = self.artifacts.get(checkpoint_id)
        if doc["kind"] != "gameplay_checkpoint":
            raise ToolFailure("checkpoint_invalid", "Expected a gameplay checkpoint artifact.")
        data = doc["data"]
        if digest(self.artifacts.path(data["trace_id"])) != data["trace_sha256"]:
            raise ToolFailure("evidence_changed", "Checkpoint evidence changed.")
        files = self.saves._manifest(data["backup_id"], self.saves.roots())
        if files != data["save_files"]:
            raise ToolFailure("evidence_changed", "Checkpoint save inventory changed.")
        return data

    async def launch(self, checkpoint_id):
        task = asyncio.create_task(self._launch(checkpoint_id))
        cancelled = None
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError as exc:
                cancelled = exc
                if task.done():
                    result = task.result()
                    break
        if cancelled:
            # Restore threads must finish before process/lease cleanup can run.
            await self.sessions.stop()
            cancelled.details = result
            raise cancelled
        return result

    async def _launch(self, checkpoint_id):
        self.config.require_development()
        checkpoint = self.load(checkpoint_id)
        restored = await asyncio.to_thread(self.saves.restore, checkpoint["backup_id"])
        try:
            result = await self.sessions.start()
        except BaseException as exc:
            exc.details = {"save_restore": restored}
            raise
        return {
            **result,
            "checkpoint_id": checkpoint_id,
            "save_restore": restored,
            "next_action": "Use observed native menus to Load Game, then run_gameplay_harness. No blind menu input is sent.",
        }

    async def wait_ready(self, checkpoint, timeout):
        self.sessions._admit()
        if not 1 <= timeout <= 120:
            raise ToolFailure("invalid_parameters", "Readiness timeout must be 1–120 seconds.")
        async with self.sessions.operation_lock:
            previous, consecutive, rows = None, 0, []
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                row = await self.sessions._snapshot()
                matches = world_ready(row, previous, checkpoint["stage"])
                if matches:
                    position = row["actors"][0]["position"]
                    matches = math.dist(position, checkpoint["position"]) <= checkpoint["position_tolerance"]
                consecutive = consecutive + 1 if matches else 0
                rows.append(row)
                if consecutive >= 3:
                    return rows[-4:]
                previous = row
                await asyncio.sleep(0.25)
            failure = ToolFailure(
                "readiness_timeout", "No stable advancing checkpoint world observed before deadline."
            )
            failure.details = {"last_samples": rows[-4:]}
            raise failure

    async def run(self, checkpoint_id, recipe="observe_idle", seconds=2.0, timeout=30, stop_after=True):
        self.config.require_development()
        if recipe not in {"observe_idle", "neutral_input"} or not 0.5 <= seconds <= 30:
            raise ToolFailure("invalid_parameters", "Use observe_idle/neutral_input for 0.5–30 seconds.")
        checkpoint = self.load(checkpoint_id)
        provenance = dict(self.sessions.receipt or {})
        data = {
            "checkpoint_id": checkpoint_id,
            "checkpoint_sha256": digest(self.artifacts.path(checkpoint_id)),
            "recipe": recipe,
            "summary": {"outcome": "inconclusive"},
        }
        failure = None
        try:
            data["readiness"] = await self.wait_ready(checkpoint, timeout)
            data["capture"] = await self.sessions.capture(seconds, 250, recipe == "neutral_input")
            trace = self.artifacts.get(data["capture"]["artifact_id"])
            rows = trace["data"]["samples"]
            good = len(rows) >= 2 and all(
                world_ready(b, a, checkpoint["stage"]) for a, b in zip(rows, rows[1:], strict=False)
            )
            data["summary"] = {
                "outcome": "passed" if good else "failed",
                "sample_count": len(rows),
                "predicate": "advancing callbacks, expected stage, offline guard, no faults",
            }
        except BaseException as exc:
            failure = exc
            data["error"] = {
                "code": getattr(
                    exc, "code", "cancelled" if isinstance(exc, asyncio.CancelledError) else "harness_failed"
                ),
                "details": getattr(exc, "details", None),
            }
        finally:
            if stop_after:
                try:
                    data["cleanup"] = await self.sessions.stop()
                except BaseException as exc:
                    failure = exc
                    data["summary"]["outcome"] = "inconclusive"
                    data["cleanup"] = {"verified": False, "error": getattr(exc, "code", "cleanup_failed")}
        receipt = self.artifacts.put(
            "gameplay_harness", data, {**provenance, "evidence_class": "native_harness"}
        )
        if failure:
            failure.artifact = receipt
            failure.details = receipt
            raise failure
        return {
            **receipt,
            **data["summary"],
            "cleanup": data.get("cleanup"),
            "limitations": "Only the named predicate was tested; no combat or physical-controller acceptance.",
        }
