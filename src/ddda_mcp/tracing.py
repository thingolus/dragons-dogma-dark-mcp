"""Bounded observation with exact code provenance and verified cleanup. MIT, Thingolus."""

import asyncio
import time

from .common import ToolFailure
from .trace_catalog import TRACES, reviewed


class Tracing:
    def __init__(self, source, sessions, builds, artifacts):
        self.source, self.sessions, self.builds, self.artifacts = source, sessions, builds, artifacts

    def catalog(self):
        return {
            "traces": [reviewed(self.source, name) for name in TRACES],
            "policy": "Function entry observers only. Changed/already-hooked prefixes are refused. No argument modification or arbitrary hooks.",
        }

    async def capture(self, symbol, seconds=2.0, decompile=False):
        self.sessions._admit()
        if not 0.1 <= seconds <= 30:
            raise ToolFailure("invalid_parameters", "Trace duration must be 0.1–30 seconds.")
        spec = reviewed(self.source, symbol)
        static = await self.builds.decompile(symbol) if decompile else None
        self.sessions._admit()
        async with self.sessions.operation_lock:
            before = await self.sessions._snapshot()
            if not before["input_admitted"] or before["stage"] == 0:
                raise ToolFailure(
                    "trace_admission_failed", "Trace needs healthy offline loaded developer world."
                )
            provenance = dict(self.sessions.receipt or {})
            data = {
                "symbol": spec,
                "decompilation": static,
                "before": before,
                "samples": [],
                "summary": {"outcome": "inconclusive"},
            }
            failure = None
            started = False
            try:
                await self.sessions._request("trace_start", symbol=symbol, duration_ms=round(seconds * 1000))
                started = True
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    row = await self.sessions._snapshot()
                    data["samples"].append(row)
                    if not row["input_admitted"] or any(row[k] != before[k] for k in ("stage", "generation")):
                        raise ToolFailure("world_changed", "World/guard changed during trace.")
                    await asyncio.sleep(min(0.25, max(0, end - time.monotonic())))
            except BaseException as exc:
                failure = exc
                data["error"] = getattr(exc, "code", "trace_interrupted")
            finally:
                try:
                    for _ in range(10):
                        data["native"] = await self.sessions._request("trace_stop")
                        if data["native"].get("sealed"):
                            break
                        await asyncio.sleep(0.1)
                    else:
                        raise ToolFailure(
                            "cleanup_failed", "Trace callbacks/prefix restoration did not seal."
                        )
                except BaseException as exc:
                    self.sessions.unusable = True
                    await self.sessions._stop()
                    failure = ToolFailure("cleanup_failed", "Trace cleanup failed; owned game stopped.")
                    failure.__cause__ = exc
            native = data.get("native", {})
            if not started:
                # A rejected start must not inherit a previous sealed trace's rows.
                native = data["native"] = {
                    "sealed": native.get("sealed", False),
                    "rows": [],
                    "start_confirmed": False,
                }
            data["summary"] = {
                "outcome": "failed" if failure or native.get("errors") else "completed",
                "events": len(native.get("rows", [])),
                "omitted": native.get("omitted", 0),
                "cleanup_verified": native.get("sealed", False),
            }
            receipt = self.artifacts.put(
                "function_trace",
                data,
                {**provenance, "source_commit": self.source.commit, "evidence_class": "native_observation"},
            )
            if failure:
                failure.artifact = receipt
                failure.details = receipt
                raise failure
            return {**receipt, "summary": data["summary"], "limitation": spec["limitation"]}
