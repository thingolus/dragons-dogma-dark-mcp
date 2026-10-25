"""Conservative named-field editing of DDDA ITL2 item data. MIT, Thingolus.

Independent implementation of the file layout, cross-checked against local data
and Chris Purnell's itl2xml format research. See docs/ITEM_PARAMETERS.md. No game
data, item-name tables or third-party implementation is included.
"""

import math
import struct
from dataclasses import dataclass

from .common import ToolFailure

FORMAT = "ddda_itl2_20121105"
VERSION = 20121105
STRIDE = 128
REFERENCE = "https://github.com/chrispurnell/dd-tools/blob/6e3e76107ae67bf5efef8a3206bea54848b0e694/itl2xml.c"


@dataclass(frozen=True)
class Stat:
    offset: int
    storage: str
    minimum: int | float
    maximum: int | float
    meaning: str
    shift: int = 0
    bits: int = 0
    signed: bool = False
    reference: bool = False

    def read(self, raw, base):
        value = struct.unpack_from("<" + self.storage, raw, base + self.offset)[0]
        if self.bits:
            value = (value >> self.shift) & ((1 << self.bits) - 1)
            if self.signed and value & (1 << (self.bits - 1)):
                value -= 1 << self.bits
        return value

    def normalize(self, value, count, editing=True):
        if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
            raise ToolFailure("parameter_invalid", "A finite numeric value is required.")
        if self.storage != "f" and type(value) is not int:
            raise ToolFailure("parameter_invalid", "This field requires an integer.")
        if editing and not self.minimum <= value <= self.maximum:
            raise ToolFailure("parameter_range", "Value is outside the field's supported range.")
        if editing and self.reference and value != -1 and not 0 <= value < count:
            raise ToolFailure("parameter_reference", "Alternate item must be -1 or an existing item ID.")
        try:
            if self.storage == "f":
                value = struct.unpack("<f", struct.pack("<f", value))[0]
                if not math.isfinite(value):
                    raise OverflowError
            elif self.bits:
                low = -(1 << (self.bits - 1)) if self.signed else 0
                high = (1 << (self.bits - int(self.signed))) - 1
                if not low <= value <= high:
                    raise OverflowError
            else:
                struct.pack("<" + self.storage, value)
        except (OverflowError, struct.error) as exc:
            raise ToolFailure("parameter_range", "Value cannot be represented by the stored field.") from exc
        return value

    def write(self, result, base, value):
        at = base + self.offset
        if self.bits:
            mask = ((1 << self.bits) - 1) << self.shift
            original = struct.unpack_from("<I", result, at)[0]
            struct.pack_into("<I", result, at, (original & ~mask) | ((value << self.shift) & mask))
        else:
            struct.pack_into("<" + self.storage, result, at, value)

    def masks(self):
        if self.bits:
            return (((1 << self.bits) - 1) << self.shift).to_bytes(4, "little")
        return b"\xff" * struct.calcsize("<" + self.storage)


# Native field names are retained to avoid inventing undocumented game semantics.
# Only these reviewed fields are writable; all other bytes/bits stay untouched.
STATS = {
    "mAttack": Stat(0, "I", 0, 2047, "Physical attack field", bits=11),
    "mMagicAttack": Stat(0, "I", 0, 2047, "Magick attack field", shift=11, bits=11),
    "mElementAttack": Stat(0, "I", 0, 1023, "Element attack field", shift=22, bits=10),
    "mDefense": Stat(4, "I", 0, 1023, "Physical defense field", bits=10),
    "mMagicDefense": Stat(4, "I", 0, 1023, "Magick defense field", shift=10, bits=10),
    "mAlterItemNo": Stat(
        60,
        "I",
        -1,
        4095,
        "Alternate item reference; -1 means absent",
        shift=13,
        bits=13,
        signed=True,
        reference=True,
    ),
    "mWeight": Stat(68, "f", 0, 1000000, "Weight field; no gameplay-unit acceptance claimed"),
    "mBuy": Stat(72, "i", 0, 2147483647, "Buy-price field"),
    "mSell": Stat(76, "i", 0, 2147483647, "Sell-price field"),
    "mAddHp": Stat(
        112, "h", -32768, 32767, "Flat HP amount field; engine effect requires gameplay verification"
    ),
    "mAddAp": Stat(
        114, "h", -32768, 32767, "Flat stamina amount field; engine effect requires gameplay verification"
    ),
}


def table(raw):
    if len(raw) < 16 or raw[:4] != b"ITL2":
        raise ToolFailure("parameter_unsupported", "Expected an ITL2 item table.")
    version, count, reserved = struct.unpack_from("<III", raw, 4)
    if version != VERSION or reserved != 0 or not 1 <= count <= 4096 or len(raw) != 16 + STRIDE * count:
        raise ToolFailure("parameter_unsupported", "Unknown item-table version, header or record extent.")
    for item_id in range(count):
        base = 16 + STRIDE * item_id
        if struct.unpack_from("<I", raw, base + 60)[0] & 8191 != item_id:
            raise ToolFailure(
                "parameter_invalid", "Record order/item identity does not match the reviewed layout."
            )
        ref = STATS["mAlterItemNo"].read(raw, base)
        if ref != -1 and not 0 <= ref < count:
            raise ToolFailure(
                "parameter_reference", "Item table contains an unresolved alternate-item reference."
            )
        if not math.isfinite(STATS["mWeight"].read(raw, base)):
            raise ToolFailure("parameter_invalid", "Nonfinite item weight.")
    return count


def read_item(raw, item_id):
    return {
        "item_id": item_id,
        "fields": {name: spec.read(raw, 16 + STRIDE * item_id) for name, spec in STATS.items()},
    }


def edit_table(raw, edits):
    count = table(raw)
    if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
        raise ToolFailure("parameter_invalid", "Edit 1–100 named fields per patch.")
    result, normalized, seen, masks = bytearray(raw), [], set(), {}
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {"item_id", "field", "expected", "value"}:
            raise ToolFailure("parameter_invalid", "Use item_id, field, expected and value only.")
        item_id, name = edit["item_id"], edit["field"]
        if (
            type(item_id) is not int
            or not 0 <= item_id < count
            or not isinstance(name, str)
            or name not in STATS
        ):
            raise ToolFailure("parameter_invalid", "Select an existing item and reviewed named field.")
        key = (item_id, name)
        if key in seen:
            raise ToolFailure("parameter_invalid", "A patch cannot edit a field twice.")
        seen.add(key)
        spec, base = STATS[name], 16 + STRIDE * item_id
        before = spec.read(raw, base)
        expected = spec.normalize(edit["expected"], count, editing=False)
        if before != expected:
            raise ToolFailure(
                "parameter_conflict", f"Item {item_id} field {name} differs from the expected original."
            )
        value = spec.normalize(edit["value"], count)
        spec.write(result, base, value)
        for offset, bits in enumerate(spec.masks(), base + spec.offset):
            masks[offset] = masks.get(offset, 0) | bits
        normalized.append({"item_id": item_id, "field": name, "expected": before, "value": value})
    table(result)
    if any((a ^ b) & ~masks.get(i, 0) for i, (a, b) in enumerate(zip(raw, result, strict=True))):
        raise ToolFailure("parameter_roundtrip", "The patch changed unselected bits.")
    for edit in normalized:
        if STATS[edit["field"]].read(result, 16 + STRIDE * edit["item_id"]) != edit["value"]:
            raise ToolFailure("parameter_roundtrip", "A patched field failed readback verification.")
    return bytes(result), normalized


def merge_edits(first, second):
    merged = {(e["item_id"], e["field"]): e for e in first if e["expected"] != e["value"]}
    for edit in second:
        if edit["expected"] == edit["value"]:
            continue
        key = (edit["item_id"], edit["field"])
        if key in merged and merged[key] != edit:
            raise ToolFailure("mod_conflict", f"Mods change item {key[0]} field {key[1]} differently.")
        merged[key] = edit
    if len(merged) > 100:
        raise ToolFailure("parameter_invalid", "Merged item patch exceeds 100 fields.")
    return [merged[k] for k in sorted(merged)]


class Parameters:
    def __init__(self, assets):
        self.assets = assets

    def catalog(self):
        return {
            "format": FORMAT,
            "magic": "ITL2",
            "version": VERSION,
            "record_bytes": STRIDE,
            "fields": [
                {
                    "name": name,
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                    "integer": spec.storage != "f",
                    "meaning": spec.meaning,
                    "reference": "Existing item ID or -1" if spec.reference else None,
                }
                for name, spec in STATS.items()
            ],
            "reference": REFERENCE,
            "native_acceptance": "unverified",
            "limitations": "Only the listed item fields are writable. Skills, enemies, loot tables and generic XFS remain unsupported.",
        }

    def inspect(self, entry_id, item_id=None, offset=0, limit=20):
        data, raw = self.assets.read(entry_id, "asset_blob")
        count = table(raw)
        if (
            not 0 <= offset <= 4096
            or not 1 <= limit <= 100
            or (item_id is not None and not 0 <= item_id < count)
        ):
            raise ToolFailure("parameter_invalid", "Use an existing item ID or a bounded page.")
        ids = [item_id] if item_id is not None else range(offset, min(count, offset + limit))
        return {
            "format": FORMAT,
            "sha256": data["sha256"],
            "total": count,
            "items": [read_item(raw, i) for i in ids],
            "next_offset": offset + limit if item_id is None and offset + limit < count else None,
        }

    def edit(self, entry_id, edits):
        self.assets.config.require_development()
        data, raw = self.assets.read(entry_id, "asset_blob")
        changed, normalized = edit_table(raw, edits)
        base_id, base_sha = entry_id, data["sha256"]
        if data.get("format") == FORMAT and data.get("base_id"):
            base_id, base_sha = data["base_id"], data["base_sha256"]
            base, original = self.assets.read(base_id, "asset_blob")
            if base["sha256"] != base_sha or edit_table(original, data["edits"])[0] != raw:
                raise ToolFailure(
                    "evidence_changed", "Item edit provenance no longer reproduces its payload."
                )
            combined = {(e["item_id"], e["field"]): e for e in data["edits"]}
            for edit in normalized:
                key = (edit["item_id"], edit["field"])
                combined[key] = {
                    **edit,
                    "expected": STATS[edit["field"]].read(original, 16 + STRIDE * edit["item_id"]),
                }
            normalized = [combined[k] for k in sorted(combined)]
            if edit_table(original, normalized)[0] != changed:
                raise ToolFailure("parameter_roundtrip", "Composed item edits did not reproduce the payload.")
        receipt = self.assets.blob(
            changed,
            {
                "base_id": base_id,
                "base_sha256": base_sha,
                "format": FORMAT,
                "edits": normalized,
                "entry": data.get("entry"),
                "game_path": data.get("game_path"),
                "layout_reference": REFERENCE,
            },
        )
        return {**receipt, "changes": normalized, "native_acceptance": "unverified"}

    def diff(self, before_id, after_id, offset=0, limit=20):
        if not 0 <= offset <= 50000 or not 1 <= limit <= 100:
            raise ToolFailure("parameter_invalid", "Use a bounded diff page.")
        a, before = self.assets.read(before_id, "asset_blob")
        b, after = self.assets.read(after_id, "asset_blob")
        count = table(before)
        if table(after) != count or before[:16] != after[:16]:
            raise ToolFailure("parameter_incompatible", "Item tables have different identities or extents.")
        changes, allowed = [], bytearray(len(before))
        for item_id in range(count):
            base = 16 + STRIDE * item_id
            for name, spec in STATS.items():
                first, second = spec.read(before, base), spec.read(after, base)
                if first != second:
                    changes.append({"item_id": item_id, "field": name, "before": first, "after": second})
                for i, bits in enumerate(spec.masks(), base + spec.offset):
                    allowed[i] |= bits
        unknown = sum(bool((a ^ b) & ~mask) for a, b, mask in zip(before, after, allowed, strict=True))
        return {
            "format": FORMAT,
            "before_sha256": a["sha256"],
            "after_sha256": b["sha256"],
            "changes": changes[offset : offset + limit],
            "total": len(changes),
            "next_offset": offset + limit if offset + limit < len(changes) else None,
            "unmodeled_changed_bytes": unknown,
            "native_acceptance": "unverified",
        }

    def merge(self, left_id, right_id):
        left, left_bytes = self.assets.read(left_id, "asset_blob")
        right, right_bytes = self.assets.read(right_id, "asset_blob")
        if (
            left.get("format") != FORMAT
            or right.get("format") != FORMAT
            or not left.get("base_id")
            or left.get("base_sha256") != right.get("base_sha256")
        ):
            raise ToolFailure("mod_conflict", "Item patches need the same recorded base.")
        base, original = self.assets.read(left["base_id"], "asset_blob")
        if base["sha256"] != left["base_sha256"]:
            raise ToolFailure("evidence_changed", "Item patch base changed.")
        for data, payload in ((left, left_bytes), (right, right_bytes)):
            if edit_table(original, data["edits"])[0] != payload:
                raise ToolFailure("evidence_changed", "Item patch metadata does not reproduce the payload.")
        edits = merge_edits(left["edits"], right["edits"])
        return self.edit(left["base_id"], edits) if edits else {"artifact_id": left["base_id"]}
