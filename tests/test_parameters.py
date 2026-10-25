"""Synthetic item layouts and private profile round trips. No installed game writes."""

import asyncio
import struct
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.assets import Assets, arc_table, unpack_entry
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.mods import Mods
from ddda_mcp.parameters import STRIDE, VERSION, Parameters, edit_table, read_item, table


def item_table(count=4):
    raw = bytearray(b"ITL2" + struct.pack("<III", VERSION, count, 0))
    for i in range(count):
        base = len(raw)
        raw.extend(bytes([0xA5]) * STRIDE)  # Nonzero unknown data must survive edits.
        struct.pack_into("<I", raw, base, 100 | (200 << 11) | (30 << 22))
        struct.pack_into("<I", raw, base + 4, 120 | (230 << 10) | 0xABC00000)
        struct.pack_into("<I", raw, base + 60, i | (8191 << 13) | 0xB4000000)
        struct.pack_into("<fii", raw, base + 68, 0.5, 100, 40)
        struct.pack_into("<hh", raw, base + 112, 120, 20)
    return bytes(raw)


@pytest.fixture
def services(development):
    assets = Assets(development, Artifacts(development))
    return assets, Parameters(assets), Mods(development, assets.artifacts, assets)


def edit(field="mAttack", expected=100, value=200, item_id=0):
    return {"item_id": item_id, "field": field, "expected": expected, "value": value}


def test_packed_fields_preserve_other_fields_unknown_bits_header_and_records():
    original = item_table()
    changed, changes = edit_table(original, [edit()])
    assert len(changes) == 1
    assert read_item(changed, 0)["fields"]["mAttack"] == 200
    assert read_item(changed, 0)["fields"]["mMagicAttack"] == 200
    assert read_item(changed, 0)["fields"]["mElementAttack"] == 30
    assert changed[:16] == original[:16] and changed[20:] == original[20:]
    delta = struct.unpack_from("<I", original, 16)[0] ^ struct.unpack_from("<I", changed, 16)[0]
    assert delta & ~2047 == 0
    restored, _ = edit_table(changed, [edit(expected=200, value=100)])
    assert restored == original


def test_float_roundtrip_uses_stored_precision_and_does_not_round_unedited_fields():
    original = item_table()
    changed, changes = edit_table(original, [edit("mWeight", 0.5, 0.1)])
    assert changes[0]["value"] == struct.unpack("<f", struct.pack("<f", 0.1))[0]
    restored, _ = edit_table(changed, [edit("mWeight", 0.1, 0.5)])
    assert restored == original


@pytest.mark.parametrize(
    "change", ["magic", "version", "reserved", "short", "trailing", "count", "identity", "reference", "nan"]
)
def test_unknown_or_corrupt_layouts_are_refused(change):
    raw = bytearray(item_table())
    if change == "magic":
        raw[:4] = b"XFS\0"
    elif change == "version":
        struct.pack_into("<I", raw, 4, VERSION + 1)
    elif change == "reserved":
        struct.pack_into("<I", raw, 12, 1)
    elif change == "short":
        raw.pop()
    elif change == "trailing":
        raw.extend(b"\0")
    elif change == "count":
        struct.pack_into("<I", raw, 8, 4097)
    elif change == "identity":
        raw[16 + 60] = 2
    elif change == "reference":
        struct.pack_into("<I", raw, 16 + 60, 5 << 13)
    else:
        struct.pack_into("<f", raw, 16 + 68, float("nan"))
    with pytest.raises(ToolFailure):
        table(raw)


@pytest.mark.parametrize(
    "patch",
    [
        edit(value=2048),
        edit(value=-1),
        edit(value=1.0),
        edit(value=True),
        edit(value=float("nan")),
        edit(expected=99),
        edit(field="unknown_offset"),
        edit(item_id=4),
        edit(item_id=True),
        edit("mWeight", 0.5, -1.0),
        edit("mBuy", 100, 2147483648),
        edit("mAddHp", 120, 32768),
        edit("mAlterItemNo", -1, 4),
        edit("mAlterItemNo", -1, -2),
    ],
)
def test_invalid_conflicting_and_out_of_range_edits_are_refused(patch):
    with pytest.raises(ToolFailure):
        edit_table(item_table(), [patch])


def test_alternate_item_references_and_signed_fields_roundtrip():
    raw = item_table()
    changed, _ = edit_table(raw, [edit("mAlterItemNo", -1, 3), edit("mAddHp", 120, -5)])
    assert read_item(changed, 0)["fields"]["mAlterItemNo"] == 3
    assert read_item(changed, 0)["fields"]["mAddHp"] == -5
    assert (
        struct.unpack_from("<I", changed, 16 + 60)[0] & 0xFC001FFF
        == struct.unpack_from("<I", raw, 16 + 60)[0] & 0xFC001FFF
    )
    with pytest.raises(ToolFailure):
        edit_table(raw, [edit(), edit()])
    with pytest.raises(ToolFailure):
        edit_table(raw, [edit(value=10**1000)])


def test_private_parameter_workspace_diff_and_chained_edit_merge(services):
    assets, parameters, _ = services
    base = assets.blob(item_table())["artifact_id"]
    first = parameters.edit(base, [edit()])["artifact_id"]
    second = parameters.edit(first, [edit("mMagicAttack", 200, 300)])["artifact_id"]
    other = parameters.edit(base, [edit("mWeight", 0.5, 0.25)])["artifact_id"]
    merged = parameters.merge(second, other)["artifact_id"]
    diff = parameters.diff(base, merged, limit=2)
    assert diff["total"] == 3 and diff["next_offset"] == 2
    assert diff["unmodeled_changed_bytes"] == 0
    assert parameters.inspect(merged, item_id=0)["items"][0]["fields"]["mMagicAttack"] == 300
    assert assets.read(base)[1] == item_table()
    assert list(assets.config.game.iterdir()) == []


def test_merge_conflict_and_metadata_tampering_are_not_silently_accepted(services):
    assets, parameters, _ = services
    base = assets.blob(item_table())["artifact_id"]
    left = parameters.edit(base, [edit()])["artifact_id"]
    right = parameters.edit(base, [edit(value=300)])["artifact_id"]
    with pytest.raises(ToolFailure, match="differently"):
        parameters.merge(left, right)
    doc = assets.artifacts.get(right)
    doc["data"]["edits"][0]["value"] = 200
    atomic_json(assets.artifacts.path(right), doc)
    with pytest.raises(ToolFailure, match="reproduce"):
        parameters.merge(left, right)


def test_unmodeled_changed_bytes_are_reported_instead_of_hidden(services):
    assets, parameters, _ = services
    raw = item_table()
    changed = bytearray(raw)
    changed[16 + 99] ^= 1
    first = assets.blob(raw)["artifact_id"]
    second = assets.blob(changed)["artifact_id"]
    report = parameters.diff(first, second)
    assert report["total"] == 0 and report["unmodeled_changed_bytes"] == 1


def test_item_fields_merge_through_real_archive_and_profile_pipeline(services):
    from test_workbench import arc

    assets, parameters, mods = services
    raw = arc([item_table(), b"untouched opaque entry"])
    path = assets.config.game / "nativePC/fixture.arc"
    path.parent.mkdir()
    path.write_bytes(raw)
    archive = assets.open("nativePC/fixture.arc")["artifact_id"]
    entry = assets.extract(archive, 0)["artifact_id"]
    original, _ = assets.read(entry)

    def mod(label, patch):
        edited = parameters.edit(entry, [patch])
        repacked = assets.repack(
            archive,
            [{"index": 0, "artifact_id": edited["artifact_id"], "expected_sha256": original["sha256"]}],
        )
        return mods.register(
            label, [{"target": "nativePC/fixture.arc", "asset_id": repacked["artifact_id"]}]
        )["artifact_id"]

    first = mod("attack", edit())
    second = mod("magic", edit("mMagicAttack", 200, 300))
    third = mod("weight", edit("mWeight", 0.5, 0.25))
    conflicting = mod("different attack", edit(value=400))
    combined = mods.compose("three independent fields", [first, second, third])
    assert combined["summary"]["compatible"]
    final_id = assets.artifacts.get(combined["artifact_id"])["data"]["files"][0]["asset_id"]
    _, packed = assets.read(final_id)
    entries = arc_table(packed)
    fields = read_item(unpack_entry(packed, entries[0]), 0)["fields"]
    assert (fields["mAttack"], fields["mMagicAttack"], fields["mWeight"]) == (200, 300, 0.25)
    assert unpack_entry(packed, entries[1]) == b"untouched opaque entry"
    assert not mods.compose("conflict", [first, conflicting])["summary"]["compatible"]
    assert mods.package(combined["artifact_id"])["sha256"]
    assert path.read_bytes() == raw


def test_item_tools_over_stdio_use_private_assets_and_preserve_originals(services):
    assets, _, _ = services
    config = assets.config
    base = assets.blob(item_table())["artifact_id"]
    atomic_json(config.root / "config/local.json", config.settings.model_dump())
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "ddda_mcp", "--project", str(config.root)]
    )

    async def test():
        async with Client(parameters, read_timeout_seconds=20) as client:

            async def call(name, args):
                response = await client.call_tool(name, args)
                assert not response.is_error, response.structured_content
                return response.structured_content["data"]

            catalog = await call("item_parameter_catalog", {})
            assert len(catalog["fields"]) == 11
            assert (await call("inspect_item_parameters", {"entry_id": base, "item_id": 0}))["total"] == 4
            edited = await call(
                "edit_item_parameters", {"entry_id": base, "edits": [edit("mAddHp", 120, 150)]}
            )
            diff = await call("diff_item_parameters", {"before_id": base, "after_id": edited["artifact_id"]})
            assert diff["total"] == 1 and diff["changes"][0]["after"] == 150
            assert (
                await client.call_tool(
                    "edit_item_parameters", {"entry_id": base, "edits": [edit(value=True)]}
                )
            ).is_error

    asyncio.run(test())
    assert assets.read(base)[1] == item_table()
    assert list(config.game.iterdir()) == []
