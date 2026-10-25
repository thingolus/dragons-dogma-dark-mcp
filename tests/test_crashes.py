"""Synthetic minidumps and redaction checks; no game memory fixtures."""

import struct

import pytest

from ddda_mcp.common import ToolFailure
from ddda_mcp.crashes import dump_summary, fingerprint


def minidump():
    raw = bytearray(400)
    raw[:4] = b"MDMP"
    struct.pack_into("<II", raw, 8, 2, 32)
    struct.pack_into("<III", raw, 32, 4, 112, 56)
    struct.pack_into("<III", raw, 44, 6, 168, 168)
    struct.pack_into("<I", raw, 56, 1)
    struct.pack_into("<Q4I", raw, 60, 0x400000, 0x1000, 0, 123, 336)
    name = "C:\\private\\DDDA.exe".encode("utf-16-le")
    struct.pack_into("<I", raw, 336, len(name))
    raw[340 : 340 + len(name)] = name
    struct.pack_into("<I", raw, 168, 7)
    struct.pack_into("<I", raw, 176, 0xC0000005)
    struct.pack_into("<Q", raw, 192, 0x400020)
    return raw


def test_dump_resolves_module_rva_without_exposing_paths_or_raw_bases():
    result = dump_summary(minidump())
    assert result["exception"] == {"thread": 7, "code": "0xc0000005", "module": "DDDA.exe", "rva": 32}
    assert result["modules"] == [{"name": "DDDA.exe", "bytes": 4096, "timestamp": 123}]
    assert fingerprint(result) == fingerprint(result)
    assert fingerprint({"type": "unknown", "location": {}}) is None


def test_zero_unused_streams_are_valid():
    raw = bytearray(80)
    raw[:4] = b"MDMP"
    struct.pack_into("<II", raw, 8, 4, 32)
    assert dump_summary(raw)["streams"] == []


@pytest.mark.parametrize("change", ["magic", "streams", "directory", "module_count", "name", "exception"])
def test_dump_rejects_invalid_extents(change):
    raw = minidump()
    if change == "magic":
        raw[0] = 0
    elif change == "streams":
        struct.pack_into("<I", raw, 8, 129)
    elif change == "directory":
        struct.pack_into("<I", raw, 12, 399)
    elif change == "module_count":
        struct.pack_into("<I", raw, 56, 2)
    elif change == "name":
        struct.pack_into("<I", raw, 336, 65536)
    else:
        struct.pack_into("<I", raw, 48, 167)
    with pytest.raises(ToolFailure):
        dump_summary(raw)
