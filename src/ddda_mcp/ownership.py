"""All MCP instances share a lock tied to the configured game directory."""

import os
from contextlib import contextmanager

import portalocker
import psutil

from .common import ToolFailure, contained


def game_processes() -> list[dict]:
    found = []
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if (proc.info["name"] or "").lower() == "ddda.exe":
                found.append({"pid": proc.pid, "created": proc.info["create_time"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


@contextmanager
def game_lease(game_root):
    if not game_root.is_dir():
        raise ToolFailure("game_missing", "Configured game directory does not exist.")
    lease = portalocker.Lock(
        str(contained(game_root, game_root / ".ddda-dark-mcp.lock")), mode="a", timeout=0
    )
    try:
        lease.acquire()
    except portalocker.exceptions.LockException as exc:
        raise ToolFailure("session_busy", "Another MCP process owns this game installation.") from exc
    try:
        yield
    finally:
        lease.release()


def require_closed() -> None:
    require_native_host()
    if game_processes():
        raise ToolFailure("session_busy", "DDDA is already running. Its existing owner must finish first.")


def require_native_host() -> None:
    """AppContainer process enumeration may hide the user's game. Fail closed."""
    if os.name != "nt":
        raise ToolFailure("unsupported_host", "Native game operations require Windows.")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    token, is_container, returned = wintypes.HANDLE(), wintypes.DWORD(), wintypes.DWORD()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ToolFailure("host_unverified", "Cannot verify native process visibility.")
    try:
        if not security.GetTokenInformation(
            token, 29, ctypes.byref(is_container), ctypes.sizeof(is_container), ctypes.byref(returned)
        ):
            raise ToolFailure("host_unverified", "Cannot query AppContainer identity.")
        if is_container.value:
            raise ToolFailure(
                "restricted_host",
                "Live/deployment/save operations require a normal Windows user process; AppContainer cannot establish global game ownership.",
            )
    finally:
        kernel.CloseHandle(token)


def stop_owned(pid: int, created: float) -> None:
    try:
        proc = psutil.Process(pid)
        if abs(proc.create_time() - created) > 0.01:
            raise ToolFailure("not_owner", "PID was recycled; refusing to stop it.")
        proc.terminate()
        proc.wait(timeout=8)
    except psutil.NoSuchProcess:
        return
    except (psutil.AccessDenied, psutil.TimeoutExpired) as exc:
        raise ToolFailure("cleanup_failed", "Cannot verify termination of the owned process.") from exc
