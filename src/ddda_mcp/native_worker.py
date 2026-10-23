"""Isolated Frida broker. stdin accepts only the fixed command vocabulary below."""

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import psutil

from .binary import Binary
from .common import ToolFailure, atomic_json, utc_now
from .config import GAME_SHA256, Config
from .control import verify_control_build
from .deployment import installed, verify_offline_settings
from .ownership import game_lease, require_closed, stop_owned
from .recipes import MOVEMENT
from .saves import Saves


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def run(config: Config, session_id: str, receipt_path: Path, backend="coop", bridge_id=None) -> None:
    import frida

    config.require_development()
    pid, created, session, script, receipt = None, None, None, None, None
    parent = psutil.Process(os.getppid())
    parent_created = parent.create_time()
    work = queue.Queue(maxsize=8)
    done = threading.Event()
    last_request = [time.monotonic()]

    def reader():
        try:
            for line in sys.stdin:
                if len(line) > 4096:
                    break
                work.put(line, timeout=1)
        finally:
            done.set()

    def watchdog():
        while not done.wait(1):
            try:
                if not parent.is_running() or parent.create_time() != parent_created:
                    break
                if time.monotonic() - last_request[0] > 30:
                    break
            except psutil.Error:
                break
        # Expiry must end the broker loop as well as the owned game; otherwise
        # the dead session keeps the game-directory lease indefinitely.
        done.set()
        if pid is not None and created is not None:
            try:
                stop_owned(pid, created)
            except Exception:
                pass

    with game_lease(config.game):
        require_closed()
        Saves(config).require_clear()
        from .mods import require_profile_clear

        require_profile_clear(config, allow_applied=True)
        build = Binary(config).inventory()
        if build["sha256"] != GAME_SHA256:
            raise ToolFailure("unsupported_build", "No native adapter exists for this executable.")
        bridge_path, bridge_sha = None, None
        if backend == "standalone":
            from .artifacts import Artifacts
            from .sdk import SDK
            from .source import Source

            bridge_path, bridge_sha = SDK(config, Source(config), Artifacts(config), None).verified_bridge(
                bridge_id
            )
            # A co-op loader would install competing offline hooks before the observer.
            if any((config.game / name).exists() for name in ("dinput8.dll", "xinput1_3.dll")):
                raise ToolFailure(
                    "loader_conflict",
                    "Use a restorable profile to disable co-op proxy loaders for standalone research.",
                )
            deployment = {"files": {"ddcoop_runtime.dll": None, "ddcoop.ini": None}}
        else:
            deployment = installed(config)
            verify_offline_settings(config.game)
        device = frida.get_local_device()
        try:
            pid = device.spawn(
                str(config.game / "DDDA.exe"),
                cwd=str(config.game),
                env={"SteamAppId": "367500", "SteamGameId": "367500"},
            )
            created = psutil.Process(pid).create_time()
            receipt = {
                "session_id": session_id,
                "backend": backend,
                "bridge_sha256": bridge_sha,
                "pid": pid,
                "process_created": created,
                "owner_pid": os.getpid(),
                "owner_created": psutil.Process().create_time(),
                "state": "starting",
                "created_at": utc_now(),
                "game_sha256": build["sha256"],
                "runtime_sha256": deployment["files"]["ddcoop_runtime.dll"],
                "settings_sha256": deployment["files"]["ddcoop.ini"],
                "runtime_source_commit": deployment.get("source_commit"),
                "runtime_provenance": (
                    "Standalone reviewed offline bridge; no co-op runtime loaded."
                    if backend == "standalone"
                    else "Installed artifact verified by SHA-256; source commit is unknown unless recorded by its deployment."
                ),
            }
            atomic_json(receipt_path, receipt)
            threading.Thread(target=watchdog, daemon=True).start()
            threading.Thread(target=reader, daemon=True).start()
            session = device.attach(pid)
            session.on("detached", lambda *args: done.set())
            from .copied_groups import GROUPS
            from .trace_catalog import TRACES

            script = session.create_script(
                "const REVIEWED_GROUPS = "
                + json.dumps(GROUPS)
                + ";\nconst REVIEWED_TRACES = "
                + json.dumps(TRACES)
                + ";\n"
                + (
                    Path(__file__).with_name("agent.js").read_text(encoding="utf-8")
                    if backend == "coop"
                    else ""
                )
                + "\n"
                + Path(__file__).with_name("tracing.js").read_text(encoding="utf-8")
                + "\n"
                + Path(__file__).with_name("world.js").read_text(encoding="utf-8")
                + "\n"
                + Path(__file__)
                .with_name("control.js" if backend == "coop" else "standalone.js")
                .read_text(encoding="utf-8")
            )
            script.on(
                "message", lambda message, data: print(json.dumps(message), file=sys.stderr, flush=True)
            )
            script.load()
            # Recheck file ownership immediately before loading native code.
            if backend == "coop":
                installed(config)
                script.exports_sync.bootstrap(str(config.game / "ddcoop_runtime.dll"))
            else:
                script.exports_sync.research_bootstrap(str(bridge_path))
            device.resume(pid)
            receipt["state"] = "running"
            atomic_json(receipt_path, receipt)
            emit({"ready": True, **receipt})
            while not done.is_set():
                try:
                    line = work.get(timeout=0.25)
                except queue.Empty:
                    continue
                request = json.loads(line)
                last_request[0] = time.monotonic()
                op = request.get("op")
                try:
                    if backend == "standalone":
                        if op == "stop":
                            emit({"id": request["id"], "ok": True, "value": {"stopping": True}})
                            break
                        if op == "heartbeat":
                            value = {"alive": True}
                        elif op == "research_status":
                            value = script.exports_sync.research_status()
                        elif op == "research_start" and type(request.get("duration_ms")) is int:
                            value = script.exports_sync.research_start(request["duration_ms"])
                        elif op == "research_stop":
                            value = script.exports_sync.research_stop()
                        else:
                            raise ToolFailure(
                                "backend_capability", "Operation is unavailable on standalone observer."
                            )
                        emit({"id": request["id"], "ok": True, "value": value})
                        continue
                    if op in {
                        "neutral",
                        "title_start",
                        "movement_pulse",
                    } and script.exports_sync.control_status().get("running"):
                        raise ToolFailure(
                            "control_busy", "Release the gameplay lease before legacy input recipes."
                        )
                    if op == "heartbeat":
                        value = {"alive": True}
                    elif op == "snapshot":
                        value = script.exports_sync.snapshot()
                    elif op == "performance":
                        value = script.exports_sync.performance()
                    elif op == "death_refusals":
                        value = script.exports_sync.death_refusals()
                    elif op == "copied_group" and request.get("group") in GROUPS:
                        value = script.exports_sync.copied_group(request["group"])
                    elif (
                        op == "trace_start"
                        and request.get("symbol") in TRACES
                        and type(request.get("duration_ms")) is int
                    ):
                        value = script.exports_sync.trace_start(request["symbol"], request["duration_ms"])
                    elif op == "trace_stop":
                        value = script.exports_sync.trace_stop()
                    elif op == "control_claim":
                        verify_control_build(config, receipt)
                        value = script.exports_sync.control_claim()
                    elif op == "control_status":
                        value = script.exports_sync.control_status()
                    elif op == "control_release":
                        value = script.exports_sync.control_release()
                    elif (
                        op == "control_action"
                        and type(request.get("duration_ms")) is int
                        and type(request.get("role")) is int
                    ):
                        value = script.exports_sync.control_action(
                            request.get("action"), request["role"], request["duration_ms"]
                        )
                    elif op == "world_start" and type(request.get("duration_ms")) is int:
                        value = script.exports_sync.world_start(request["duration_ms"])
                    elif op == "world_stop":
                        value = script.exports_sync.world_stop()
                    elif op == "neutral" and type(request.get("connected")) is bool:
                        value = script.exports_sync.neutral(request["connected"])
                    elif op == "title_start" and type(request.get("pressed")) is bool:
                        value = script.exports_sync.title_start(request["pressed"])
                    elif (
                        op == "movement_pulse"
                        and request.get("recipe") in MOVEMENT
                        and type(request.get("stage")) is int
                        and type(request.get("generation")) is int
                    ):
                        value = script.exports_sync.movement_pulse(
                            request["recipe"], request["stage"], request["generation"]
                        )
                    elif op == "stop":
                        emit({"id": request["id"], "ok": True, "value": {"stopping": True}})
                        break
                    else:
                        raise ToolFailure("invalid_command", "Unsupported broker command.")
                    emit({"id": request["id"], "ok": True, "value": value})
                except Exception as exc:
                    emit({"id": request.get("id"), "ok": False, "error": str(exc)[:1000]})
        finally:
            done.set()
            # Killing our own process also removes all instrumentation. We never
            # detach and leave a game running under abandoned synthetic controls.
            if pid is not None and created is not None:
                stop_owned(pid, created)
            if session is not None:
                try:
                    session.detach()
                except Exception:
                    pass
            if receipt is not None:
                atomic_json(receipt_path, dict(receipt, state="stopped", stopped_at=utc_now()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--backend", choices=["coop", "standalone"], default="coop")
    parser.add_argument("--bridge-id")
    args = parser.parse_args()
    from .common import identifier

    config = Config.load(args.project, args.config)
    receipt = config.artifacts / "sessions" / (identifier(args.session_id) + ".json")
    try:
        run(config, args.session_id, receipt, args.backend, args.bridge_id)
    except Exception as exc:
        emit({"ready": False, "error": str(exc)[:1000]})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
