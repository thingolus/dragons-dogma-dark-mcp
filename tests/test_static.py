import io
import json
import tarfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from ddda_mcp.binary import Binary
from ddda_mcp.build import unpack_archive
from ddda_mcp.common import ToolFailure, atomic_json, contained
from ddda_mcp.config import Config, Settings
from ddda_mcp.knowledge import Knowledge
from ddda_mcp.source import Source


def test_manifest_and_immutable_reader(config):
    source = Source(config)
    assert source.verify()["verified_files"] == 6
    path = config.source / "src/example.cpp"
    before = path.read_bytes()
    try:
        path.write_text("UNCOMMITTED CHANGE")
        assert "return 42" in source.read("src/example.cpp")
    finally:
        path.write_bytes(before)


def test_manifest_tampering_refused(config):
    path = config.root / "reuse-manifest.json"
    manifest = json.loads(path.read_text())
    manifest["components"][0]["files"][0]["git_blob_sha1"] = "0" * 40
    atomic_json(path, manifest)
    with pytest.raises(ToolFailure, match="mismatch"):
        Source(config).verify()


def test_paginated_source_rejects_unknown_path(config):
    source = Source(config)
    page = source.read_lines("src/example.cpp", 1, 1)
    assert page["next_line"] == 2
    assert page["source"]["commit"] == config.settings.coop_source_commit
    with pytest.raises(ToolFailure):
        source.read_lines("../../secrets.md", 1, 20)


def test_fts_search_and_symbol_merge(config):
    knowledge = Knowledge(Source(config))
    result = knowledge.search("pawn ownership", limit=1)
    assert len(result["results"]) == 1
    assert result["next_offset"] == 1
    assert "commit" in result["results"][0]["source"]
    symbol = knowledge.lookup("pawn_movement_consume")["symbols"][0]
    assert symbol["runtime_signature"]["bytes"] == "55 8b ec c3"
    assert symbol["research"]["status"] == "live-observed"
    assert knowledge.lookup("0x1000")["total_matches"] == 1


@pytest.mark.parametrize("query", ["", "*", "x" * 300, " ".join(["word"] * 21)])
def test_search_rejects_invalid_queries(config, query):
    with pytest.raises(ToolFailure):
        Knowledge(Source(config)).search(query)


def test_search_sql_metacharacters_are_data(config):
    result = Knowledge(Source(config)).search('pawn OR "DROP TABLE passages"')
    assert result["results"] == []
    assert Knowledge(Source(config)).search("ownership")["results"]


def test_concurrent_index_creation(config):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Knowledge(Source(config)).search("ownership"), range(2)))
    assert all(result["results"] for result in results)


def test_unknown_executable_static_analysis(pe):
    binary = Binary(pe)
    assert binary.inventory()["adapter_supported"] is False
    disasm = binary.inspect("disassembly", "0x1000", size=4)
    assert [row["mnemonic"] for row in disasm["results"]] == ["push", "mov", "ret"]
    assert binary.inspect("strings", "Thingolus")["results"]
    assert binary.inspect("references", "0x1000")["results"][0]["rva"] == "0x1058"


@pytest.mark.parametrize("value,size", [("-1", 1), ("0x999999", 1), ("0x11ff", 10), ("hello", 1)])
def test_invalid_pe_ranges(pe, value, size):
    with pytest.raises(ToolFailure):
        Binary(pe).inspect("bytes", value, size)


def test_malformed_pe(config):
    (config.game / "DDDA.exe").write_bytes(b"garbage")
    with pytest.raises(ToolFailure, match="valid PE"):
        Binary(config).inventory()


def test_generated_paths_cannot_escape(config):
    with pytest.raises(ToolFailure):
        Config(config.root, Settings(artifact_root="../outside"))
    with pytest.raises(ToolFailure):
        contained(config.root, config.root / "../outside")


def test_archive_traversal_refused(tmp_path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo("../outside")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ToolFailure):
        unpack_archive(data.getvalue(), tmp_path / "inside")
    assert not (tmp_path / "outside").exists()


def test_archive_symlinks_refused(tmp_path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as archive:
        member = tarfile.TarInfo("link")
        member.type = tarfile.SYMTYPE
        member.linkname = "outside"
        archive.addfile(member)
    with pytest.raises(ToolFailure):
        unpack_archive(data.getvalue(), tmp_path / "inside")
