import asyncio
import json
import struct

import pytest
from mcp import Client
from test_operations import FakeSession

from ddda_mcp.common import ToolFailure
from ddda_mcp.death import POINTER_COLUMNS, decode_death
from ddda_mcp.server import create_server


def ring(count=1, next_row=None, serial=None, phase=1, reason=1):
    next_row = count % 8 if next_row is None else next_row
    serial = count if serial is None else serial
    words = [2080, 1, 64, 8, count, next_row, serial & 0xFFFFFFFF, serial >> 32] + [0] * 512
    for i in range(count):
        slot = (next_row + i) % 8 if count == 8 else i
        at = 8 + slot * 64
        seq = serial - count + i + 1
        words[at] = seq & 0xFFFFFFFF
        words[at + 63] = seq >> 32
        words[at + 1 : at + 4] = [phase, reason, i % 2]
        words[at + 9 : at + 13] = [1, 0, 3, 1] if phase == 1 else [0, 0, 0, 0]
        words[at + 39] = words[at + 55] = 0xFFFFFFFF
        for column in POINTER_COLUMNS:
            words[at + column] = 0xDECAFBAD
    return words


def test_entry_and_short_circuit_explanations_redact_addresses():
    data = decode_death(ring())
    row = data["rows"][0]
    assert row["reasons"] == ["Revival admission refused"]
    assert row["predicates"] == {
        "revival_admitted": False,
        "recovery_unknown": None,
        "already_downed": None,
        "second_down_admitted": None,
    }
    assert row["join_predicates"]["joined_state"] is True
    assert row["join_predicates"]["p1_assigned"] is False
    assert row["join_predicates"]["focused"] is None
    assert row["control_age_ms"] is None
    assert str(0xDECAFBAD) not in json.dumps(data) and "caller" not in row


def test_wrapped_ring_exact_uint64_and_nonfinite_hp():
    serial = 2**53 + 17
    words = ring(8, next_row=3, serial=serial)
    words[8 + 3 * 64 + 28] = 0x7FC00000
    result = decode_death(words)
    assert [row["sequence"] for row in result["rows"]] == [str(i) for i in range(serial - 7, serial + 1)]
    assert result["summary"]["older_rows_overwritten"]
    assert result["rows"][0]["hp"] is None and not result["rows"][0]["hp_finite"]
    json.dumps(result, allow_nan=False)


def test_post_native_and_capacity_explanations():
    words = ring(phase=2, reason=4)
    words[17:19] = [7, 4]  # Three predicates evaluated; nonzero HP caused refusal.
    words[36] = struct.unpack("<I", struct.pack("<f", 25.5))[0]
    row = decode_death(words)["rows"][0]
    assert row["phase"] == "after_native" and row["hp"] == 25.5
    assert row["predicates"]["hp_not_zero"] is True
    assert row["predicates"]["terminal_flag"] is None
    assert decode_death(ring(phase=3, reason=2))["rows"][0]["reasons"] == ["No invocation ticket available"]
    assert decode_death(ring(0))["summary"]["retained_refusals"] == 0


@pytest.mark.parametrize(
    "index,value",
    [
        (1, 2),
        (4, 9),
        (5, 8),
        (6, 0),
        (8, 2),
        (9, 99),
        (10, 0),
        (11, 2),
        (17, 0),
        (18, 16),
        (19, 4096),
        (20, 4),
        (28, -1),
    ],
)
def test_malformed_ring_refused(index, value):
    words = ring()
    words[index] = value
    with pytest.raises(ToolFailure):
        decode_death(words)


@pytest.mark.parametrize("words", [[], [0] * 521, [False] * 520])
def test_input_bounds(words):
    with pytest.raises(ToolFailure):
        decode_death(words)


def test_saturated_native_serial_remains_decodable():
    words = ring(8, serial=2**64 - 1)
    # A further native publication reuses the saturated serial in the newest slot.
    words[8 + 6 * 64] = 0xFFFFFFFF
    words[8 + 6 * 64 + 63] = 0xFFFFFFFF
    assert len(decode_death(words)["rows"]) == 8


def test_native_capture_persists_redacted_replay_only(development):
    async def run():
        session = FakeSession(development)
        original = session._request

        async def request(operation, **kwargs):
            if operation == "death_refusals":
                session.calls.append((operation, kwargs))
                return ring()
            return await original(operation, **kwargs)

        session._request = request
        result = await session.snapshot("death_refusals")
        artifact = session.artifacts.get(result["artifact_id"])
        assert artifact["kind"] == "death_diagnostic"
        assert str(0xDECAFBAD) not in json.dumps(artifact)
        assert decode_death(artifact["data"]["words"]) == result["death_refusals"]
        assert [op for op, _ in session.calls] == ["snapshot", "death_refusals"]

    asyncio.run(run())


def test_offline_mcp_decoder_and_live_profile_refusal(config):
    async def run():
        server, _ = create_server(config)
        async with Client(server) as client:
            result = await client.call_tool("decode_death_diagnostic", {"words": ring()})
            assert not result.is_error and result.structured_content["data"]["rows"][0]["actor"] == "Arisen"
            result = await client.call_tool("decode_death_diagnostic", {"words": [True] * 520})
            assert result.is_error
            result = await client.call_tool("runtime_snapshot", {"group": "death_refusals"})
            assert result.structured_content["error"]["code"] == "profile_disabled"

    asyncio.run(run())
