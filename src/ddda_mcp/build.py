"""Isolated pinned-source builds and bounded Ghidra exports."""

import asyncio
import io
import json
import shutil
import subprocess
import tarfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import portalocker
import psutil

from .artifacts import Artifacts
from .binary import Binary
from .common import ToolFailure, contained, digest
from .config import GAME_SHA256, Config
from .source import Source


async def run_process(args: list[str], cwd: Path, logfile: Path, timeout: int = 600) -> dict:
    process = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    tail = bytearray()
    total = 0
    try:
        async with asyncio.timeout(timeout):
            with logfile.open("wb") as log:
                while block := await process.stdout.read(8192):
                    total += len(block)
                    if total > 10 * 1024 * 1024:
                        raise ToolFailure("output_limit", "Subprocess exceeded the 10 MiB output budget.")
                    log.write(block)
                    tail.extend(block)
                    del tail[:-10000]
            code = await process.wait()
            return {
                "exit_code": code,
                "log_tail": tail.decode("utf-8", errors="replace"),
                "output_bytes": total,
                "log_sha256": digest(logfile),
            }
    finally:
        if process.returncode is None:
            try:
                parent = psutil.Process(process.pid)
                for child in reversed(parent.children(recursive=True)):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                parent.kill()
            except psutil.NoSuchProcess:
                pass
            await process.wait()


def unpack_archive(data: bytes, destination: Path) -> None:
    if len(data) > 128 * 1024 * 1024:
        raise ToolFailure("source_too_large", "Source archive exceeds 128 MiB.")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        total = 0
        for member in archive:
            target = contained(destination, destination / member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                total += member.size
                if total > 128 * 1024 * 1024:
                    raise ToolFailure("source_too_large", "Extracted source exceeds 128 MiB.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as inp, target.open("xb") as out:
                    shutil.copyfileobj(inp, out)
            else:
                raise ToolFailure("invalid_archive", "Source archive contains a link or unsupported entry.")


class Builds:
    def __init__(self, config: Config, source: Source, artifacts: Artifacts):
        self.config, self.source, self.artifacts = config, source, artifacts
        self.lock = asyncio.Lock()

    def executable(self, configured: str | None, name: str, pattern: str) -> str:
        if configured:
            candidate = (self.config.root / configured).resolve()
            if candidate.is_file():
                return str(candidate)
            raise ToolFailure("tool_missing", f"Configured {name} does not exist.")
        found = shutil.which(name)
        if found:
            return found
        matches = sorted((self.config.source / ".tools").glob(pattern))
        if matches:
            return str(matches[0].resolve())
        raise ToolFailure(
            "tool_missing", f"Configure {name} in config/local.json or install the co-op toolchain."
        )

    async def build(self, configuration: str = "Debug", test_group: str = "all") -> dict:
        self.config.require_development()
        if configuration not in {"Debug", "Release"} or test_group not in {"all", "core"}:
            raise ToolFailure("invalid_parameters", "Choose Debug/Release and all/core.")
        if self.lock.locked():
            raise ToolFailure("build_busy", "An offline build/decompilation job is already active.")
        async with self.lock:
            self.source.verify()
            cmake = self.executable(self.config.settings.cmake, "cmake", "cmake/**/cmake.exe")
            ctest = str(
                Path(cmake).with_name("ctest.exe" if Path(cmake).suffix.lower() == ".exe" else "ctest")
            )
            folder = self.config.artifacts / "builds" / uuid.uuid4().hex
            source_root, build_root = folder / "source", folder / "build"
            source_root.mkdir(parents=True)
            archive = await asyncio.to_thread(
                self.source.git,
                "archive",
                "--format=tar",
                self.source.commit,
                "CMakeLists.txt",
                "src",
                "include",
                "tests",
                "config",
                "scripts",
                "assets",
                "research",
            )
            await asyncio.to_thread(unpack_archive, archive, source_root)
            dependency = self.config.source / "external/minhook"
            if not dependency.is_dir():
                raise ToolFailure(
                    "tool_missing", "Pinned MinHook source is missing from the co-op toolchain."
                )
            pins = json.loads(self.source.read("tools.lock.json"))
            pin = next(item["commit"] for item in pins["sources"] if item["name"] == "minhook")
            proc = await asyncio.to_thread(
                subprocess.run,
                ["git", "-C", str(dependency), "archive", "--format=tar", pin],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if proc.returncode:
                raise ToolFailure("source_mismatch", "Pinned MinHook commit is unavailable.")
            await asyncio.to_thread(unpack_archive, proc.stdout, source_root / "external/minhook")
            commands = [
                [
                    cmake,
                    "-S",
                    str(source_root),
                    "-B",
                    str(build_root),
                    "-G",
                    "Visual Studio 17 2022",
                    "-A",
                    "Win32",
                ],
                [cmake, "--build", str(build_root), "--config", configuration, "--parallel", "4"],
                [
                    ctest,
                    "--test-dir",
                    str(build_root),
                    "-C",
                    configuration,
                    "--output-on-failure",
                    "--output-junit",
                    str(folder / "tests.xml"),
                ],
            ]
            if test_group == "core":
                commands[1].extend(["--target", "coop_tests", "settings_tests", "session_tests"])
                commands[-1].extend(
                    ["-R", "^(core_and_hook_tests|settings_validation|controller_session_policy)$"]
                )
            results = []
            for index, command in enumerate(commands):
                result = await run_process(command, folder, folder / f"step-{index}.log", 1200)
                results.append(result)
                if result["exit_code"]:
                    break
            tests, failures = 0, 0
            if (folder / "tests.xml").exists():
                report = ET.parse(folder / "tests.xml")
                cases = list(report.iter("testcase"))
                tests = len(cases)
                failures = sum(
                    any(case.find(tag) is not None for tag in ("failure", "error")) for case in cases
                )
            binaries = {p.name: digest(p) for p in (build_root / configuration).glob("*.dll")}
            summary = {
                "steps_completed": len(results),
                "tests": tests,
                "failures": failures,
                "passed": len(results) == 3
                and all(r["exit_code"] == 0 for r in results)
                and tests > 0
                and failures == 0,
            }
            artifact = self.artifacts.put(
                "build",
                {"summary": summary, "steps": results, "binaries": binaries},
                {
                    "source_commit": self.source.commit,
                    "minhook_commit": pin,
                    "configuration": configuration,
                    "recipe": "build_" + test_group,
                    "evidence_class": "static",
                },
            )
            return {**artifact, "summary": summary, "native_acceptance": "unverified"}

    async def decompile(self, symbol_name: str) -> dict:
        self.config.require_development()
        if self.lock.locked():
            raise ToolFailure("build_busy", "An offline build/decompilation job is already active.")
        async with self.lock:
            settings = self.config.settings
            if not settings.ghidra_home or not settings.ghidra_project_dir:
                raise ToolFailure(
                    "tool_missing",
                    "Configure ghidra_home and ghidra_project_dir for an existing analysis database.",
                )
            self.source.verify()
            symbol = next((s for s in self.source.symbols() if s["name"] == symbol_name), None)
            if not symbol or "runtime_signature" not in symbol:
                raise ToolFailure("symbol_not_found", "An exact signature-pinned symbol name is required.")
            info = Binary(self.config).inventory()
            if info["sha256"] != GAME_SHA256:
                raise ToolFailure(
                    "unsupported_build", "Decompilation database must correspond to the pinned game."
                )
            home = (self.config.root / settings.ghidra_home).resolve()
            projects = (self.config.root / settings.ghidra_project_dir).resolve()
            if not (projects / (settings.ghidra_project_name + ".gpr")).is_file():
                raise ToolFailure(
                    "database_missing", "Existing Ghidra project not found; automatic import is disabled."
                )
            if list(projects.glob(settings.ghidra_project_name + "*.lock*")):
                raise ToolFailure(
                    "database_busy", "Ghidra database has an active lock; close its current owner first."
                )
            java = self.executable(settings.java, "java", "jdk21/**/java.exe")
            jar = home / "Ghidra/Framework/Utility/lib/Utility.jar"
            if not jar.is_file():
                raise ToolFailure("tool_missing", "Configured ghidra_home does not contain Utility.jar.")
            folder = self.config.artifacts / "decompilation" / uuid.uuid4().hex
            folder.mkdir(parents=True)
            shutil.copyfile(Path(__file__).with_name("ExportMcp.java"), folder / "ExportMcp.java")
            output = folder / "export.json"
            args = [
                java,
                "-Xmx3G",
                "-cp",
                str(jar),
                "ghidra.Ghidra",
                "ghidra.app.util.headless.AnalyzeHeadless",
                str(projects),
                settings.ghidra_project_name,
                "-process",
                "DDDA.exe",
                "-readOnly",
                "-noanalysis",
                "-scriptPath",
                str(folder),
                "-postScript",
                "ExportMcp.java",
                str(output),
                GAME_SHA256,
                hex(int(info["image_base"], 16) + int(symbol["runtime_signature"]["rva"], 16)),
                "-max-cpu",
                "2",
            ]
            try:
                with portalocker.Lock(str(projects / ".ddda-mcp-export.lock"), mode="a", timeout=0):
                    result = await run_process(args, folder, folder / "ghidra.log", 120)
            except portalocker.exceptions.LockException as exc:
                raise ToolFailure("database_busy", "Another MCP export owns this database.") from exc
            from .common import read_json

            export = read_json(output) if output.exists() else {"error": "No verified export produced."}
            summary = {
                "passed": result["exit_code"] == 0
                and export.get("game_sha256") == GAME_SHA256
                and export.get("success") is True
            }
            artifact = self.artifacts.put(
                "decompilation",
                {"summary": summary, "export": export, "process": result},
                {
                    "source_commit": self.source.commit,
                    "game_sha256": GAME_SHA256,
                    "symbol": symbol_name,
                    "evidence_class": "static",
                    "recipe": "decompile",
                },
            )
            return {**artifact, "summary": summary}
