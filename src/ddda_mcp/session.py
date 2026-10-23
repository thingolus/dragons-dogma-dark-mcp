"""Owned live sessions and bounded, reviewed recipes. No legacy mailbox writes."""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from .artifacts import Artifacts
from .common import ToolFailure, read_json, utc_now
from .config import Config
from .copied_groups import GROUPS
from .diagnostics import decode
from .ownership import game_processes, stop_owned
from .recipes import MOVEMENT


class Sessions:
    def __init__(self, config: Config, artifacts: Artifacts, config_path: Path | None = None):
        self.config, self.artifacts, self.config_path = config, artifacts, config_path
        self.process = None
        self.receipt = None
        self.io_lock = asyncio.Lock()
        self.operation_lock = asyncio.Lock()
        self.heartbeat_task = None
        self.error_stream = None
        self.unusable = False
        self.title_start_used = False
        self.movement_used = set()

    def status(self) -> dict:
        alive = self.process is not None and self.process.returncode is None
        return {
            "owned_session": self.receipt if alive else None,
            "running": alive,
            "unusable": self.unusable,
            "external_game_processes": [
                p
                for p in game_processes()
                if not alive or not self.receipt or p["pid"] != self.receipt.get("pid")
            ],
            "operation_busy": self.operation_lock.locked(),
            "policy": "No attachment to existing games; legacy research mailboxes are never written.",
        }

    def _admit(self):
        self.config.require_development()
        if self.operation_lock.locked():
            raise ToolFailure("session_busy", "Another live operation is in progress.")

    async def start(self, backend="coop", bridge_id=None) -> dict:
        self._admit()
        if backend not in {"coop", "standalone"} or (backend == "standalone" and not bridge_id):
            raise ToolFailure("invalid_parameters", "Standalone launch requires a reviewed bridge build ID.")
        async with self.operation_lock:
            if self.process is not None and self.process.returncode is None:
                raise ToolFailure("session_busy", "This server already owns a session.")
            if game_processes():
                raise ToolFailure("session_busy", "An existing DDDA process belongs to another session.")
            session_id = uuid.uuid4().hex
            folder = self.config.artifacts / "sessions"
            folder.mkdir(parents=True, exist_ok=True)
            self.receipt = {"session_id": session_id, "state": "starting"}
            args = [
                sys.executable,
                "-m",
                "ddda_mcp.native_worker",
                "--project",
                str(self.config.root),
                "--session-id",
                session_id,
                "--backend",
                backend,
            ]
            if bridge_id:
                args.extend(["--bridge-id", bridge_id])
            if self.config_path is not None:
                args.extend(["--config", str(self.config_path.resolve())])
            self.error_stream = (folder / f"{session_id}.log").open("wb")
            self.process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=self.error_stream,
                limit=65536,
            )
            self.unusable = False
            self.title_start_used = False
            self.movement_used.clear()
            try:
                line = await asyncio.wait_for(self.process.stdout.readline(), timeout=30)
                result = json.loads(line)
                if not result.get("ready"):
                    raise ToolFailure(
                        "session_start_failed", result.get("error", "Worker did not become ready.")
                    )
                self.receipt = {k: v for k, v in result.items() if k != "ready"}
                self.heartbeat_task = asyncio.create_task(self._heartbeat())
                return {
                    "session": self.receipt,
                    "warning": "Owned game is stopped without saving when the server exits.",
                }
            except BaseException:
                await self._stop()
                raise

    async def _heartbeat(self):
        try:
            while True:
                await asyncio.sleep(5)
                await self._request("heartbeat")
        except asyncio.CancelledError:
            return
        except Exception:
            self.unusable = True
            await self._stop()

    async def _request(self, operation: str, **parameters):
        if self.process is None or self.process.returncode is not None or self.unusable:
            raise ToolFailure("session_unavailable", "Start an owned development session first.")
        async with self.io_lock:
            request_id = uuid.uuid4().hex
            command = json.dumps({"id": request_id, "op": operation, **parameters}) + "\n"
            try:
                self.process.stdin.write(command.encode())
                await self.process.stdin.drain()
                line = await asyncio.wait_for(
                    self.process.stdout.readline(), self.config.settings.limits.read_timeout_seconds
                )
                result = json.loads(line)
                if result.get("id") != request_id:
                    self.unusable = True
                    raise ToolFailure("outcome_unknown", "Broker response did not match the request.")
                if not result.get("ok"):
                    raise ToolFailure("native_refused", result.get("error", "Native operation refused."))
                return result["value"]
            except (TimeoutError, ValueError, BrokenPipeError, ConnectionError) as exc:
                self.unusable = True
                raise ToolFailure(
                    "outcome_unknown",
                    "Broker response unavailable; session disabled. Stop it before retrying.",
                ) from exc

    async def _snapshot(self) -> dict:
        if (self.receipt or {}).get("backend") == "standalone":
            raise ToolFailure(
                "backend_capability", "Use inspect_standalone_world for the standalone backend."
            )
        result = await self._request("snapshot")
        if result.get("size") != 132 or result.get("version") != 2:
            self.unusable = True
            raise ToolFailure("abi_mismatch", "CoopStatus requires size=132/version=2.")
        if (
            result.get("runtime") != 2
            or result.get("guard_transport") != 2
            or result.get("transport") not in {0, 2}
            or result.get("native_offline") not in {0, 1}
            or result.get("native_errors") != 0
        ):
            self.unusable = True
            raise ToolFailure("offline_guard_failed", "Runtime/offline guard is not admitted.")
        return {
            **result,
            "native_state": "ready" if result["native_offline"] == 1 else "pending_game_initialization",
            "input_admitted": result["native_offline"] == 1
            and result.get("developer_input") == 1
            and result.get("faults") == 0,
            "captured_at": utc_now(),
            "evidence_class": "native_observation",
            "freshness": "Copied snapshot at capture; actor sample ages are not supplied by this ABI.",
        }

    async def snapshot(self, group: str = "runtime") -> dict:
        self._admit()
        async with self.operation_lock:
            status = await self._snapshot()
            if group == "runtime":
                return status
            if group in GROUPS:
                result = decode(group, {"words": await self._request("copied_group", group=group)})
                result["summary"] = {"adapter": group, "decoder_version": result["decoder_version"]}
                receipt = self.artifacts.put(
                    "diagnostic_capture",
                    result,
                    {
                        "session": self.receipt,
                        "source_commit": self.config.settings.coop_source_commit,
                        "evidence_class": "native_observation",
                    },
                )
                return {"runtime": status, "diagnostic": result["decoded"], **receipt}
            if group == "performance":
                result = decode("performance", await self._request("performance"))
                result["summary"] = {"adapter": "performance", "decoder_version": result["decoder_version"]}
                receipt = self.artifacts.put(
                    "diagnostic_capture",
                    result,
                    {
                        "session": self.receipt,
                        "source_commit": self.config.settings.coop_source_commit,
                        "evidence_class": "native_observation",
                    },
                )
                return {
                    "runtime": status,
                    "performance": {
                        **result["payload"],
                        "coverage": "Existing callback-span instrumentation only; reading does not begin or seal collection.",
                    },
                    **receipt,
                }
            if group == "death_refusals":
                if status.get("developer_input") != 1 or status.get("faults") != 0:
                    raise ToolFailure(
                        "diagnostic_admission_failed", "Diagnostic needs a healthy developer runtime."
                    )
                words = await self._request("death_refusals")
                result = decode("death_refusals", {"words": words})
                decoded = result["decoded"]
                words = result["payload"]["words"]
                receipt = self.artifacts.put(
                    "death_diagnostic",
                    {
                        "summary": decoded["summary"],
                        "words": words,
                        "decoded": decoded,
                        "decoder_version": result["decoder_version"],
                        "payload_sha256": result["payload_sha256"],
                    },
                    {
                        "session": self.receipt,
                        "source_commit": self.config.settings.coop_source_commit,
                        "evidence_class": "native_observation",
                    },
                )
                return {"runtime": status, "death_refusals": decoded, **receipt}
            raise ToolFailure("invalid_parameters", "group must be runtime, performance or death_refusals.")

    async def dismiss_title(self) -> dict:
        """One fixed Start press, with no A/confirm/navigation or save loading."""
        self._admit()
        async with self.operation_lock:
            before = await self._snapshot()
            if self.title_start_used:
                raise ToolFailure("already_attempted", "Title Start is allowed once per owned session.")
            if (
                before.get("developer_input") != 1
                or before.get("stage") != 0
                or before.get("generation") != 0
                or any(a["observed"] for a in before.get("actors", []))
            ):
                raise ToolFailure(
                    "not_title_state", "Title Start requires developer input and no loaded world/actors."
                )
            self.title_start_used = True
            try:
                await self._request("title_start", pressed=True)
                await asyncio.sleep(0.25)
            finally:
                try:
                    await self._request("title_start", pressed=False)
                except Exception as exc:
                    self.unusable = True
                    await self._stop()
                    raise ToolFailure(
                        "cleanup_failed", "Title input cleanup failed; owned session stopped."
                    ) from exc
            after = await self._snapshot()
            return self.artifacts.put(
                "title_start",
                {"summary": {"input_released": True, "press_ms": 250}, "before": before, "after": after},
                {**(self.receipt or {}), "recipe": "dismiss_title", "evidence_class": "synthetic_native"},
            )

    async def movement(self, recipe: str) -> dict:
        self._admit()
        if recipe not in MOVEMENT:
            raise ToolFailure("invalid_parameters", "Unknown reviewed movement recipe.")
        async with self.operation_lock:
            if recipe in self.movement_used:
                raise ToolFailure(
                    "already_attempted", "Each movement recipe is allowed once per owned session."
                )
            before = await self._snapshot()
            actor = MOVEMENT[recipe]["actor"]
            slot = before.get("p1" if actor == 0 else "p2", -1)
            actors = before.get("actors", [])
            if (
                not before["input_admitted"]
                or before.get("transport") != 2
                or before.get("stage", 0) == 0
                or before.get("generation", 0) <= 0
                or before.get("menu_gated") != 0
                or before.get("physical_mask") != 0
                or not 0 <= slot <= 3
                or len(actors) != 2
                or actors[actor]["observed"] != 1
                or before.get("p1") == before.get("p2")
            ):
                raise ToolFailure(
                    "input_admission_failed",
                    "Movement needs an observed actor and assigned pad in an offline loaded world without menus or physical controllers.",
                )
            self.movement_used.add(recipe)
            samples, failure, released = [before], None, False
            provenance = {
                **(self.receipt or {}),
                "recipe": recipe,
                "recipe_version": 1,
                "source_commit": self.config.settings.coop_source_commit,
                "evidence_class": "synthetic_native",
            }
            started = time.monotonic()

            def check_world(current):
                if any(current.get(key) != before.get(key) for key in ("stage", "generation", "p1", "p2")):
                    raise ToolFailure(
                        "world_changed", "World or controller assignment changed during the recipe."
                    )
                if (
                    not current["input_admitted"]
                    or current.get("menu_gated") != 0
                    or current.get("physical_mask") != 0
                    or current["actors"][actor]["observed"] != 1
                ):
                    raise ToolFailure(
                        "input_admission_failed", "Movement readiness changed during the recipe."
                    )

            try:
                for _ in range(3):
                    current = await self._snapshot()
                    check_world(current)
                    await self._request(
                        "movement_pulse",
                        recipe=recipe,
                        stage=before["stage"],
                        generation=before["generation"],
                    )
                    await asyncio.sleep(0.1)
                    samples.append(await self._snapshot())
                    check_world(samples[-1])
            except BaseException as exc:
                failure = exc
            finally:
                try:
                    await self._request("neutral", connected=False)
                    released = True
                except Exception as exc:
                    self.unusable = True
                    await self._stop()
                    failure = ToolFailure("cleanup_failed", "Input release failed; owned game stopped.")
                    failure.__cause__ = exc
            if failure is None:
                try:
                    await asyncio.sleep(0.2)
                    samples.append(await self._snapshot())
                    check_world(samples[-1])
                except BaseException as exc:
                    failure = exc
            summary = {
                "sample_count": len(samples),
                "input_released": released,
                "planned_press_ms": 300,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "max_faults": max(s["faults"] for s in samples),
                "max_native_errors": max(s["native_errors"] for s in samples),
                "outcome": "cancelled"
                if isinstance(failure, asyncio.CancelledError)
                else "failed"
                if failure
                else "completed",
            }
            artifact = self.artifacts.put(
                "movement_trace",
                {
                    "summary": summary,
                    "samples": samples,
                    "limits": [
                        "Input submission is not proof of actor movement or physical-controller behavior.",
                        "These recipes still require real-game acceptance.",
                    ],
                },
                provenance,
            )
            if failure:
                if isinstance(failure, asyncio.CancelledError):
                    failure.artifact = artifact
                else:
                    failure = ToolFailure(getattr(failure, "code", "scenario_failed"), str(failure))
                    failure.details = artifact
                raise failure
            return {**artifact, "summary": summary, "cleanup": "input_released"}

    async def capture(self, seconds: float, interval_ms: int = 250, neutral: bool = False) -> dict:
        self._admit()
        if (
            not 0.1 <= seconds <= self.config.settings.limits.max_experiment_seconds
            or not 100 <= interval_ms <= 2000
        ):
            raise ToolFailure(
                "invalid_parameters", "Use a bounded duration and a 100–2000 ms sampling interval."
            )
        async with self.operation_lock:
            rows, encoded_bytes, input_active = [], 0, False
            started = time.monotonic()
            end = started + seconds
            before = await self._snapshot()
            if neutral and not before["input_admitted"]:
                raise ToolFailure(
                    "capability_unavailable",
                    "Neutral-input recipe requires developer_input=1 and native offline readiness.",
                )
            failure = None
            captured_receipt = dict(self.receipt or {})
            try:
                while time.monotonic() < end:
                    if neutral:
                        # Refresh at <=1s; the native provider expires after 2s.
                        input_active = True
                        await self._request("neutral", connected=True)
                    row = await self._snapshot()
                    row["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                    serialized_row = json.dumps(row, ensure_ascii=False, indent=2)
                    # Account for pretty-printed storage and nesting, not just
                    # compact wire JSON, so overflow can retain partial evidence.
                    encoded_bytes += len(serialized_row.encode()) + 8 * (serialized_row.count("\n") + 1) + 2
                    if encoded_bytes > self.config.settings.limits.max_trace_bytes - 4096:
                        raise ToolFailure(
                            "trace_overflow", "Trace byte budget exhausted; no unbounded capture allowed."
                        )
                    rows.append(row)
                    await asyncio.sleep(
                        min(interval_ms / 1000, 1 if neutral else 2, max(0, end - time.monotonic()))
                    )
            except BaseException as exc:
                failure = exc
            finally:
                if input_active:
                    try:
                        await self._request("neutral", connected=False)
                    except Exception as exc:
                        self.unusable = True
                        await self._stop()
                        failure = ToolFailure(
                            "cleanup_failed", "Neutral-input cleanup failed; owned session was stopped."
                        )
                        failure.__cause__ = exc
            summary = {
                "sample_count": len(rows),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "max_faults": max((r["faults"] for r in rows), default=0),
                "max_native_errors": max((r["native_errors"] for r in rows), default=0),
                "generation_changes": sum(
                    a["generation"] != b["generation"] for a, b in zip(rows, rows[1:], strict=False)
                ),
                "stage_changes": sum(a["stage"] != b["stage"] for a, b in zip(rows, rows[1:], strict=False)),
                "outcome": "cancelled"
                if isinstance(failure, asyncio.CancelledError)
                else "failed"
                if failure
                else "completed",
            }
            provenance = {
                **captured_receipt,
                "source_commit": self.config.settings.coop_source_commit,
                "evidence_class": "synthetic_native" if neutral else "native_observation",
                "recipe": "neutral_input" if neutral else "observe_idle",
            }
            artifact = self.artifacts.put(
                "runtime_trace",
                {
                    "summary": summary,
                    "samples": rows,
                    "limits": [
                        "No physical-controller acceptance.",
                        "Observation/neutral input only; no combat assertion.",
                    ],
                },
                provenance,
            )
            if failure is not None:
                if isinstance(failure, asyncio.CancelledError):
                    failure.artifact = artifact
                elif isinstance(failure, ToolFailure):
                    failure.details = artifact
                else:
                    wrapped = ToolFailure("capture_failed", str(failure))
                    wrapped.details = artifact
                    failure = wrapped
                raise failure
            return {
                **artifact,
                "summary": summary,
                "cleanup": "input_released" if neutral else "no_input_used",
            }

    async def stop(self) -> dict:
        self._admit()
        async with self.operation_lock:
            return await self._stop()

    async def _stop(self) -> dict:
        heartbeat, self.heartbeat_task = self.heartbeat_task, None
        if heartbeat is not None and heartbeat is not asyncio.current_task():
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        process = self.process
        receipt = self.receipt
        if process is not None:
            if process.stdin:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.wait()
            if receipt:
                path = self.config.artifacts / "sessions" / (receipt["session_id"] + ".json")
                if path.exists():
                    owned = read_json(path)
                    if owned.get("session_id") == receipt["session_id"]:
                        await asyncio.to_thread(stop_owned, owned["pid"], owned["process_created"])
        if self.error_stream:
            self.error_stream.close()
            self.error_stream = None
        self.process, self.receipt = None, None
        return {
            "stopped": True,
            "session_id": receipt["session_id"] if receipt else None,
            "game_saved": False,
            "cleanup": "owned_process_exit_verified",
        }

    async def close(self):
        await self._stop()
