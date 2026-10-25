"""Bounded, lossless editors for DDDA's self-describing XFS and skill tables.

Copyright (c) 2026 Thingolus. MIT. Independent format implementation; see
docs/GAME_PARAMETERS.md for format research and the distinction between a
serialized type and a verified gameplay meaning.
"""

import math
import struct
from dataclasses import dataclass, replace

from .assets import MAX_ENTRY
from .common import ToolFailure

FORMAT = "ddda_named_parameters_v1"
SCALARS = {
    3: ("bool", "B"),
    4: ("u8", "B"),
    5: ("u16", "H"),
    6: ("u32", "I"),
    7: ("u64", "Q"),
    8: ("s8", "b"),
    9: ("s16", "h"),
    10: ("s32", "i"),
    11: ("s64", "q"),
    12: ("f32", "f"),
    13: ("f64", "d"),
}
VECTORS = {19: 16, 20: 4, 21: 4, 22: 4, 34: 2, 35: 3, 36: 4, 45: 4, 47: 8, 49: 12, 55: 2, 57: 16}


def invalid(message):
    raise ToolFailure("parameter_layout", message)


@dataclass(frozen=True)
class Field:
    path: str
    name: str
    type: str
    offset: int
    size: int
    value: object
    storage: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None

    def public(self):
        return {
            "path": self.path,
            "name": self.name,
            "type": self.type,
            "value": self.value,
            "editable": self.storage is not None,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }

    def encode(self, value):
        if not self.storage:
            invalid("This field is structural or a reference and is read-only.")
        if self.type == "bool":
            if type(value) is not bool:
                invalid("Boolean fields require true or false.")
        elif self.storage in {"f", "d"}:
            if type(value) not in {int, float} or not math.isfinite(value):
                invalid("Floating-point fields require finite numbers.")
        elif type(value) is not int:
            invalid("Integer fields require an exact integer.")
        if (self.minimum is not None and value < self.minimum) or (
            self.maximum is not None and value > self.maximum
        ):
            invalid("Value is outside the reviewed field bounds.")
        try:
            result = struct.pack("<" + self.storage, value)
            decoded = struct.unpack("<" + self.storage, result)[0]
            if isinstance(decoded, float) and not math.isfinite(decoded):
                invalid("Value overflows its storage type.")
            return result
        except (OverflowError, struct.error) as exc:
            raise ToolFailure("parameter_range", "Value overflows its storage type.") from exc


class Reader:
    def __init__(self, raw):
        if not 8 <= len(raw) <= MAX_ENTRY:
            invalid("Parameter file extent is out of bounds.")
        self.raw, self.pos, self.fields, self.nodes = raw, 0, [], 0

    def take(self, size, end=None):
        if size < 0 or self.pos + size > (len(self.raw) if end is None else end):
            invalid("Truncated parameter payload.")
        start = self.pos
        self.pos += size
        return start

    def number(self, storage, end=None):
        return struct.unpack_from("<" + storage, self.raw, self.take(struct.calcsize(storage), end))[0]

    def string(self, end):
        start = self.pos
        stop = self.raw.find(b"\0", start, min(end, start + 65537))
        if stop < 0:
            invalid("Unterminated or oversized parameter string.")
        self.pos = stop + 1
        try:
            return self.raw[start:stop].decode("utf-8")
        except UnicodeError as exc:
            raise ToolFailure("parameter_encoding", "Unsupported parameter string encoding.") from exc

    def scalar(self, path, name, typename, storage, end, editable=True, minimum=None, maximum=None):
        at = self.pos
        value = self.number(storage, end)
        if isinstance(value, float) and not math.isfinite(value):
            invalid("Nonfinite serialized parameter.")
        if typename == "bool":
            if value not in (0, 1):
                invalid("Invalid serialized boolean.")
            value = bool(value)
        self.fields.append(
            Field(
                path,
                name,
                typename,
                at,
                self.pos - at,
                value,
                storage if editable else None,
                minimum,
                maximum,
            )
        )
        if len(self.fields) > 200000:
            invalid("Parameter field budget exceeded.")


def xfs_fields(raw):
    r = Reader(raw)
    if len(raw) < 28 or raw[:4] != b"XFS\0":
        invalid("Expected an XFS resource.")
    version, subtype, max_id, count, extent = struct.unpack_from("<HHIII", raw, 4)
    if version != 0x109 or not 1 <= count <= 4096 or not count * 4 <= extent <= len(raw) - 28:
        invalid("Unsupported XFS version or descriptor extent.")
    end = 20 + extent
    classes, descriptor_spans = [], []
    for index in range(count):
        at = 20 + struct.unpack_from("<I", raw, 20 + index * 4)[0]
        if not 20 + count * 4 <= at <= end - 12:
            invalid("Class descriptor points outside the descriptor block.")
        class_hash, native_size, fields = struct.unpack_from("<III", raw, at)
        if fields > 4096 or at + 12 + 24 * fields > end:
            invalid("Class descriptor is truncated.")
        descriptor_spans.append((at, at + 12 + 24 * fields))
        rows = []
        for j in range(fields):
            name_at, kind, flags, size = struct.unpack_from("<IBBH", raw, at + 12 + 24 * j)
            r.pos = 20 + name_at
            if not 20 + count * 4 <= r.pos < end:
                invalid("Field name points outside the descriptor block.")
            name = r.string(end)
            if not name or len(name) > 1024:
                invalid("Invalid field name.")
            rows.append((name, kind, flags, size))
        classes.append((class_hash, rows))
    spans = sorted(descriptor_spans)
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
        invalid("Overlapping class descriptors.")

    def read_class(path, parent_end, depth=0):
        r.nodes += 1
        if depth > 64 or r.nodes > 100000:
            invalid("XFS object budget exceeded.")
        kind, identity = r.number("H", parent_end), r.number("H", parent_end)
        if not kind & 1:
            return
        index = kind >> 1
        if index >= count or identity > max_id:
            invalid("Invalid XFS class or instance reference.")
        length_start = r.pos
        length = r.number("I", parent_end)
        object_end = length_start + length
        if length < 4 or object_end > parent_end:
            invalid("XFS object extent exceeds its parent.")
        for field_index, (name, field_type, flags, _size) in enumerate(classes[index][1]):
            n = r.number("I", object_end)
            if n > 100000 or (not flags & 0x20 and n != 1):
                invalid("Invalid XFS field array count.")
            escaped = name.replace("~", "~0").replace("/", "~1")
            field_path = f"{path}/{field_index}:{escaped}"
            for element in range(n):
                p = f"{field_path}/{element}" if flags & 0x20 else field_path
                if field_type in (1, 2):
                    read_class(p, object_end, depth + 1)
                elif field_type in SCALARS:
                    typename, storage = SCALARS[field_type]
                    r.scalar(p, name, typename, storage, object_end)
                elif field_type in (14, 32):
                    at = r.pos
                    value = r.string(object_end)
                    r.fields.append(Field(p, name, "string", at, r.pos - at, value))
                elif field_type in VECTORS:
                    for component in range(VECTORS[field_type]):
                        # VECTOR3's fourth float and padded shapes retain padding verbatim.
                        editable = not (field_type in (20, 47, 49) and component % 4 == 3)
                        r.scalar(f"{p}/{component}", name, "f32", "f", object_end, editable)
                elif field_type == 56:
                    for component in range(2):
                        r.scalar(f"{p}/{component}", name, "u16", "H", object_end)
                else:
                    raise ToolFailure(
                        "parameter_unsupported", f"XFS serialized type {field_type} is not reviewed."
                    )
        if r.pos != object_end:
            invalid("XFS class did not consume its declared extent.")

    r.pos = end
    read_class("$", len(raw))
    if r.pos != len(raw):
        invalid("Unexpected trailing XFS payload.")
    return {"format": "xfs_0109", "subtype": subtype, "classes": count}, r.fields


def skill_fields(raw):
    r = Reader(raw)
    if raw[:8] != b"skl\0\0\x02\0\0":
        invalid("Unsupported SKL version; expected 0x200.")
    r.pos = 8
    for group, names in (
        ("normal", ("mSkillId", "mJobPoint", "mJobLevel")),
        ("custom", ("mSkillId", "mSkillLv", "mJobPoint", "mJobLevel")),
        ("ability", ("mAbilityId", "mJobPoint", "mJobLevel")),
    ):
        count = r.number("I")
        if count > 4096:
            invalid("Skill table record budget exceeded.")
        identities = set()
        for i in range(count):
            for name in names:
                readonly = name in ("mSkillId", "mAbilityId", "mSkillLv")
                r.scalar(
                    f"$/{group}/{i}/{name}",
                    name,
                    "s32",
                    "i",
                    len(raw),
                    not readonly,
                    0,
                    9 if name == "mJobLevel" else 2147483647,
                )
            identity = tuple(
                f.value for f in r.fields[-len(names) :] if f.name in ("mSkillId", "mAbilityId", "mSkillLv")
            )
            if identity in identities:
                invalid("Duplicate skill identity.")
            identities.add(identity)
    if r.pos != len(raw):
        invalid("Skill table extent differs from its counts.")
    return {"format": "skl_0200"}, r.fields


def loot_fields(raw):
    r = Reader(raw)
    if raw[:8] != b"ist\0\0\0\0\0" or len(raw) < 12:
        invalid("Unsupported IST item-set version.")
    r.pos = 8
    count = r.number("I")
    if not 1 <= count <= 10000 or len(raw) != 12 + 40 * count:
        invalid("Item-set extent differs from its record count.")
    for i in range(count):
        for name in ("mSetId", "mSetType", "mGetCount", "mDropCount"):
            r.scalar(f"$/{i}/{name}", name, "s16", "h", len(raw), name in ("mGetCount", "mDropCount"), 0, 8)
        for j in range(8):
            r.scalar(f"$/{i}/mItemNo/{j}", "mItemNo", "s16", "h", len(raw), False)
        for j in range(8):
            r.scalar(
                f"$/{i}/mItemGetProbability/{j}", "mItemGetProbability", "s16", "h", len(raw), True, 0, 100
            )
    return {"format": "ist_0000", "records": count}, r.fields


def parse(raw):
    if raw[:4] == b"PRPZ":
        meta, fields = xfs_fields(raw[12:])
        return {**meta, "wrapper": "PRPZ", "wrapper_identity": raw[4:12].hex()}, [
            replace(f, offset=f.offset + 12) for f in fields
        ]
    if raw[:4] == b"XFS\0":
        return xfs_fields(raw)
    if raw[:4] == b"skl\0":
        return skill_fields(raw)
    if raw[:4] == b"ist\0":
        return loot_fields(raw)
    if raw[:4] == b"lot\0":
        from .encounters import encounter_fields

        return encounter_fields(raw)
    raise ToolFailure(
        "parameter_unsupported", "Use XFS 0x109 (including PRPZ), SKL 0x200, IST v0 or LOT v16."
    )


def patch(raw, edits):
    meta, fields = parse(raw)
    if not 1 <= len(edits) <= 100:
        invalid("Edit 1–100 named fields.")
    by_path = {f.path: f for f in fields}
    result, seen, changed, allowed = bytearray(raw), set(), [], set()
    for edit in edits:
        if set(edit) != {"path", "expected", "value"} or edit["path"] in seen:
            invalid("Edits require unique path, expected and value fields.")
        key = edit["path"]
        if key not in by_path:
            invalid("Unknown field path.")
        f = by_path[key]
        if f.encode(edit["expected"]) != raw[f.offset : f.offset + f.size]:
            raise ToolFailure("parameter_conflict", f"Expected value differs at {key}.")
        encoded = f.encode(edit["value"])
        result[f.offset : f.offset + f.size] = encoded
        allowed.update(range(f.offset, f.offset + f.size))
        value = struct.unpack("<" + f.storage, encoded)[0]
        if f.type == "bool":
            value = bool(value)
        changed.append({"path": key, "expected": f.value, "value": value})
        seen.add(key)
    if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, result, strict=True))):
        invalid("Patch changed bytes outside the selected fields.")
    _, verified = parse(bytes(result))
    values = {f.path: f.value for f in verified}
    if any(values[e["path"]] != e["value"] for e in changed):
        invalid("Field readback differs.")
    return bytes(result), changed


class GameParameters:
    def __init__(self, assets):
        self.assets = assets

    def inspect(self, entry_id, query="", offset=0, limit=20):
        data, raw = self.assets.read(entry_id, "asset_blob")
        meta, fields = parse(raw)
        rows = [f.public() for f in fields if query.casefold() in f.path.casefold()]
        return {
            **meta,
            "sha256": data["sha256"],
            "fields": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "limitations": "Names and types come from the file; numeric representability is not a gameplay safety guarantee.",
        }

    def edit(self, entry_id, edits):
        self.assets.config.require_development()
        data, raw = self.assets.read(entry_id, "asset_blob")
        changed, normalized = patch(raw, edits)
        base_id, base_sha = entry_id, data["sha256"]
        if data.get("format") == FORMAT:
            base_id, base_sha = data["base_id"], data["base_sha256"]
            base, original = self.assets.read(base_id, "asset_blob")
            if base["sha256"] != base_sha or patch(original, data["edits"])[0] != raw:
                invalid("Stored patch provenance does not reproduce the asset.")
            original_fields = {f.path: f for f in parse(original)[1]}
            combined = {e["path"]: e for e in data["edits"]}
            combined.update(
                {e["path"]: {**e, "expected": original_fields[e["path"]].value} for e in normalized}
            )
            normalized = sorted(combined.values(), key=lambda e: e["path"])
            if patch(original, normalized)[0] != changed:
                invalid("Cumulative edits do not reproduce the asset.")
        return {
            **self.assets.blob(
                changed,
                {
                    "format": FORMAT,
                    "base_id": base_id,
                    "base_sha256": base_sha,
                    "edits": normalized,
                    "entry": data.get("entry"),
                    "game_path": data.get("game_path"),
                },
            ),
            "changes": normalized,
            "native_acceptance": "unverified",
        }

    def diff(self, before_id, after_id, offset=0, limit=20):
        a, b = self.assets.read(before_id, "asset_blob")[1], self.assets.read(after_id, "asset_blob")[1]
        ma, fa = parse(a)
        mb, fb = parse(b)
        if (
            ma != mb
            or [(f.path, f.type, f.offset, f.size) for f in fa]
            != [(f.path, f.type, f.offset, f.size) for f in fb]
            or len(a) != len(b)
        ):
            invalid("Parameter layouts differ.")
        rows = [
            {"path": x.path, "before": x.value, "after": y.value}
            for x, y in zip(fa, fb, strict=True)
            if x.value != y.value
        ]
        known = {i for f in fa if f.storage for i in range(f.offset, f.offset + f.size)}
        return {
            "changes": rows[offset : offset + limit],
            "total": len(rows),
            "unmodeled_changed_bytes": sum(
                x != y and i not in known for i, (x, y) in enumerate(zip(a, b, strict=True))
            ),
        }

    def merge(self, left_id, right_id):
        left, a = self.assets.read(left_id, "asset_blob")
        right, b = self.assets.read(right_id, "asset_blob")
        if (
            left.get("format") != FORMAT
            or right.get("format") != FORMAT
            or left["base_sha256"] != right["base_sha256"]
        ):
            raise ToolFailure("mod_conflict", "Parameter patches need the same base.")
        base, raw = self.assets.read(left["base_id"], "asset_blob")
        if (
            base["sha256"] != left["base_sha256"]
            or patch(raw, left["edits"])[0] != a
            or patch(raw, right["edits"])[0] != b
        ):
            invalid("Patch provenance does not reproduce the assets.")
        edits = {e["path"]: e for e in left["edits"] if e["value"] != e["expected"]}
        for e in right["edits"]:
            if e["expected"] == e["value"]:
                continue
            if e["path"] in edits and edits[e["path"]] != e:
                raise ToolFailure("mod_conflict", f"Conflicting parameter {e['path']}.")
            edits[e["path"]] = e
        return self.edit(left["base_id"], list(edits.values())) if edits else {"artifact_id": left["base_id"]}
