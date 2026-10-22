"""Decode copied 1.8 refusal evidence, never authorize revival. MIT, Thingolus."""

import math
import struct

from .common import ToolFailure

WORDS = 520
POINTER_COLUMNS = (4, 14, 15, 16, 17, 18, 19, 20, 36)
ENTRY = ("revival_admitted", "recovery_unknown", "already_downed", "second_down_admitted")
POST = (
    "downed_at_entry",
    "not_downed_after_native",
    "hp_not_zero",
    "terminal_flag",
    "blocked_flag",
    "terminal_state",
    "action_130",
    "action_228",
    "pending_130",
    "pending_228",
)
JOIN = (
    "joined_state",
    "p1_assigned",
    "p2_assigned",
    "distinct_slots",
    "menu_clear",
    "modal_clear",
    "focused",
    "control_actor_matches",
    "world_epoch_matches",
    "generation_matches",
    "control_timestamp_not_future",
    "control_age_within_150ms",
)
REASONS = {
    1: (
        "Revival admission refused",
        "Recovery state unknown",
        "Actor already downed",
        "Second-down admission refused",
    ),
    2: POST,
    3: ("No free invocation slot", "No invocation ticket available"),
}


def u64(words, low, high=None):
    return words[low] | words[low + 1 if high is None else high] << 32


def predicates(names, evaluated, truth):
    return {name: bool(truth & (1 << i)) if evaluated & (1 << i) else None for i, name in enumerate(names)}


def decode_death(words):
    """Accept exactly one copied ring; output no raw pointer fields or caller address."""
    if (
        not isinstance(words, list)
        or len(words) != WORDS
        or any(type(w) is not int or not 0 <= w <= 0xFFFFFFFF for w in words)
    ):
        raise ToolFailure("invalid_diagnostic", "Expected exactly 520 unsigned 32-bit words.")
    if words[:4] != [2080, 1, 64, 8]:
        raise ToolFailure("abi_mismatch", "Death diagnostic requires 2080 bytes/version 1/64 words/8 rows.")
    count, next_row = words[4:6]
    serial = u64(words, 6)
    if count > 8 or next_row >= 8 or (count < 8 and (next_row != count or serial != count)) or serial < count:
        raise ToolFailure("invalid_diagnostic", "Inconsistent refusal ring header.")
    rows = []
    for index in range(count):
        slot = (next_row + index) % 8 if count == 8 else index
        row = words[8 + slot * 64 : 8 + (slot + 1) * 64]
        sequence = u64(row, 0, 63)
        phase, reason = row[1:3]
        if phase not in REASONS or row[3] not in (0, 1):
            raise ToolFailure("invalid_diagnostic", "Unknown refusal phase or actor role.")
        # The native counter saturates; ordering remains physical after UINT64_MAX.
        if serial != 0xFFFFFFFFFFFFFFFF and sequence != serial - count + index + 1:
            raise ToolFailure("invalid_diagnostic", "Refusal sequence does not match its ring header.")
        if serial == 0xFFFFFFFFFFFFFFFF and (
            not sequence or sequence > serial or (rows and sequence < int(rows[-1]["sequence"]))
        ):
            raise ToolFailure("invalid_diagnostic", "Invalid saturated refusal sequence.")
        names = ENTRY if phase == 1 else POST if phase == 2 else ()
        allowed = (1 << len(names)) - 1
        if row[9] & ~allowed or row[10] & ~row[9] or row[11] & ~4095 or row[12] & ~row[11]:
            raise ToolFailure("invalid_diagnostic", "Unknown or unevaluated predicate bits.")
        expected = ((row[9] & ~row[10] & 9) | (row[10] & 6)) if phase == 1 else row[10]
        if (phase != 3 and reason != expected) or not reason or reason & ~((1 << len(REASONS[phase])) - 1):
            raise ToolFailure("invalid_diagnostic", "Refusal reason does not match evaluated predicates.")
        if phase == 3 and reason not in (1, 2):
            raise ToolFailure(
                "invalid_diagnostic", "Capacity refusal must identify slot or ticket exhaustion."
            )
        hp = struct.unpack("<f", struct.pack("<I", row[28]))[0]
        rows.append(
            {
                "sequence": str(sequence),
                "phase": {1: "entry", 2: "after_native", 3: "capacity"}[phase],
                "actor": "Arisen" if row[3] == 0 else "main_pawn",
                "reasons": [text for i, text in enumerate(REASONS[phase]) if reason & (1 << i)],
                "predicates": predicates(names, row[9], row[10]),
                "join_predicates": predicates(JOIN, row[11], row[12]),
                "entry_tick_ms": str(u64(row, 5)),
                "record_poll_tick_ms": str(u64(row, 7)),
                "action_id": row[21],
                "pending_action_id": row[22],
                "hp": hp if math.isfinite(hp) else None,
                "hp_finite": math.isfinite(hp),
                "entry_joined": row[13] == 1,
                "control_age_ms": None if row[39] == 0xFFFFFFFF else row[39],
                "input_age_ms": None if row[55] == 0xFFFFFFFF else row[55],
                "stage": row[57],
                "world_epoch": str(u64(row, 44)),
                "routing_generation": str(u64(row, 46)),
                "policy_actor_generation": str(u64(row, 48)),
                "policy_load": str(u64(row, 58)),
                "refused_counter": row[56],
                "issued_events": str(u64(row, 60)),
                "down_commits": row[62],
            }
        )
    return {
        "summary": {
            "retained_refusals": count,
            "total_recorded": str(serial),
            "older_rows_overwritten": serial > count,
        },
        "rows": rows,
        "pointer_fields_redacted": True,
        "evidence_class": "copied_diagnostic",
        "limitations": [
            "Null predicates were not evaluated; they are not failed checks.",
            "Only the last eight recorded refusals are retained; early exits, late deaths and successful revivals are not a complete event log.",
            "Rows retain their recorded stage/generation and may predate the current world. No refusal or empty ring proves a Game Over cause or a gameplay fix.",
        ],
    }
