"""Reviewed copied exports from the pinned runtime/HUD. Copyright Thingolus, MIT."""

import math
import struct

from .common import ToolFailure

# Byte sizes/versions and fields were reviewed against e6a64c2, not dirty source.
# Only these value-only exports may be invoked; no caller-supplied export names.
GROUPS = {
    "pawn_resources": {
        "export": "CoopGetHudStatus",
        "size": 64,
        "version": 2,
        "fields": "size version draws failures visible width height hp hp_max hp_white stamina stamina_max samples draw_last_us draw_p95_us draw_max_us".split(),
        "floats": [7, 8, 9, 10, 11, 13, 14, 15],
        "source": "include/coop/hud.hpp",
        "availability": "visible",
        "limitation": "Main-pawn HUD cache only; hidden values are unavailable. No P1 vitals or damage attribution.",
    },
    "pawn_vocation": {
        "export": "CoopGetVocationStatus",
        "size": 40,
        "version": 1,
        "fields": "size version fresh job allowed experimental_mage age_ms releases reason released".split(),
        "availability": "fresh",
        "limitation": "Cached pawn vocation and policy; freshness/age are supplied by the runtime.",
    },
    "pawn_actions": {
        "export": "CoopGetGenericStatus",
        "size": 36,
        "version": 2,
        "fields": "size version requests known_requests bindings completions cleanups active rejected".split(),
        "limitation": "Generic action handoff counters; not a complete pawn AI decision log.",
    },
    "inventory_menu": {
        "export": "CoopSharedMenuStatus",
        "size": 88,
        "version": 1,
        "words_arg": True,
        "fields": "size version phase disposition blocked lifetime_state serial_low serial_high world_epoch generation native_known native_gameplay return_ready flush_mask opens closes cleanups destructors updates neutral_consumers returns flush_cycle".split(),
        "u64": {"serial": [6, 7]},
        "limitation": "Inventory/menu lifecycle only; no claim about complete item contents or quest progress.",
    },
    "shared_life": {
        "export": "CoopSharedLifeStatus",
        "size": 224,
        "version": 1,
        "words_arg": True,
        "fields": "size version enabled maximum remaining bound game_over load_low load_high events_low events_high p1_generation_low p1_generation_high p2_generation_low p2_generation_high downed_mask revival_mask paid_mask safety_present gameover_pending gameover_inflight gameover_requested gameover_failed rest_hooks_active down_entries down_commits duplicates revive_entries revived stale refused exceptions late_deaths redirects timeouts aid_input aid_animation aid_consumer voice_guards loads gameover_calls gameover_receipts gameover_deferrals actor_mask active_frames recovery_unknown_mask safety_count safety_retirements last_kind last_role last_action last_reason last_changed sequence_low sequence_high reserved".split(),
        "u64": {
            "world_load": [7, 8],
            "issued_events": [9, 10],
            "p1_generation": [11, 12],
            "p2_generation": [13, 14],
            "last_sequence": [53, 54],
        },
        "limitation": "Copied revival policy, masks and counters; no complete combat event history.",
    },
    "target_hud": {
        "export": "CoopGetIngleHudStatus",
        "size": 44,
        "version": 1,
        "fields": "size version visible ready target_valid projected screen_x screen_y target_x target_y target_z".split(),
        "floats": [6, 7, 8, 9, 10],
        "source": "include/coop/hud.hpp",
        "availability": "target_valid",
        "limitation": "Ingle HUD target cache only. Target coordinates do not identify an enemy or establish damage.",
    },
}


def decode_group(name, words):
    spec = GROUPS[name]
    values = dict(zip(spec["fields"], words, strict=True))
    for index in spec.get("floats", []):
        value = struct.unpack("<f", struct.pack("<I", words[index]))[0]
        if not math.isfinite(value):
            raise ToolFailure("invalid_diagnostic", "Nonfinite copied diagnostic value.")
        values[spec["fields"][index]] = value
    for key, (low, high) in spec.get("u64", {}).items():
        values[key] = str(words[low] | words[high] << 32)
        del values[spec["fields"][low]], values[spec["fields"][high]]
    available = values.get(spec.get("availability")) == 1 if spec.get("availability") else None
    return {
        "values": values,
        "available": available,
        "limitations": [spec["limitation"], "Sequential copied reads are not an atomic world snapshot."],
    }
