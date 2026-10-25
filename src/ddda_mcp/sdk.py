"""Versioned copied-value SDK and a minimal offline research bridge. MIT, Thingolus."""

import asyncio
import hashlib
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .build import run_process, unpack_archive
from .common import ToolFailure, atomic_json, contained, digest
from .config import BASELINE, GAME_SHA256
from .sdk_contracts import CONTRACT_TEST, catalog, header
from .sdk_contracts import schemas as gameplay_schemas

SCHEMA = {
    "version": 1,
    "game_sha256": GAME_SHA256,
    "source_commit": BASELINE,
    "access": "Copied observations only; actor access requires a reviewed game callback and identity checks.",
    "party_fields": {
        "role": "uint32",
        "stage": "uint32",
        "action": "uint32",
        "vocation": "uint32",
        "position": "float32[3]",
        "hp": "float32",
        "hp_max": "float32",
        "stamina": "float32",
    },
    "availability": "Unavailable fields are absent/null in JSON and flagged in native samples.",
    "known_layouts": {
        "actor_position": 0xE0,
        "actor_action": 0x2DD4,
        "actor_info": 0x3DEC,
        "info_vocation": 0x10,
        "info_stamina": 0x2A8,
    },
    "source_paths": [
        "research/observe_sprint_stamina.js",
        "research/observe_mage_healing.js",
        "research/party_inventory_snapshot.js",
        "src/native_offline.cpp",
        "src/network_guard.cpp",
    ],
}

HEADER = """// Generated DDDA copied-value SDK v1. Copyright (c) 2026 Thingolus. MIT.
#pragma once
#include <cstdint>
#include <cstddef>
namespace ddda {
inline constexpr std::uint32_t sdk_version = 1;
struct PartySample {
    std::uint32_t size = sizeof(PartySample), version = sdk_version, available = 0;
    std::uint32_t role = 0, stage = 0, action = 0, vocation = 0;
    float position[3]{}, hp = 0, hp_max = 0, stamina = 0;
};
static_assert(sizeof(PartySample) == 52);
static_assert(offsetof(PartySample, position) == 28);
// Call from a host that provides validated copied samples. No game pointers cross this API.
using SampleConsumer = void (*)(const PartySample&);
inline bool valid(const PartySample& s) {
    return s.size == sizeof(PartySample) && s.version == sdk_version && s.role < 2 && s.available == 1;
}
}
"""


def bridge_source(signatures):
    specs = []
    bindings = {
        "option_set": ("set_hook", "&coop::native::set_original"),
        "option_get": ("get_hook", "&coop::native::get_original"),
        "connect": ("connect_hook", "&coop::native::connect_original"),
        "online_query": ("query_hook", "&query_original"),
    }
    for name, (hook, original) in bindings.items():
        spec = signatures[name]
        raw = bytes.fromhex(spec["bytes"])
        values = ",".join(str(b) for b in raw)
        specs.append(
            f"const unsigned char {name}_bytes[] = {{{values}}};\n"
            f"if (!install(0x400000+{int(spec['rva'], 16)}, {name}_bytes, sizeof({name}_bytes), "
            f"reinterpret_cast<void*>(coop::native::{hook}), {original})) return 0;"
        )
    return (
        """// Minimal standalone research bridge. Copyright (c) 2026 Thingolus. MIT.
#include <windows.h>
#include <MinHook.h>
#include <cstring>
#include <cstdint>
#include "coop/native_offline.hpp"
extern "C" int __cdecl EnsureOffline();
extern "C" int __cdecl OfflineState();
static void* query_original{};
static bool install(std::uintptr_t address, const unsigned char* bytes, size_t length, void* hook, void** original) {
    if (std::memcmp(reinterpret_cast<void*>(address), bytes, length)) return false;
    return MH_CreateHook(reinterpret_cast<void*>(address), hook, original) == MH_OK &&
           MH_EnableHook(reinterpret_cast<void*>(address)) == MH_OK;
}
extern "C" __declspec(dllexport) int __cdecl ResearchInitialize() {
    if (reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr)) != 0x400000 || !EnsureOffline()) return 0;
"""
        + "\n".join(specs)
        + """
    return 1;
}
extern "C" __declspec(dllexport) int __cdecl ResearchHealthy() { return OfflineState()==2 && coop::native::healthy(); }
extern "C" __declspec(dllexport) unsigned __cdecl ResearchErrors() { return coop::native::errors(); }
"""
    )


class SDK:
    def __init__(self, config, source, artifacts, builds):
        self.config, self.source, self.artifacts, self.builds = config, source, artifacts, builds

    def catalog(self):
        return {
            **SCHEMA,
            "observation_extension": catalog(),
            "native_events": {
                "abi_version": 1,
                "header": "native_sdk.hpp",
                "backend": "standalone",
                "kinds": ["sample", "stamina_request", "hp_changed", "inventory_delta", "actor_replaced"],
                "exports": ["DdSdkStart", "DdSdkReadEvents", "DdSdkStatus", "DdSdkStop"],
                "capture_tool": "capture_native_sdk_events",
                "scope": "Sampled callback events, 5 Hz per party role; single consumer, bounded queue, no causal attribution or complete lifetime tracking.",
            },
            "backends": {
                "coop": "Full reviewed co-op control and diagnostics",
                "standalone": "Owned offline game; callback-only party/inventory/enemy observation, no co-op DLL or input control",
            },
        }

    def generate(self):
        self.config.require_development()
        self.source.verify()
        if self.source.commit != BASELINE:
            raise ToolFailure("sdk_source", "SDK generation requires the reviewed baseline.")
        folder = self.config.artifacts / "sdk" / uuid.uuid4().hex
        folder.mkdir(parents=True)
        schemas = {**SCHEMA, "references": [self.source.reference(p) for p in SCHEMA["source_paths"]]}
        (folder / "ddda_sdk.hpp").write_text(HEADER, encoding="utf-8")
        (folder / "ddda_observations.hpp").write_text(header(), encoding="utf-8")
        atomic_json(folder / "gameplay_schemas.json", gameplay_schemas())
        (folder / "observation_contract.cpp").write_text(CONTRACT_TEST, encoding="utf-8")
        schemas["observation_extension"] = catalog()
        atomic_json(folder / "schema.json", schemas)
        signatures = {
            s["name"]: s["runtime_signature"] for s in self.source.symbols() if "runtime_signature" in s
        }
        for name in ("native_sdk.hpp", "native_sdk.cpp", "example_mod.cpp"):
            (folder / name).write_bytes(Path(__file__).with_name(name).read_bytes())
        from .trace_catalog import reviewed

        signature = reviewed(self.source, "native_stamina_apply")
        identity = (
            "// Generated reviewed identity. MIT, Thingolus.\n#pragma once\n"
            + "constexpr unsigned char ddda_game_sha256[]={"
            + ",".join(str(b) for b in bytes.fromhex(GAME_SHA256))
            + "};\n"
            + "constexpr unsigned char ddda_stamina_bytes[]={"
            + ",".join(str(b) for b in bytes.fromhex(signature["bytes"]))
            + "};\n"
            + f"constexpr unsigned ddda_stamina_rva={signature['rva']};\n"
        )
        (folder / "sdk_build_identity.hpp").write_text(identity, encoding="utf-8")
        (folder / "NATIVE_SDK.md").write_text(
            "# Native event SDK\n\nBuild Win32 with CMake. Link a mod against research_bridge.lib and include native_sdk.hpp. "
            "ResearchInitialize establishes the offline guard; call DdSdkStart from a worker after loading a world. "
            "Drain DdSdkReadEvents regularly; check DdSdkStatus for dropped events and errors. "
            "example_mod.dll exports SampleStart, SamplePoll (a copied-value HP logger), and SampleStop. "
            "The queue has one consumer; SamplePoll and an external consumer must not drain it concurrently.\n\n"
            "Status distinguishes queue overflow (dropped) from callbacks skipped on a busy sampling lock "
            "(contended_callbacks, including non-party callbacks). Neither counter proves complete coverage.\n\n"
            "Native stamina requests are sampled at most five times per second per party actor. HP and inventory events are sampled deltas, not causal hooks. "
            "IDs change when an observed actor or stage changes; destruction/reuse between samples is not excluded. "
            "Only the exact executable hash and hook signature are admitted. DdSdkStop must return 1; otherwise stop the owned process. "
            "Stop retains the disabled trampoline for in-flight return paths; Start can reuse it after signature checks. "
            "Keep the DLL loaded until process exit. Never initialize, unload, or stop under the loader lock.\n",
            encoding="utf-8",
        )
        (folder / "bridge.cpp").write_text(bridge_source(signatures), encoding="utf-8")
        for path in ("src/network_guard.cpp", "src/native_offline.cpp", "include/coop/native_offline.hpp"):
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.source.read_many([path])[path])
        (folder / "LICENSE").write_text(self.source.read("LICENSE"), encoding="utf-8")
        (folder / "sdk_test.cpp").write_text(
            """#include "ddda_sdk.hpp"
int main() { ddda::PartySample s; if(ddda::valid(s)) return 1; s.available=1;
if(!ddda::valid(s)) return 2; s.version=999; return ddda::valid(s)?3:0; }
""",
            encoding="utf-8",
        )
        (folder / "CMakeLists.txt").write_text(
            """cmake_minimum_required(VERSION 3.20)
project(DDDAResearchBridge LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
option(DDDA_BUILD_BRIDGE "Build the Windows offline research bridge" ON)
if(DDDA_BUILD_BRIDGE)
add_subdirectory(external/minhook)
add_library(research_bridge SHARED bridge.cpp native_sdk.cpp src/network_guard.cpp src/native_offline.cpp)
target_compile_definitions(research_bridge PRIVATE DDDA_SDK_BUILD)
target_include_directories(research_bridge PRIVATE include external/minhook/include)
target_link_libraries(research_bridge PRIVATE minhook ws2_32 bcrypt)
add_library(example_mod SHARED example_mod.cpp)
target_link_libraries(example_mod PRIVATE research_bridge)
endif()
add_executable(sdk_contract sdk_test.cpp)
add_executable(observation_contract observation_contract.cpp)
enable_testing()
add_test(NAME sdk_contract COMMAND sdk_contract)
add_test(NAME observation_contract COMMAND observation_contract)
""",
            encoding="utf-8",
        )
        files = {p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()}
        receipt = self.artifacts.put(
            "sdk_bundle",
            {
                "directory": str(folder),
                "files": files,
                "schema": schemas,
                "summary": {"version": 1, "files": len(files)},
            },
            {"source_commit": BASELINE, "evidence_class": "generated_sdk", "creator": "Thingolus"},
        )
        return {**receipt, "directory": str(folder)}

    async def build(self, bundle_id):
        self.config.require_development()
        doc = self.artifacts.get(bundle_id)
        if doc["kind"] != "sdk_bundle" or doc["provenance"]["source_commit"] != BASELINE:
            raise ToolFailure("sdk_invalid", "Select a generated SDK bundle.")
        folder = contained(self.config.artifacts / "sdk", Path(doc["data"]["directory"]))
        for name, sha in doc["data"]["files"].items():
            if digest(contained(folder, folder / name)) != sha:
                raise ToolFailure(
                    "sdk_changed", "Generated SDK source changed; regenerate it before building."
                )
        # Build only generated reviewed inputs; never the sibling working tree.
        async with self.builds.lock:
            target = self.config.artifacts / "sdk-builds" / uuid.uuid4().hex
            shutil.copytree(folder, target)
            pins = json.loads(self.source.read("tools.lock.json"))
            pin = next(r["commit"] for r in pins["sources"] if r["name"] == "minhook")
            if self.source.bundled:
                vendor = self.source.snapshot()["minhook"]
                if vendor["commit"] != pin:
                    raise ToolFailure("sdk_source", "Bundled MinHook identity changed.")
                for name, row in vendor["files"].items():
                    raw = row["text"].encode("utf-8")
                    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                        raise ToolFailure("sdk_source", "Bundled MinHook source changed.")
                    output = contained(target / "external/minhook", target / "external/minhook" / name)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(raw)
            else:
                raw = await asyncio.to_thread(
                    subprocess.check_output,
                    [
                        "git",
                        "-C",
                        str(self.config.source / "external/minhook"),
                        "archive",
                        "--format=tar",
                        pin,
                    ],
                    timeout=30,
                )
                unpack_archive(raw, target / "external/minhook")
            cmake = self.builds.executable(self.config.settings.cmake, "cmake", "cmake/**/cmake.exe")
            ctest = str(Path(cmake).with_name("ctest.exe"))
            commands = [
                [
                    cmake,
                    "-S",
                    str(target),
                    "-B",
                    str(target / "build"),
                    "-G",
                    "Visual Studio 17 2022",
                    "-A",
                    "Win32",
                ],
                [cmake, "--build", str(target / "build"), "--config", "Debug", "--parallel", "4"],
                [ctest, "--test-dir", str(target / "build"), "-C", "Debug", "--output-on-failure"],
            ]
            steps = []
            for i, command in enumerate(commands):
                steps.append(await run_process(command, target, target / f"step-{i}.log", 180))
                if steps[-1]["exit_code"]:
                    break
            dll = target / "build/Debug/research_bridge.dll"
            passed = len(steps) == 3 and all(s["exit_code"] == 0 for s in steps) and dll.is_file()
            receipt = self.artifacts.put(
                "sdk_build",
                {
                    "summary": {"passed": passed},
                    "steps": steps,
                    "dll": str(dll),
                    "sha256": digest(dll) if passed else None,
                    "bundle_id": bundle_id,
                    "bundle_sha256": digest(self.artifacts.path(bundle_id)),
                    "observer_sha256": hashlib.sha256(
                        Path(__file__).with_name("standalone.js").read_bytes()
                    ).hexdigest(),
                },
                {"source_commit": BASELINE, "game_sha256": GAME_SHA256, "evidence_class": "static_build"},
            )
            return {**receipt, "summary": {"passed": passed}}

    def verified_bridge(self, build_id):
        doc = self.artifacts.get(build_id)
        if (
            doc["kind"] != "sdk_build"
            or not doc["data"]["summary"].get("passed")
            or doc["provenance"].get("source_commit") != BASELINE
        ):
            raise ToolFailure("sdk_invalid", "Standalone launch needs a passed SDK bridge build.")
        data = doc["data"]
        dll = contained(self.config.artifacts / "sdk-builds", Path(data["dll"]))
        if (
            digest(dll) != data["sha256"]
            or digest(self.artifacts.path(data["bundle_id"])) != data["bundle_sha256"]
            or digest(Path(__file__).with_name("standalone.js")) != data["observer_sha256"]
        ):
            raise ToolFailure("sdk_changed", "Bridge, observer or source receipt changed; rebuild the SDK.")
        return dll, data["sha256"]

    async def capture(self, sessions, seconds=2):
        sessions._admit()
        if not 0.2 <= seconds <= 10 or (sessions.receipt or {}).get("backend") != "standalone":
            raise ToolFailure(
                "backend_capability", "Start a standalone session; capture duration is 0.2–10 seconds."
            )
        provenance = dict(sessions.receipt)
        async with sessions.operation_lock:
            await sessions._request("research_start", duration_ms=round(seconds * 1000))
            failure = None
            try:
                await asyncio.sleep(seconds)
            except BaseException as exc:
                failure = exc
            try:
                result = await sessions._request("research_stop")
                if not result.get("cleanup", {}).get("sealed"):
                    partial = self.artifacts.put(
                        "standalone_world",
                        result,
                        {**provenance, "evidence_class": "native_callback_observation"},
                    )
                    error = ToolFailure("cleanup_failed", "Standalone observer did not seal.")
                    error.details = partial
                    raise error
            except BaseException:
                await sessions._stop()
                raise
            result["summary"] = {
                "samples": result["world"].get("samples", 0),
                "errors": result["cleanup"].get("errors", []),
                "cleanup_verified": True,
            }
            receipt = self.artifacts.put(
                "standalone_world", result, {**provenance, "evidence_class": "native_callback_observation"}
            )
            if failure:
                failure.details = receipt
                raise failure
            return {**receipt, **result}

    async def events(self, sessions, seconds=2):
        sessions._admit()
        if not 0.2 <= seconds <= 10 or (sessions.receipt or {}).get("backend") != "standalone":
            raise ToolFailure("backend_capability", "Use a standalone session and 0.2–10 seconds.")
        provenance = dict(sessions.receipt)
        events, cleanup, failure = [], {}, None
        async with sessions.operation_lock:
            started = False
            try:
                started = True
                await sessions._request("sdk_events_start", duration_ms=round(seconds * 1000))
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
                    batch = await sessions._request("sdk_events_drain")
                    events.extend(batch["events"])
                    if len(events) > 2048 or batch["status"]["errors"] or batch["status"]["dropped"]:
                        raise ToolFailure(
                            "sdk_capture_incomplete",
                            "Native event errors, dropped events or capture budget exceeded.",
                        )
            except BaseException as exc:
                failure = exc
            finally:
                if started:
                    try:
                        cleanup = await sessions._request("sdk_events_stop")
                        if not cleanup["sealed"]:
                            raise ToolFailure("sdk_cleanup_failed", "Native hook cleanup did not verify.")
                        for _ in range(8):
                            batch = await sessions._request("sdk_events_drain")
                            events.extend(batch["events"])
                            if not batch["status"]["queued"]:
                                break
                        if (
                            batch["status"]["queued"]
                            or batch["status"]["dropped"]
                            or batch["status"]["errors"]
                            or len(events) > 2048
                        ):
                            raise ToolFailure(
                                "sdk_capture_incomplete", "Final native event capture is incomplete."
                            )
                    except BaseException as exc:
                        failure = failure or exc
                        await sessions._stop()
                        cleanup["owned_process_stopped"] = True
        summary = {
            "events": len(events),
            "outcome": "inconclusive" if failure or not events else "completed",
            "cleanup_verified": bool(cleanup.get("sealed")),
        }
        data = {
            "events": events[:2048],
            "cleanup": cleanup,
            "summary": summary,
            "error": str(failure)[:500] if failure else None,
            "limitations": [
                "Stamina requests are sampled native callbacks, at most 5 Hz per party actor.",
                "Contended callback attempts may be skipped, including non-party callbacks; status reports them separately from queued event loss.",
                "HP and inventory changes are sampled deltas; action/attacker attribution is unavailable.",
                "Incarnations detect observed pointer/stage replacement, not unobserved destruction and address reuse.",
            ],
        }
        receipt = self.artifacts.put(
            "native_sdk_events", data, {**provenance, "evidence_class": "native_sdk_callback_observation"}
        )
        if isinstance(failure, asyncio.CancelledError):
            failure.details = receipt
            raise failure
        return {**receipt, "summary": summary}
