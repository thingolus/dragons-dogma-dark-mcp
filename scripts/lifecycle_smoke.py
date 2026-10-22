"""Real worker lifecycle checks: EOF, parent death and missing heartbeats; no game input."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

from ddda_mcp.common import atomic_json
from ddda_mcp.ownership import game_processes, require_closed, stop_owned

ROOT = Path(__file__).resolve().parents[1]


def worker():
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ddda_mcp.native_worker",
            "--project",
            str(ROOT),
            "--session-id",
            uuid.uuid4().hex,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )


def child():
    process = worker()
    receipt = json.loads(process.stdout.readline())
    print(
        json.dumps(
            {
                "ready": receipt,
                "supervisor_pid": os.getpid(),
                "supervisor_created": psutil.Process().create_time(),
            }
        ),
        flush=True,
    )
    process.wait()


def main():
    report = {"passed": False, "checks": []}
    try:
        for mode in ["stdin_eof", "parent_death", "heartbeat_expiry"]:
            require_closed()
            print("Checking " + mode, flush=True)
            if mode == "parent_death":
                process = subprocess.Popen(
                    [sys.executable, __file__, "--child"], stdout=subprocess.PIPE, text=True
                )
                parent = json.loads(process.stdout.readline())
                receipt = parent["ready"]
            else:
                process = worker()
                receipt = json.loads(process.stdout.readline())
            assert receipt["ready"], receipt
            started = time.monotonic()
            try:
                if mode == "stdin_eof":
                    process.stdin.close()
                elif mode == "parent_death":
                    stop_owned(parent["supervisor_pid"], parent["supervisor_created"])
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline and psutil.pid_exists(receipt["pid"]):
                    await_time = 0.2
                    time.sleep(await_time)
                assert not psutil.pid_exists(receipt["pid"]), "Owned game survived lifecycle cleanup"
                process.wait(timeout=10)
                report["checks"].append(
                    {
                        "mode": mode,
                        "game_pid": receipt["pid"],
                        "session_id": receipt["session_id"],
                        "cleanup_seconds": round(time.monotonic() - started, 3),
                        "passed": True,
                    }
                )
            finally:
                stop_owned(receipt["pid"], receipt["process_created"])
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
        report["passed"] = not game_processes()
    finally:
        atomic_json(ROOT / "artifacts/validation/lifecycle.json", report)
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    child() if args.child else main()
