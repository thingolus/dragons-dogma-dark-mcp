"""Offline comparisons of immutable source revisions and named build payloads."""

import configparser
import difflib
import hashlib
import re

import pefile

from .common import ToolFailure, contained, read_json
from .deployment import LOADERS, PAYLOAD_NAMES, installed
from .source import Source


def changes(before, after, limit=100):
    names = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    return {
        "total": len(names),
        "truncated": len(names) > limit,
        "items": [{"name": k, "before": before.get(k), "after": after.get(k)} for k in names[:limit]],
    }


def pe_summary(raw):
    try:
        with pefile.PE(data=raw, fast_load=True) as pe:
            pe.parse_data_directories(directories=[0, 1])
            exports = {
                s.name.decode(errors="replace") if s.name else f"ordinal:{s.ordinal}": {
                    "rva": hex(s.address),
                    "ordinal": s.ordinal,
                    "forwarder": s.forwarder.decode(errors="replace") if s.forwarder else None,
                }
                for s in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])
            }
            imports = {
                item.dll.decode(errors="replace"): sorted(
                    s.name.decode(errors="replace") if s.name else f"ordinal:{s.ordinal}"
                    for s in item.imports
                )
                for item in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])
            }
            if len(exports) > 4096 or sum(len(x) for x in imports.values()) > 16384:
                raise ToolFailure("comparison_limit", "PE import/export inventory is too large.")
            sections = {
                f"{i}:{s.Name.rstrip(bytes([0])).decode(errors='replace')}": {
                    "rva": hex(s.VirtualAddress),
                    "raw_bytes": s.SizeOfRawData,
                    "sha256": hashlib.sha256(s.get_data()).hexdigest(),
                }
                for i, s in enumerate(pe.sections)
            }
            return {
                "machine": hex(pe.FILE_HEADER.Machine),
                "is_dll": bool(pe.FILE_HEADER.Characteristics & 0x2000),
                "image_base": hex(pe.OPTIONAL_HEADER.ImageBase),
                "exports": exports,
                "imports": imports,
                "sections": sections,
            }
    except pefile.PEFormatError as exc:
        raise ToolFailure("invalid_pe", "Named build contains a malformed PE payload.") from exc


def settings_summary(raw):
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw.decode("utf-8-sig"))
    except (UnicodeError, configparser.Error) as exc:
        raise ToolFailure("invalid_settings", "Cannot parse named build settings.") from exc
    return {
        f"{section}.{key}": value for section in parser.sections() for key, value in parser[section].items()
    }


class Comparisons:
    def __init__(self, config, source, artifacts):
        self.config, self.source, self.artifacts = config, source, artifacts

    def revision(self, sha):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ToolFailure("invalid_revision", "Use a full immutable 40-character commit SHA.")
        source = Source(self.config)
        source.commit = sha
        source.tree()  # Resolve exactly; never read dirty checkout contents.
        return source

    def compare_source(self, before_commit, after_commit, offset=0, limit=50):
        if not 0 <= offset <= 10000 or not 1 <= limit <= 50:
            raise ToolFailure("invalid_parameters", "Use offset 0–10000 and limit 1–50.")
        before, after = self.revision(before_commit), self.revision(after_commit)
        old, new = before.tree(), after.tree()
        names = sorted(p for p in old.keys() | new.keys() if old.get(p) != new.get(p))
        rows = []
        for name in names[offset : offset + limit]:
            row = {
                "path": name,
                "before_blob": old.get(name, (None,))[0],
                "after_blob": new.get(name, (None,))[0],
            }
            if (
                name.endswith((".cpp", ".hpp", ".h", ".py", ".js", ".ini", ".json", ".txt", ".md", ".csv"))
                and max(old.get(name, (None, 0))[1], new.get(name, (None, 0))[1]) <= 64 * 1024
            ):
                a = before.read(name).splitlines() if name in old else []
                b = after.read(name).splitlines() if name in new else []
                if max(len(a), len(b)) > 2000:
                    row["content_status"] = "hash comparison only; over 2000 lines"
                    rows.append(row)
                    continue
                diff = list(
                    difflib.unified_diff(a, b, fromfile="before/" + name, tofile="after/" + name, n=2)
                )
                row["diff_excerpt"] = "\n".join(diff[:150])[:6000]
                row["diff_truncated"] = len(diff) > 150 or len("\n".join(diff[:150])) > 6000
                function = re.compile(r"^\s*(?:[\w:<>&*~]+\s+)+([\w:~]+)\s*\([^;]*\)\s*(?:const\s*)?\{")
                contexts = set()
                for tag, i, j, k, end in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
                    if tag == "equal":
                        continue
                    for lines, begin, finish in ((a, i, j), (b, k, end)):
                        candidates = [(n, function.match(line)) for n, line in enumerate(lines[: finish + 1])]
                        candidates = [(n, match.group(1)) for n, match in candidates if match]
                        preceding = [item for item in candidates if item[0] <= begin]
                        contexts.update(
                            name
                            for _, name in (preceding[-1:] + [item for item in candidates if item[0] > begin])
                        )
                row["candidate_function_contexts"] = sorted(contexts)[:20]
            else:
                row["content_status"] = "hash comparison only; binary, unrecognized text or over 64 KiB"
            rows.append(row)
        signature_maps = []
        for source in (before, after):
            if {"research/symbols.csv", "include/coop/supported_build.hpp"} <= source.tree().keys():
                signature_maps.append(
                    {
                        s["name"]: s.get("runtime_signature")
                        for s in source.symbols()
                        if "runtime_signature" in s
                    }
                )
            else:
                signature_maps.append(None)
        signatures = (
            changes(*signature_maps) if all(m is not None for m in signature_maps) else {"unavailable": True}
        )
        risks = []
        if any("runtime_status" in p or "supported_build" in p for p in names):
            risks.append(
                "Runtime ABI or signature source changed; review adapter layout and fingerprint assumptions."
            )
        if any("settings" in p or p.endswith(".ini") for p in names):
            risks.append("Settings definitions changed; review offline/developer defaults.")
        data = {
            "summary": {
                "changed_files": len(names),
                "reported_files": len(rows),
                "truncated": offset > 0 or offset + len(rows) < len(names),
                "offset": offset,
                "next_offset": offset + len(rows) if offset + len(rows) < len(names) else None,
                "risks": risks,
            },
            "files": rows,
            "signature_changes": signatures,
            "limitations": [
                "Function contexts are lexical candidates, not semantic change detection.",
                "Source comparison does not prove binary or gameplay compatibility.",
            ],
        }
        return {
            **self.artifacts.put(
                "source_comparison",
                data,
                {
                    "before_commit": before_commit,
                    "after_commit": after_commit,
                    "evidence_class": "static",
                    "dirty_inputs_used": False,
                },
            ),
            "summary": data["summary"],
        }

    def snapshot_build(self, name):
        if name == "installed":
            root, manifest = self.config.game, installed(self.config)
            expected_game = manifest["exe_sha256"]
        else:
            value = self.config.settings.analysis_builds.get(
                name
            ) or self.config.settings.deployment_candidates.get(name)
            if value is None:
                raise ToolFailure(
                    "build_unknown",
                    "Select installed or a named analysis_builds/deployment_candidates directory.",
                )
            root = (self.config.root / value).resolve()
            manifest = read_json(root / "candidate.json", 65536)
            expected_game = manifest.get("game_sha256")
        files = manifest.get("files", {})
        if not isinstance(expected_game, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_game):
            raise ToolFailure("candidate_invalid", "Expected a SHA-256 target executable identity.")
        if (
            len(files) != 3
            or set(files) - PAYLOAD_NAMES
            or len(set(files) & LOADERS) != 1
            or not {"ddcoop_runtime.dll", "ddcoop.ini"} <= files.keys()
        ):
            raise ToolFailure(
                "candidate_invalid", "Expected one loader, runtime DLL and settings with exact hashes."
            )
        records = {}
        for filename, sha in files.items():
            path = contained(root, root / filename)
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ToolFailure("comparison_limit", "Build file exceeds 64 MiB.")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha:
                raise ToolFailure("candidate_changed", "Named build changed from its manifest.")
            records[filename] = (
                {"sha256": sha, "size_bytes": len(raw), "pe": pe_summary(raw)}
                if filename.endswith(".dll")
                else {"sha256": sha, "settings": settings_summary(raw)}
            )
        return {
            "name": name,
            "game_sha256": expected_game,
            "files": records,
            "source_commit": manifest.get("source_commit"),
            "source_provenance": "Manifest declaration only; not proof of compilation provenance.",
        }

    def compare_builds(self, before_name, after_name):
        before, after = self.snapshot_build(before_name), self.snapshot_build(after_name)
        rows, risks = [], []
        if before["game_sha256"] != after["game_sha256"]:
            risks.append("Target executable fingerprints differ.")
        for name in sorted(before["files"].keys() | after["files"].keys()):
            a, b = before["files"].get(name), after["files"].get(name)
            row = {
                "name": name,
                "before_sha256": a["sha256"] if a else None,
                "after_sha256": b["sha256"] if b else None,
                "changed": a != b,
            }
            if not a or not b:
                risks.append(
                    f"Payload added/removed: {name}; loader changes need separate deployment review."
                )
            elif name.endswith(".dll"):
                row.update(
                    {key: changes(a["pe"][key], b["pe"][key]) for key in ("exports", "imports", "sections")}
                )
                row["machine"] = [a["pe"]["machine"], b["pe"]["machine"]]
                if b["pe"]["machine"] != "0x14c":
                    risks.append(f"{name}: after build is not x86.")
                if not b["pe"]["is_dll"]:
                    risks.append(f"{name}: PE is not marked as a DLL.")
                required = (
                    {"CoopInitialize", "CoopGetStatus", "OfflineState"}
                    if name == "ddcoop_runtime.dll"
                    else {"DirectInput8Create" if name == "dinput8.dll" else "XInputGetState"}
                )
                if not required <= b["pe"]["exports"].keys():
                    risks.append(f"{name}: required adapter exports are missing.")
                if a["pe"]["image_base"] != b["pe"]["image_base"]:
                    risks.append(f"{name}: preferred image base changed; address assumptions need review.")
                removed = set(a["pe"]["exports"]) - set(b["pe"]["exports"])
                if removed:
                    risks.append(f"{name}: {len(removed)} exports removed; callers may fail to load.")
            else:
                row["settings"] = changes(a["settings"], b["settings"])
                if b["settings"].get("coop.online_mode") != "0":
                    risks.append("After settings do not explicitly enforce coop.online_mode=0.")
                if a["settings"].get("coop.developer_input") != b["settings"].get("coop.developer_input"):
                    risks.append("Developer input setting changed.")
            rows.append(row)
        summary = {
            "changed_payloads": sum(r["changed"] for r in rows),
            "risks": risks,
            "deployment_approved": False,
            "native_acceptance": "unverified",
        }
        return {
            **self.artifacts.put(
                "build_comparison",
                {
                    "summary": summary,
                    "files": rows,
                    "limitations": [
                        "Export RVAs and section hashes do not identify all changed function bodies.",
                        "No PDB, ABI-layout or gameplay compatibility proof; no deployment performed.",
                    ],
                },
                {"before": before, "after": after, "evidence_class": "static"},
            ),
            "summary": summary,
        }
