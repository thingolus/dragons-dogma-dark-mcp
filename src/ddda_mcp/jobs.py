"""Bounded asynchronous jobs with durable receipts and explicit cancellation."""

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable

from .common import ToolFailure, atomic_json, contained, identifier, read_json, utc_now
from .config import Config


class Jobs:
    def __init__(self, config: Config):
        self.root = config.artifacts / "jobs"
        self.tasks: dict[str, asyncio.Task] = {}
        self.receipts: dict[str, dict] = {}

    def path(self, job_id: str):
        return contained(self.root, self.root / f"{identifier(job_id)}.json")

    def _save(self, job_id: str) -> None:
        atomic_json(self.path(job_id), self.receipts[job_id])

    def submit(self, kind: str, operation: Callable[[], Awaitable[dict]]) -> dict:
        if sum(not task.done() for task in self.tasks.values()) >= 4:
            raise ToolFailure("busy", "At most four background jobs may be pending per server.")
        job_id = uuid.uuid4().hex
        self.receipts[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "state": "queued",
            "owner_pid": os.getpid(),
            "created_at": utc_now(),
            "cleanup": "not_started",
        }
        self._save(job_id)

        async def run():
            receipt = self.receipts[job_id]
            receipt.update(state="running", started_at=utc_now())
            self._save(job_id)
            try:
                receipt["result"] = await operation()
                receipt.update(state="completed", cleanup="completed")
            except asyncio.CancelledError as exc:
                receipt.update(state="cancelled", cleanup="operation_cleanup_finished")
                if hasattr(exc, "artifact"):
                    receipt["partial_evidence"] = exc.artifact
            except ToolFailure as exc:
                receipt.update(
                    state="failed",
                    error={"code": exc.code, "message": str(exc)},
                    cleanup="unknown" if exc.code == "cleanup_failed" else "operation_cleanup_finished",
                )
                if hasattr(exc, "details"):
                    receipt["partial_evidence"] = exc.details
            except Exception as exc:
                receipt.update(
                    state="failed",
                    error={"code": "internal_error", "message": str(exc)[:1000]},
                    cleanup="unknown",
                )
            finally:
                receipt["finished_at"] = utc_now()
                self._save(job_id)

        self.tasks[job_id] = asyncio.create_task(run(), name=f"ddda-{kind}-{job_id}")
        return {"job_id": job_id, "state": "queued"}

    def status(self, job_id: str) -> dict:
        path = self.path(job_id)
        if not path.exists():
            raise ToolFailure("job_not_found", "Unknown job ID.")
        receipt = read_json(path)
        if job_id not in self.tasks and receipt["state"] in {"queued", "running"}:
            receipt = dict(
                receipt,
                state="outcome_unknown",
                recovery="Inspect originating server/session; do not replay automatically.",
            )
        return receipt

    async def cancel(self, job_id: str) -> dict:
        identifier(job_id)
        task = self.tasks.get(job_id)
        if task is None:
            raise ToolFailure("not_owner", "This server does not own that job.")
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.receipts[job_id]["state"] in {"queued", "running"}:
            self.receipts[job_id].update(state="cancelled", cleanup="not_started", finished_at=utc_now())
            self._save(job_id)
        return self.status(job_id)

    async def close(self) -> None:
        await asyncio.gather(*(self.cancel(job_id) for job_id in list(self.tasks)))
