"""PE analysis adapted from Thingolus's DDDA inspect_game/static_probe helpers."""

import hashlib
import re
import struct

import pefile
from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from .common import ToolFailure
from .config import GAME_SHA256, Config


class Binary:
    def __init__(self, config: Config):
        self.config = config

    def path(self):
        path = self.config.game / "DDDA.exe"
        if not path.is_file():
            raise ToolFailure("game_missing", "DDDA.exe was not found in configured game_root.")
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ToolFailure("binary_too_large", "Executable exceeds the 128 MiB analysis limit.")
        return path

    def inventory(self) -> dict:
        path = self.path()
        raw = path.read_bytes()
        try:
            with pefile.PE(data=raw, fast_load=True) as pe:
                sha = hashlib.sha256(raw).hexdigest()
                return {
                    "filename": path.name,
                    "sha256": sha,
                    "size_bytes": len(raw),
                    "architecture": "x86" if pe.FILE_HEADER.Machine == 0x14C else "other",
                    "image_base": hex(pe.OPTIONAL_HEADER.ImageBase),
                    "entry_point_rva": hex(pe.OPTIONAL_HEADER.AddressOfEntryPoint),
                    "adapter_supported": sha == self.config.settings.expected_game_sha256 == GAME_SHA256
                    and pe.FILE_HEADER.Machine == 0x14C,
                    "sections": [
                        {
                            "name": s.Name.rstrip(b"\0").decode(errors="replace"),
                            "rva": hex(s.VirtualAddress),
                            "raw_bytes": s.SizeOfRawData,
                        }
                        for s in pe.sections
                    ],
                    "evidence_class": "static",
                    "native_acceptance": "unverified",
                }
        except pefile.PEFormatError as exc:
            raise ToolFailure("invalid_pe", "Configured DDDA.exe is not a valid PE file.") from exc

    def inspect(self, mode: str, value: str, size: int = 128, offset: int = 0, limit: int = 25) -> dict:
        if not 1 <= size <= 1024 or not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise ToolFailure("invalid_parameters", "size 1–1024, limit 1–100, offset 0–10000 required.")
        if mode not in {"bytes", "disassembly", "strings", "references"}:
            raise ToolFailure("invalid_parameters", "Unsupported static analysis mode.")
        path = self.path()
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        try:
            pe = pefile.PE(data=raw, fast_load=True)
        except pefile.PEFormatError as exc:
            raise ToolFailure("invalid_pe", "Cannot parse executable.") from exc
        with pe:
            if pe.FILE_HEADER.Machine != 0x14C:
                raise ToolFailure("unsupported_architecture", "Static disassembler targets x86 DDDA.")
            base = pe.OPTIONAL_HEADER.ImageBase
            rows = []
            address = None
            if mode != "strings":
                try:
                    address = int(value, 0)
                except ValueError as exc:
                    raise ToolFailure("invalid_address", "Use an RVA such as 0x751ee0.") from exc
                if not 0 <= address < pe.OPTIONAL_HEADER.SizeOfImage:
                    raise ToolFailure("invalid_address", "RVA is outside the executable image.")
            elif not value or len(value) > 128:
                raise ToolFailure("invalid_parameters", "Provide a literal string of 1–128 characters.")
            if mode in {"bytes", "disassembly"}:
                section = pe.get_section_by_rva(address)
                if section is None or address + size > section.VirtualAddress + section.SizeOfRawData:
                    raise ToolFailure("invalid_address", "Requested bytes cross an unbacked PE region.")
                data = pe.get_data(address, size)
                if mode == "bytes":
                    rows = [{"rva": hex(address), "bytes": data.hex(" ")}]
                else:
                    for instruction in Cs(CS_ARCH_X86, CS_MODE_32).disasm(data, base + address):
                        rows.append(
                            {
                                "rva": hex(instruction.address - base),
                                "va": hex(instruction.address),
                                "bytes": instruction.bytes.hex(" "),
                                "mnemonic": instruction.mnemonic,
                                "operands": instruction.op_str,
                            }
                        )
            else:
                for section in pe.sections:
                    data = section.get_data()
                    if mode == "strings":
                        iterator = (
                            m
                            for m in re.finditer(rb"[ -~]{4,}\x00", data)
                            if value.lower() in m.group()[:-1].decode("ascii").lower()
                        )
                    else:
                        iterator = re.finditer(re.escape(struct.pack("<I", base + address)), data)
                    for match in iterator:
                        row = {"rva": hex(section.VirtualAddress + match.start())}
                        if mode == "strings":
                            row["text"] = match.group()[:-1].decode("ascii")[:200]
                        else:
                            row["evidence"] = (
                                "candidate encoded absolute address; not a decoded code reference"
                            )
                        rows.append(row)
                        if len(rows) >= offset + limit + 1:
                            break
                    if len(rows) >= offset + limit + 1:
                        break
            return {
                "mode": mode,
                "game_sha256": sha,
                "address_format": "input RVA; VA = image_base + RVA",
                "results": rows[offset : offset + limit],
                "next_offset": offset + limit if len(rows) > offset + limit else None,
                "evidence_class": "static",
            }
