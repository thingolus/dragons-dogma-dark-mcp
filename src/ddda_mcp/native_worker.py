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
from .deployment import installed, verify_offline_settings
from .ownership import game_lease, require_closed, stop_owned


def emit(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def run(config: Config, session_id: str, receipt_path: Path) -> None:
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
        build = Binary(config).inventory()
        if build["sha256"] != GAME_SHA256:
            raise ToolFailure("unsupported_build", "No native adapter exists for this executable.")
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
                "runtime_provenance": "Installed artifact verified by SHA-256; source commit is unknown unless recorded by its deployment.",
            }
            atomic_json(receipt_path, receipt)
            threading.Thread(target=watchdog, daemon=True).start()
            threading.Thread(target=reader, daemon=True).start()
            session = device.attach(pid)
            session.on("detached", lambda *args: done.set())
            script = session.create_script(Path(__file__).with_name("agent.js").read_text())
            script.on(
                "message", lambda message, data: print(json.dumps(message), file=sys.stderr, flush=True)
            )
            script.load()
            # Recheck file ownership immediately before loading native code.
            installed(config)
            script.exports_sync.bootstrap(str(config.game / "ddcoop_runtime.dll"))
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
                    if op == "heartbeat":
                        value = {"alive": True}
                    elif op == "snapshot":
                        value = script.exports_sync.snapshot()
                    elif op == "performance":
                        value = script.exports_sync.performance()
                    elif op == "neutral" and type(request.get("connected")) is bool:
                        value = script.exports_sync.neutral(request["connected"])
                    elif op == "title_start" and type(request.get("pressed")) is bool:
                        value = script.exports_sync.title_start(request["pressed"])
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
    args = parser.parse_args()
    from .common import identifier

    config = Config.load(args.project, args.config)
    receipt = config.artifacts / "sessions" / (identifier(args.session_id) + ".json")
    try:
        run(config, args.session_id, receipt)
    except Exception as exc:
        emit({"ready": False, "error": str(exc)[:1000]})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
