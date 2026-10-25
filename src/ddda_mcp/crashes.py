"""Owned-process crash evidence and private Windows minidumps. MIT, Thingolus."""

import ctypes
import hashlib
import json
import os
import struct

import psutil

from .common import ToolFailure, contained, digest, identifier, read_json

MAX_DUMP = 64 * 1024 * 1024


def write_minidump(pid, created, path):
    """Only called for the supervisor-owned process, never an arbitrary tool PID."""
    if os.name != "nt":
        raise ToolFailure("platform_unsupported", "Minidump capture requires Windows.")
    process = psutil.Process(pid)
    if process.create_time() != created or not process.is_running():
        raise ToolFailure("process_changed", "Owned process lifetime changed.")
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    dbghelp.MiniDumpWriteDump.argtypes = [w.HANDLE, w.DWORD, w.HANDLE, w.DWORD, w.LPVOID, w.LPVOID, w.LPVOID]
    dbghelp.MiniDumpWriteDump.restype = w.BOOL
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ToolFailure("dump_capture_failed", f"OpenProcess failed ({ctypes.get_last_error()}).")
    file = None
    try:
        if psutil.Process(pid).create_time() != created:
            raise ToolFailure("process_changed", "Process was replaced before capture.")
        path.parent.mkdir(parents=True, exist_ok=True)
        file = kernel.CreateFileW(str(path), 0x40000000, 0, None, 1, 0x80, None)
        if file in (None, ctypes.c_void_p(-1).value):
            raise ToolFailure("dump_capture_failed", f"CreateFile failed ({ctypes.get_last_error()}).")
        # MiniDumpNormal includes stacks/modules, not a full heap dump.
        if not dbghelp.MiniDumpWriteDump(handle, pid, file, 0, None, None, None):
            raise ToolFailure("dump_capture_failed", f"MiniDumpWriteDump failed ({ctypes.get_last_error()}).")
    finally:
        if file not in (None, ctypes.c_void_p(-1).value):
            kernel.CloseHandle(file)
        kernel.CloseHandle(handle)
    if path.stat().st_size > MAX_DUMP:
        raise ToolFailure("dump_too_large", "Dump exceeds 64 MiB; retained privately, not exposed inline.")
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}


def dump_summary(raw):
    """Parse bounded directory/module/exception metadata; do not guess a stack unwind."""

    def span(at, n):
        if at < 0 or n < 0 or at + n > len(raw):
            raise ToolFailure("dump_invalid", "Minidump contains an out-of-bounds stream.")
        return raw[at : at + n]

    if not 32 <= len(raw) <= MAX_DUMP or raw[:4] != b"MDMP":
        raise ToolFailure("dump_invalid", "Expected a bounded Windows minidump.")
    count, offset = struct.unpack_from("<II", raw, 8)
    if count > 128:
        raise ToolFailure("dump_invalid", "Minidump stream count exceeds bounds.")
    streams = {}
    for i in range(count):
        kind, size, rva = struct.unpack("<III", span(offset + 12 * i, 12))
        if kind == 0 and size == 0 and rva == 0:
            continue  # Windows reserves zeroed UnusedStream directory slots.
        if kind in streams:
            raise ToolFailure("dump_invalid", "Duplicate minidump stream.")
        streams[kind] = span(rva, size)
    modules = []
    if 4 in streams:
        data = streams[4]
        if len(data) < 4:
            raise ToolFailure("dump_invalid", "Truncated module stream.")
        n = struct.unpack_from("<I", data)[0]
        if n > 1024 or len(data) != 4 + n * 108:
            raise ToolFailure("dump_invalid", "Invalid module stream extent.")
        for i in range(n):
            base, size, checksum, timestamp, name_at = struct.unpack_from("<Q4I", data, 4 + i * 108)
            length = struct.unpack("<I", span(name_at, 4))[0]
            if length > 4096 or length % 2:
                raise ToolFailure("dump_invalid", "Invalid module name.")
            name = span(name_at + 4, length).decode("utf-16-le")
            modules.append(
                {
                    "name": name.replace("\\", "/").rsplit("/", 1)[-1],
                    "bytes": size,
                    "timestamp": timestamp,
                    "_base": base,
                }
            )
    exception = None
    if 6 in streams:
        data = streams[6]
        if len(data) != 168:
            raise ToolFailure("dump_invalid", "Invalid exception stream.")
        thread, code = struct.unpack_from("<I", data)[0], struct.unpack_from("<I", data, 8)[0]
        address = struct.unpack_from("<Q", data, 24)[0]
        module = next((m for m in modules if m["_base"] <= address < m["_base"] + m["bytes"]), None)
        exception = {
            "thread": thread,
            "code": f"0x{code:08x}",
            "module": module["name"] if module else None,
            "rva": address - module["_base"] if module else None,
        }
    for m in modules:
        del m["_base"]
    return {
        "streams": sorted(streams),
        "modules": modules,
        "exception": exception,
        "stack": "Use captured native unwind frames or a debugger with matching symbols; stack words are not treated as return addresses.",
    }


def fingerprint(report):
    location = report.get("location") or report.get("exception") or {}
    key = {
        "type": report.get("type", location.get("code")),
        "module": location.get("module"),
        "rva": location.get("rva"),
    }
    return (
        hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
        if key["type"] and key["module"] is not None and key["rva"] is not None
        else None
    )


class Crashes:
    def __init__(self, app):
        self.app = app

    async def capture(self, include_dump=False):
        sessions = self.app.sessions
        sessions._admit()
        async with sessions.operation_lock:
            receipt = dict(sessions.receipt or {})
            data = await sessions._request("diagnostic_snapshot")
            if include_dump:
                data["dump"] = await sessions._request("diagnostic_dump")
            data["summary"] = {
                "threads": len(data.get("threads", [])),
                "kind": "thread_snapshot",
                "dump": include_dump,
            }
            return {
                **self.app.artifacts.put(
                    "native_diagnostic",
                    data,
                    {"session": receipt, "evidence_class": "native_thread_observation"},
                ),
                "summary": data["summary"],
            }

    def reports(self, session_id=None):
        root = self.app.config.artifacts / "crashes"
        rows = []
        for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime)[-1000:]:
            doc = read_json(path, 65536)
            if session_id is None or doc.get("session", {}).get("session_id") == session_id:
                rows.append(
                    {
                        "report_id": path.stem,
                        "kind": doc.get("kind"),
                        "captured_at": doc.get("captured_at"),
                        "session_id": doc.get("session", {}).get("session_id"),
                        "fingerprint": fingerprint(doc.get("exception", {})),
                    }
                )
        return {"reports": rows[-100:], "total": len(rows)}

    def analyze(self, report_id):
        root = self.app.config.artifacts / "crashes"
        doc = read_json(contained(root, root / (identifier(report_id) + ".json")), 65536)
        exception = doc.get("exception", {})
        known = {
            int(s.get("runtime_signature", {}).get("rva", "-1"), 16): s for s in self.app.source.symbols()
        }
        frames = exception.get("stack", {}).get("frames", [])
        linked = []
        for frame in frames:
            row = dict(frame)
            if (frame.get("module") or "").lower() == "ddda.exe" and frame.get("rva") in known:
                symbol = known[frame["rva"]]
                row["source_references"] = symbol["sources"]
                row["known_symbol"] = symbol["name"]
            linked.append(row)
        return {
            "report_id": report_id,
            "session": doc.get("session"),
            "exception": exception,
            "frames": linked,
            "fingerprint": fingerprint(exception),
            "scope": "Observed exception and captured frames; fault location is not automatically the root cause.",
        }


def register_tools(mcp, app):
    from .server import Read, Result, Write

    @mcp.tool(annotations=Write)
    async def capture_session_diagnostic(include_dump: bool = False) -> Result:
        """Capture owned-game threads/modules and optionally a private Windows minidump; no automatic hang diagnosis."""
        return await app.invoke("capture_session_diagnostic", app.crashes.capture, include_dump)

    @mcp.tool(annotations=Read)
    async def list_crash_reports(session_id: str | None = None) -> Result:
        """List durable native exception reports, including reports retained after the game exits."""
        return await app.invoke("list_crash_reports", app.crashes.reports, session_id)

    @mcp.tool(annotations=Read)
    async def analyze_crash_report(report_id: str) -> Result:
        """Read a private exception report and link exact known game RVAs to pinned research."""
        return await app.invoke("analyze_crash_report", app.crashes.analyze, report_id)
