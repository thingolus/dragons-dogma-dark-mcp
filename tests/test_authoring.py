"""Synthetic format and workflow tests; no game assets are included."""

import asyncio
import hashlib
import struct
import zlib
from contextlib import contextmanager
from dataclasses import replace

import pytest

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.asset_atlas import AssetAtlas
from ddda_mcp.assets import Assets
from ddda_mcp.common import ToolFailure
from ddda_mcp.game_parameters import GameParameters, parse, patch
from ddda_mcp.textures import decode, from_dds, png, texture, to_dds


def xfs():
    names = b"power\0enabled\0resource\0"
    descriptor = struct.pack("<4I", 4, 0x12345678, 12, 3)
    for offset, kind, size in ((88, 12, 4), (94, 3, 1), (102, 14, 4)):
        descriptor += struct.pack("<IBBH4I", offset, kind, 0, size, 0, 0, 0, 0)
    descriptor += names
    values = struct.pack("<IfIBI", 1, 2.5, 1, 1, 1) + b"synthetic/path\0"
    return (
        struct.pack("<4sHHIII", b"XFS\0", 0x109, 1, 0, 1, len(descriptor))
        + descriptor
        + struct.pack("<HHI", 1, 0, len(values) + 4)
        + values
    )


def tex(bc3=False):
    color = struct.pack("<HHI", 0xF800, 0x07E0, 0)
    payload = (bytes((255, 0)) + b"\0" * 6 if bc3 else b"") + color
    return (
        struct.pack(
            "<4s4I",
            b"TEX\0",
            0x20000099,
            1 + (4 << 6) + (4 << 19),
            1 + ((24 if bc3 else 20) << 8) + (1 << 16),
            20,
        )
        + payload
    )


def arc(entries):
    rows, payload = [], b""
    for name, kind, value in entries:
        packed = zlib.compress(value)
        rows.append(
            struct.pack(
                "<64sIIII", name.encode(), kind, len(packed), len(value), 8 + 80 * len(entries) + len(payload)
            )
        )
        payload += packed
    return b"ARC\0\x07\0" + struct.pack("<H", len(entries)) + b"".join(rows) + payload


def test_xfs_named_lossless_patch():
    raw = xfs()
    meta, fields = parse(raw)
    assert meta["classes"] == 1
    assert [(f.name, f.value) for f in fields] == [
        ("power", 2.5),
        ("enabled", True),
        ("resource", "synthetic/path"),
    ]
    changed, _ = patch(raw, [{"path": "$/0:power", "expected": 2.5, "value": 3.5}])
    assert parse(changed)[1][0].value == 3.5
    restored, _ = patch(changed, [{"path": "$/0:power", "expected": 3.5, "value": 2.5}])
    assert restored == raw


def test_prpz_preserves_opaque_identity_and_adjusts_field_offsets():
    prefix = b"PRPZ" + b"12345678"
    raw = prefix + xfs()
    _, fields = parse(raw)
    assert fields[0].offset == parse(xfs())[1][0].offset + 12
    changed, _ = patch(raw, [{"path": fields[0].path, "expected": 2.5, "value": 3.5}])
    assert changed[:12] == prefix
    assert parse(changed)[1][0].value == 3.5


def test_lot_target_and_schema_boundaries():
    # One target-only record with a null target; no engine relationships editable.
    raw = struct.pack("<4s5I", b"lot\0", 16, 1, 9, 54, 0)
    meta, fields = parse(raw)
    assert meta["records"] == 1
    assert [f.value for f in fields] == [9, 54, 0]
    assert not any(f.storage for f in fields)
    for bad in (raw + b"extra", raw[:-1], raw[:16] + struct.pack("<I", 999) + raw[20:]):
        with pytest.raises(ToolFailure):
            parse(bad)


def test_lot_enemy_stat_edit_preserves_ids_scripts_and_tail():
    # Independently assembled type-3 record in on-disk field order.
    enemy = struct.pack("<iBiBBiiiBBBi", 0, 0, 0, 0, 0, 0, -1, 0, 0, 0, 0, 250) + b"synthetic.fsm\0"
    enemy += struct.pack("<Bfi", 0, 1.0, -1)
    enemy += struct.pack("<BfBfBfBfBf", 1, 2.0, 0, 1.0, 0, 1.0, 0, 1.0, 0, 1.0)
    enemy += struct.pack("<iiBBBi", 0, 0, 0, 0, 0, 42) + b"synthetic enemy\0"
    enemy += struct.pack("<i10fB", 0, -10, 20, 30, 0, 0, 0, 1, 1, 1, 200, 0)
    raw = struct.pack("<4s4I", b"lot\0", 16, 1, 7, 3) + enemy
    _, fields = parse(raw)
    hp = next(f for f in fields if f.name == "mHpRatio")
    changed, _ = patch(raw, [{"path": hp.path, "expected": 2.0, "value": 3.0}])
    assert changed[: hp.offset] == raw[: hp.offset] and changed[hp.offset + 4 :] == raw[hp.offset + 4 :]
    assert next(f for f in parse(changed)[1] if f.name == "mHpRatio").value == 3.0
    reference = next(f for f in fields if f.name == "mSetID")
    with pytest.raises(ToolFailure):
        patch(raw, [{"path": reference.path, "expected": 42, "value": 43}])


@pytest.mark.parametrize("mutation", ["truncate", "version", "extent", "class", "count", "name", "nonfinite"])
def test_xfs_rejects_corruption(mutation):
    raw = bytearray(xfs())
    if mutation == "truncate":
        raw = raw[:-1]
    if mutation == "version":
        struct.pack_into("<H", raw, 4, 999)
    if mutation == "extent":
        struct.pack_into("<I", raw, 16, 0xFFFFFFFF)
    if mutation == "class":
        struct.pack_into("<I", raw, 20, 0xFFFFFFFF)
    if mutation == "name":
        struct.pack_into("<I", raw, 36, 0xFFFFFFFF)
    payload = 20 + struct.unpack_from("<I", raw, 16)[0]
    if mutation == "count":
        struct.pack_into("<I", raw, payload + 8, 9999)
    if mutation == "nonfinite":
        struct.pack_into("<f", raw, payload + 12, float("nan"))
    with pytest.raises(ToolFailure):
        parse(bytes(raw))


@pytest.mark.parametrize(
    "edit",
    [
        {"path": "$/0:power", "expected": 9.0, "value": 3.0},
        {"path": "$/0:power", "expected": 2.5, "value": float("inf")},
        {"path": "$/1:enabled", "expected": True, "value": 1},
        {"path": "$/2:resource", "expected": "synthetic/path", "value": "changed"},
        {"path": "$/missing", "expected": 0, "value": 1},
    ],
)
def test_parameter_invalid_edits(edit):
    with pytest.raises(ToolFailure):
        patch(xfs(), [edit])


def test_cumulative_parameter_merging(development):
    assets = Assets(development, Artifacts(development))
    params = GameParameters(assets)
    base = assets.blob(xfs())["artifact_id"]
    a = params.edit(base, [dict(path="$/0:power", expected=2.5, value=4.0)])["artifact_id"]
    b = params.edit(base, [dict(path="$/1:enabled", expected=True, value=False)])["artifact_id"]
    merged = params.merge(a, b)["artifact_id"]
    assert params.diff(base, merged)["total"] == 2
    c = params.edit(a, [dict(path="$/0:power", expected=4.0, value=5.0)])["artifact_id"]
    assert params.inspect(c)["fields"][0]["value"] == 5
    with pytest.raises(ToolFailure, match="Conflicting"):
        params.merge(a, c)


def test_skill_costs_and_id_preservation():
    raw = b"skl\0\0\x02\0\0" + struct.pack("<4i", 1, 9, 100, 2) + struct.pack("<2I", 0, 0)
    changed, _ = patch(raw, [dict(path="$/normal/0/mJobPoint", expected=100, value=120)])
    assert parse(changed)[1][1].value == 120
    with pytest.raises(ToolFailure):
        patch(raw, [dict(path="$/normal/0/mSkillId", expected=9, value=10)])
    with pytest.raises(ToolFailure):
        patch(raw, [dict(path="$/normal/0/mJobLevel", expected=2, value=10)])


def test_loot_probabilities_and_structure():
    raw = b"ist\0" + struct.pack("<II20h", 0, 1, 7, -1, 1, 1, *([43] + [-1] * 7), *([100] + [0] * 7))
    changed, _ = patch(raw, [dict(path="$/0/mItemGetProbability/0", expected=100, value=90)])
    assert parse(changed)[1][-8].value == 90
    with pytest.raises(ToolFailure):
        patch(raw, [dict(path="$/0/mItemGetProbability/0", expected=100, value=101)])


@pytest.mark.parametrize("bc3", [False, True])
def test_texture_roundtrip_and_known_pixels(bc3):
    raw = tex(bc3)
    assert from_dds(raw, to_dds(raw)) == raw
    w, h, rgba = decode(raw)
    assert (w, h) == (4, 4) and rgba == bytes((255, 0, 0, 255)) * 16
    assert png(w, h, rgba).startswith(b"\x89PNG\r\n\x1a\n")
    modified = bytearray(to_dds(raw))
    modified[-8:-4] = struct.pack("<HH", 0x001F, 0x07E0)
    changed = from_dds(raw, modified)
    assert changed[:20] == raw[:20]
    assert decode(changed)[2] == bytes((0, 0, 255, 255)) * 16


@pytest.mark.parametrize("mutation", ["mips", "surface", "format", "offset", "trailing"])
def test_texture_rejects_unsupported_or_corrupt(mutation):
    raw = bytearray(tex())
    if mutation == "mips":
        raw[8] = 0
    if mutation == "surface":
        raw[12] = 6
    if mutation == "format":
        raw[13] = 0xFF
    if mutation == "offset":
        struct.pack_into("<I", raw, 16, 0)
    if mutation == "trailing":
        raw += b"!"
    with pytest.raises(ToolFailure):
        texture(raw)


def test_dds_shape_mismatch():
    dds = bytearray(to_dds(tex()))
    struct.pack_into("<I", dds, 16, 8)
    with pytest.raises(ToolFailure):
        from_dds(tex(), dds)


def test_index_duplicates_extraction_staleness(development, monkeypatch):
    root = development.game / "nativePC"
    root.mkdir()
    one = arc([("synthetic/path", 1, b"hello"), ("parameters", 2, xfs())])
    (root / "one.arc").write_bytes(one)
    (root / "two.arc").write_bytes(arc([("synthetic/path", 1, b"different")]))
    assets = Assets(development, Artifacts(development))
    atlas = AssetAtlas(assets)
    index = asyncio.run(atlas.build())["artifact_id"]
    results = atlas.search(index, duplicates_only=True)
    assert results["total"] == 2
    row = atlas.search(index, "parameters")["assets"][0]
    entry = atlas.extract(index, row["id"])["artifact_id"]
    refs = atlas.references(index, entry)
    assert len(refs["references"][0]["matches"]) == 2
    original_connect = atlas.connect
    queries = []

    @contextmanager
    def traced_connect(ident):
        with original_connect(ident) as db:
            db.set_trace_callback(queries.append)
            yield db

    reference = parse(xfs())[1][-1]
    many_references = [replace(reference, path=f"$/resource/{i}") for i in range(1000)]
    with monkeypatch.context() as scoped:
        scoped.setattr("ddda_mcp.asset_atlas.parse", lambda raw: ({}, many_references))
        scoped.setattr(atlas, "connect", traced_connect)
        page = atlas.references(index, entry, offset=24, limit=2)
    assert page["total"] == 1000 and page["next_offset"] == 26
    assert [row["field"] for row in page["references"]] == ["$/resource/24", "$/resource/25"]
    assert len(queries) == 2  # Unrequested pages must not resolve or materialize their matches.
    changed = bytearray(one)
    changed[8] = ord("X")
    (root / "one.arc").write_bytes(changed)
    with pytest.raises(ToolFailure, match="changed"):
        atlas.extract(index, row["id"])
    (root / "one.arc").write_bytes(one)
    original_open = assets.open

    def changed_during_open(path):
        (root / "one.arc").write_bytes(changed)
        return original_open(path)

    monkeypatch.setattr(assets, "open", changed_during_open)
    with pytest.raises(ToolFailure, match="during extraction"):
        atlas.extract(index, row["id"])


def test_texture_named_import(development):
    from ddda_mcp.textures import Textures

    assets = Assets(development, Artifacts(development))
    textures = Textures(assets)
    entry = assets.blob(tex())["artifact_id"]
    result = textures.export(entry)
    root = development.root / "input"
    root.mkdir()
    dds = to_dds(tex())
    (root / "edit.dds").write_bytes(dds)
    development.settings.mod_sources = {"art": str(root)}
    imported = textures.replace(entry, "art", "edit.dds", hashlib.sha256(dds).hexdigest())
    assert assets.read(imported["artifact_id"])[1] == tex()
    assert result["spec"]["fourcc"] == "DXT1"
    with pytest.raises(ToolFailure):
        textures.replace(entry, "art", "../edit.dds", hashlib.sha256(dds).hexdigest())
