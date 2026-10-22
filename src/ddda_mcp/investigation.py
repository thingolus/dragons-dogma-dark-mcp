"""Bounded static investigation bundles. Copyright (c) 2026 Thingolus. MIT."""

import asyncio
import hashlib
import struct

import pefile

from .common import ToolFailure


def candidate_calls(raw, target_rva, limit=20, byte_budget=16 * 1024 * 1024):
    """E8 matches are candidates: executable sections can also contain data."""
    rows, scanned, examined, truncated = [], 0, 0, False
    with pefile.PE(data=raw, fast_load=True) as pe:
        if pe.FILE_HEADER.Machine != 0x14C:
            raise ToolFailure("unsupported_architecture", "Call scan requires x86.")
        for section in pe.sections:
            if not section.Characteristics & 0x20000000:
                continue
            remaining = byte_budget - scanned
            data = section.get_data()[:remaining]
            scanned += len(data)
            truncated |= len(data) < section.SizeOfRawData
            offset = 0
            while (offset := data.find(b"\xe8", offset)) >= 0:
                if offset + 5 > len(data):
                    break
                examined += 1
                address = section.VirtualAddress + offset
                if (address + 5 + struct.unpack_from("<i", data, offset + 1)[0]) & 0xFFFFFFFF == target_rva:
                    rows.append(
                        {
                            "callsite_rva": hex(address),
                            "target_rva": hex(target_rva),
                            "evidence": "candidate E8 rel32 encoding; instruction boundary and containing function unverified",
                        }
                    )
                    if len(rows) >= limit:
                        return {"results": rows, "truncated": True, "scanned_bytes": scanned}
                offset += 1
                if examined >= 100000:
                    return {"results": rows, "truncated": True, "scanned_bytes": scanned}
            if scanned >= byte_budget:
                truncated = True
                break
    return {
        "results": rows,
        "truncated": truncated,
        "scanned_bytes": scanned,
        "scope": "Direct relative calls only; indirect calls and complete caller coverage are unavailable.",
    }


class Investigations:
    def __init__(self, config, source, knowledge, binary, builds, artifacts):
        self.config, self.source, self.knowledge = config, source, knowledge
        self.binary, self.builds, self.artifacts = binary, builds, artifacts

    def collect(self, name, query):
        self.source.verify()
        symbol = next((s for s in self.source.symbols() if s["name"] == name), None)
        if not symbol:
            raise ToolFailure(
                "symbol_not_found", "Use an exact known symbol name; lookup_symbol lists candidates."
            )
        evidence = self.knowledge.search(query or name.replace("_", " "), limit=5)
        excerpts = []
        for ref in symbol["sources"][:2]:
            line = ref["line"]
            if ref["path"].endswith(".csv"):
                line = next(
                    (
                        i + 1
                        for i, text in enumerate(self.source.read(ref["path"]).splitlines())
                        if text.startswith(name + ",")
                    ),
                    line,
                )
            excerpts.append(self.source.read_lines(ref["path"], max(1, line - 2), 8))
        result = {
            "symbol": symbol,
            "research": evidence,
            "source_excerpts": excerpts,
            "unavailable": [],
            "limitations": [
                "Historical research claims retain their original evidence scope.",
                "Candidate call encodings are not a verified call graph.",
                "Static analysis cannot establish gameplay behavior.",
            ],
        }
        try:
            info = self.binary.inventory()
            result["build"] = info
            if not info["adapter_supported"]:
                raise ToolFailure(
                    "unsupported_build", "Pinned symbol addresses require the supported executable."
                )
            address = symbol.get("runtime_signature", {}).get("rva") or symbol.get("research", {}).get("rva")
            if not address:
                raise ToolFailure("symbol_address_missing", "No reviewed RVA is recorded for this symbol.")
            result["disassembly"] = self.binary.inspect("disassembly", address, 64, limit=20)
            result["absolute_references"] = self.binary.inspect("references", address, limit=20)
            raw = self.binary.path().read_bytes()
            if (
                any(
                    part["game_sha256"] != info["sha256"]
                    for part in (result["disassembly"], result["absolute_references"])
                )
                or hashlib.sha256(raw).hexdigest() != info["sha256"]
            ):
                raise ToolFailure("input_changed", "Executable changed while collecting the bundle.")
            result["candidate_callers"] = candidate_calls(raw, int(address, 16))
        except ToolFailure as exc:
            if exc.code == "input_changed":
                raise
            result["unavailable"].append({"component": "binary", "code": exc.code, "message": str(exc)})
        return result

    async def bundle(self, symbol_name, query="", include_decompilation=False):
        if include_decompilation:
            self.config.require_development()
        data = await asyncio.to_thread(self.collect, symbol_name, query)
        if include_decompilation:
            try:
                receipt = await self.builds.decompile(symbol_name)
                data["decompilation"] = receipt
                if not receipt["summary"]["passed"]:
                    data["unavailable"].append({"component": "decompilation", "code": "export_failed"})
            except ToolFailure as exc:
                data["unavailable"].append(
                    {"component": "decompilation", "code": exc.code, "message": str(exc)}
                )
        else:
            data["decompilation"] = {"requested": False}
        summary = {
            "symbol": symbol_name,
            "source_commit": self.source.commit,
            "research_hits": len(data["research"]["results"]),
            "candidate_callers": len(data.get("candidate_callers", {}).get("results", [])),
            "complete": not data["unavailable"],
            "unavailable": data["unavailable"],
            "native_acceptance": "unverified",
        }
        data["summary"] = summary
        receipt = self.artifacts.put(
            "investigation",
            data,
            {
                "source_commit": self.source.commit,
                "game_sha256": data.get("build", {}).get("sha256"),
                "symbol": symbol_name,
                "evidence_class": "static",
                "recipe": "investigate_symbol",
            },
        )
        return {**receipt, "summary": summary}
