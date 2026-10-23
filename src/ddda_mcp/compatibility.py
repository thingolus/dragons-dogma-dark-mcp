"""Conservative source drift checks; never auto-adopt an upstream commit."""

import hashlib
import re
import threading
from pathlib import Path

from .common import ToolFailure, read_json
from .comparison import changes, settings_summary
from .source import Source

WATCHED = (
    "include/coop/runtime_status.hpp",
    "include/coop/performance.hpp",
    "include/coop/elapsed_tracker.hpp",
    "include/coop/session.hpp",
    "include/coop/shared_life_down_debug.hpp",
    "include/coop/settings.hpp",
    "include/coop/hud.hpp",
    "src/hud.cpp",
    "research/observe_sprint_stamina.js",
    "research/observe_fighter_damage.js",
    "src/runtime.cpp",
    "src/network_guard.cpp",
    "src/settings.cpp",
    "src/proxy.cpp",
    "src/proxy.def",
    "src/xinput_proxy.cpp",
    "src/xinput_proxy.def",
    "CMakeLists.txt",
    "tools.lock.json",
)
REQUIRED_EXPORTS = (
    "CoopInitialize",
    "CoopGetStatus",
    "CoopGetPerformanceStatus",
    "CoopSetTestPads",
    "CoopSharedLifeDownDebugStatus",
    "OfflineState",
    "CoopGetHudStatus",
    "CoopGetVocationStatus",
    "CoopGetGenericStatus",
    "CoopSharedMenuStatus",
    "CoopSharedLifeStatus",
    "CoopGetIngleHudStatus",
)


def capture_contract(source):
    tree = source.tree()
    required = (*WATCHED, "include/coop/supported_build.hpp", "research/symbols.csv", "config/ddcoop.ini")
    missing = sorted(set(required) - tree.keys())
    if missing:
        raise ToolFailure("contract_inputs_missing", "Missing required source inputs: " + ", ".join(missing))
    blobs = source.read_many(list(required))
    exports = {}
    for path in ("src/runtime.cpp", "src/network_guard.cpp", "src/hud.cpp"):
        # Recognize this project's exported C function definitions, not arbitrary C++ ABI.
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", source.read(path), flags=re.S)
        for result, convention, name, args in re.findall(
            r'extern\s+"C"\s+__declspec\(dllexport\)\s+([\w:*<>]+)\s+(__cdecl|__stdcall)\s+(\w+)\s*\(([^()]*)\)\s*\{',
            text,
        ):
            if name in exports:
                raise ToolFailure("contract_parse_failed", "Duplicate exported declaration: " + name)
            exports[name] = re.sub(r"\s+", "", f"{result} {convention}({args})")
    fingerprint = re.search(
        r'sha256\[\]\s*=\s*"([0-9a-f]{64})"', source.read("include/coop/supported_build.hpp")
    )
    if not fingerprint:
        raise ToolFailure("contract_parse_failed", "Supported executable fingerprint is unavailable.")
    signatures = {
        row["name"]: {
            "rva": row["runtime_signature"]["rva"],
            "sha256": hashlib.sha256(bytes.fromhex(row["runtime_signature"]["bytes"])).hexdigest(),
        }
        for row in source.symbols()
        if "runtime_signature" in row
    }
    if not signatures:
        raise ToolFailure("contract_parse_failed", "Signature inventory is empty.")
    return {
        "schema_version": 1,
        "source_commit": source.commit,
        "game_sha256": fingerprint.group(1),
        "signatures": signatures,
        "exports": exports,
        "settings": settings_summary(blobs["config/ddcoop.ini"]),
        "watched_sources": {path: hashlib.sha256(blobs[path]).hexdigest() for path in WATCHED},
    }


def compare_contracts(before, after):
    differences = {
        key: changes(before[key], after[key])
        for key in ("signatures", "exports", "settings", "watched_sources")
    }
    blockers = []
    if before["game_sha256"] != after["game_sha256"]:
        blockers.append("Supported executable fingerprint changed.")
    changed_signatures = [
        name for name, value in before["signatures"].items() if after["signatures"].get(name) != value
    ]
    if changed_signatures:
        blockers.append(f"{len(changed_signatures)} reviewed signatures changed or disappeared.")
    for name in REQUIRED_EXPORTS:
        if not before["exports"].get(name) or before["exports"].get(name) != after["exports"].get(name):
            blockers.append("Required export missing or declaration changed: " + name)
    for setting in ("coop.online_mode", "coop.developer_input"):
        if after["settings"].get(setting) != "0":
            blockers.append("Default must remain explicitly disabled: " + setting)
    changed = any(item["total"] for item in differences.values())
    status = "incompatible" if blockers else "review_required" if changed else "unchanged"
    return {
        "summary": {
            "status": status,
            "baseline_commit": before["source_commit"],
            "candidate_commit": after["source_commit"],
            "blockers": blockers,
            "changed_categories": {key: value["total"] for key, value in differences.items()},
            "automatic_adoption": False,
            "native_acceptance": "unverified",
        },
        "differences": differences,
        "limitations": [
            "Watched source hashes conservatively flag layout, recorder, guard, loader, settings and build changes; they are not compiled ABI analysis.",
            "Unchanged means no drift in this reviewed contract, not gameplay compatibility. Unwatched code and indirect dependencies may still affect behavior.",
            "At most 100 changes per category are shown; totals and truncation remain explicit.",
        ],
    }


class Compatibility:
    def __init__(self, config, source, artifacts, contract=None):
        self.config, self.source, self.artifacts = config, source, artifacts
        self.contract = (
            contract
            if contract is not None
            else read_json(Path(__file__).with_name("upstream_contract.json"))
        )
        self.cache = {}
        self.lock = threading.RLock()

    def evaluate(self, candidate_commit=None):
        with self.lock:
            return self._evaluate(candidate_commit)

    def _evaluate(self, candidate_commit):
        self.source.verify()
        if (
            self.contract.get("schema_version") != 1
            or self.contract.get("source_commit") != self.source.commit
        ):
            raise ToolFailure(
                "contract_mismatch", "Reviewed compatibility contract differs from the configured source pin."
            )
        candidate_commit = (
            candidate_commit or self.source.git("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        )
        if not re.fullmatch(r"[0-9a-f]{40}", candidate_commit):
            raise ToolFailure("invalid_revision", "Use a full immutable 40-character commit SHA.")
        if candidate_commit not in self.cache:
            candidate = Source(self.config)
            candidate.commit = candidate_commit
            if len(self.cache) >= 16:
                del self.cache[next(iter(self.cache))]
            self.cache[candidate_commit] = compare_contracts(self.contract, capture_contract(candidate))
        return self.cache[candidate_commit]

    def status(self):
        try:
            return self.evaluate()["summary"]
        except ToolFailure as exc:
            return {
                "status": "unavailable",
                "code": exc.code,
                "message": str(exc),
                "automatic_adoption": False,
            }

    def check(self, candidate_commit=None):
        data = self.evaluate(candidate_commit)
        return {
            **self.artifacts.put(
                "upstream_compatibility",
                data,
                {
                    "source_commit": self.source.commit,
                    "candidate_commit": data["summary"]["candidate_commit"],
                    "evidence_class": "static",
                    "dirty_inputs_used": False,
                },
            ),
            "summary": data["summary"],
        }
