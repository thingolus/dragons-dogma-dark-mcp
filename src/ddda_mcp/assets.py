"""Private ARC v7 workspaces and conservative GMD text editing. MIT, Thingolus.

ARC layout verified against Gibbed.MT ArchiveFile.cs and local DDDA containers.
This is an independent Python implementation, not a bundled external executable.
"""

import hashlib
import re
import struct
import zlib
from pathlib import PurePosixPath

from .common import ToolFailure, contained, digest

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_ENTRY = 32 * 1024 * 1024


def relative_name(value):
    parts = value.split("/")
    if (
        not value
        or len(value) > 240
        or "\\" in value
        or any(
            not re.fullmatch(r"[A-Za-z0-9_. -]+", p)
            or p in {".", ".."}
            or p.endswith((".", " "))
            or p.split(".")[0].upper()
            in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}
            for p in parts
        )
    ):
        raise ToolFailure("invalid_path", "Use a regular relative path without device names or traversal.")
    return str(PurePosixPath(value))


def arc_table(raw):
    if len(raw) < 8 or len(raw) > MAX_ARCHIVE or raw[:6] != b"ARC\0\x07\0":
        raise ToolFailure("archive_unsupported", "Only little-endian unencrypted DDDA ARC v7 is supported.")
    count = struct.unpack_from("<H", raw, 6)[0]
    end = 8 + 80 * count
    if not 1 <= count <= 8192 or end > len(raw):
        raise ToolFailure("archive_invalid", "Invalid archive index.")
    rows, keys, spans = [], set(), []
    for i in range(count):
        name, kind, packed, flags, offset = struct.unpack_from("<64sIIII", raw, 8 + i * 80)
        try:
            name = name.split(b"\0", 1)[0].decode("ascii")
        except UnicodeError as exc:
            raise ToolFailure("archive_invalid", "Non-ASCII archive name.") from exc
        key = (name.casefold(), kind)
        size = flags & 0x1FFFFFFF
        if not name or key in keys or offset < end or packed < 1 or offset + packed > len(raw):
            raise ToolFailure("archive_invalid", "Duplicate entry or invalid payload range.")
        keys.add(key)
        spans.append((offset, offset + packed))
        rows.append(
            {
                "index": i,
                "name": name,
                "type_hash": kind,
                "packed_size": packed,
                "size": size,
                "quality": flags >> 29,
                "offset": offset,
            }
        )
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
        raise ToolFailure("archive_invalid", "Overlapping archive payloads.")
    return rows


def unpack_entry(raw, entry):
    if entry["size"] > MAX_ENTRY:
        raise ToolFailure("asset_too_large", "Entry exceeds the 32 MiB decompression limit.")
    compressed = raw[entry["offset"] : entry["offset"] + entry["packed_size"]]
    decoder = zlib.decompressobj()
    try:
        value = decoder.decompress(compressed, entry["size"] + 1)
    except zlib.error as exc:
        raise ToolFailure("archive_invalid", "Invalid compressed entry.") from exc
    if len(value) != entry["size"] or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ToolFailure("archive_invalid", "Compressed entry size or stream boundary differs.")
    return value


def gmd_read(raw):
    # First supported schema: DDDA 0x10201 tables without label/pointer sections.
    if len(raw) < 41 or raw[:8] != b"GMD\0\x01\x02\x01\0":
        raise ToolFailure("text_unsupported", "Expected DDDA GMD version 0x10201.")
    labels, count, label_bytes, text_bytes, name_size = struct.unpack_from("<5I", raw, 20)
    start = 40 + name_size + 1
    if labels or label_bytes or count > 100000 or name_size > 256 or start + text_bytes != len(raw):
        raise ToolFailure("text_unsupported", "Only bounded GMD tables without labels are editable.")
    if raw[start - 1] != 0 or not raw[start:].endswith(b"\0"):
        raise ToolFailure("text_invalid", "Missing GMD terminator.")
    try:
        strings = raw[start:-1].decode("utf-8").split("\0")
    except UnicodeError as exc:
        raise ToolFailure("text_unsupported", "GMD text is not valid UTF-8.") from exc
    if len(strings) != count:
        raise ToolFailure("text_invalid", "GMD string count differs.")
    return start, strings


def gmd_edit(raw, edits):
    start, strings = gmd_read(raw)
    seen = set()
    if not 1 <= len(edits) <= 100:
        raise ToolFailure("invalid_parameters", "Edit 1–100 text entries per patch.")
    for edit in edits:
        index, value = edit["index"], edit["text"]
        if type(index) is not int or not 0 <= index < len(strings) or index in seen:
            raise ToolFailure("text_invalid", "Duplicate or invalid text index.")
        if strings[index] != edit["expected"]:
            raise ToolFailure("text_conflict", "Text differs from the expected original.")
        if not isinstance(value, str) or "\0" in value or len(value.encode("utf-8")) > 65536:
            raise ToolFailure("text_invalid", "Invalid replacement text.")
        seen.add(index)
        strings[index] = value
    payload = ("\0".join(strings) + "\0").encode("utf-8")
    result = bytearray(raw[:start])
    struct.pack_into("<I", result, 32, len(payload))
    result.extend(payload)
    gmd_read(result)
    return bytes(result)


class Assets:
    def __init__(self, config, artifacts):
        self.config, self.artifacts = config, artifacts
        self.root = config.artifacts / "assets"

    def blob(self, raw, metadata=None, kind="asset_blob"):
        if len(raw) > MAX_ARCHIVE:
            raise ToolFailure("asset_too_large", "Asset exceeds the workspace limit.")
        sha = hashlib.sha256(raw).hexdigest()
        path = self.root / (sha + ".bin")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if digest(path) != sha:
                raise ToolFailure("asset_changed", "Stored content-addressed blob changed.")
        else:
            with path.open("xb") as stream:
                stream.write(raw)
        return self.artifacts.put(
            kind,
            {
                "sha256": sha,
                "bytes": len(raw),
                **(metadata or {}),
                "summary": {"bytes": len(raw), "sha256": sha},
            },
            {"evidence_class": "local_asset", "private": True},
        )

    def read(self, artifact_id, kind=None):
        doc = self.artifacts.get(artifact_id)
        if doc["kind"] not in {"asset_blob", "asset_archive"} or (kind and doc["kind"] != kind):
            raise ToolFailure("asset_invalid", "Expected an asset workspace artifact.")
        data = doc["data"]
        sha = data["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ToolFailure("asset_invalid", "Invalid blob identity.")
        path = contained(self.root, self.root / (sha + ".bin"))
        if path.stat().st_size > MAX_ARCHIVE or digest(path) != sha:
            raise ToolFailure("asset_changed", "Stored asset hash differs.")
        return data, path.read_bytes()

    def catalog(self, query="", offset=0, limit=20):
        if len(query) > 120 or not 0 <= offset <= 10000 or not 1 <= limit <= 100:
            raise ToolFailure("invalid_parameters", "Bounded archive query required.")
        root = contained(self.config.game, self.config.game / "nativePC")
        paths = sorted(
            p.relative_to(self.config.game).as_posix()
            for p in root.rglob("*.arc")
            if query.casefold() in p.as_posix().casefold()
        )
        return {
            "archives": paths[offset : offset + limit],
            "total": len(paths),
            "next_offset": offset + limit if offset + limit < len(paths) else None,
        }

    def open(self, relative_path):
        self.config.require_development()
        name = relative_name(relative_path)
        if not name.startswith("nativePC/") or not name.lower().endswith(".arc"):
            raise ToolFailure("asset_invalid", "Select a nativePC ARC archive.")
        path = contained(self.config.game, self.config.game / name)
        if path.stat().st_size > MAX_ARCHIVE:
            raise ToolFailure("asset_too_large", "Archive exceeds 512 MiB.")
        raw = path.read_bytes()
        rows = arc_table(raw)
        receipt = self.blob(raw, {"game_path": name, "entries": rows}, "asset_archive")
        return {**receipt, "entry_count": len(rows), "entries": rows[:20]}

    def entries(self, archive_id, query="", offset=0, limit=20):
        data, raw = self.read(archive_id, "asset_archive")
        rows = [r for r in arc_table(raw) if query.casefold() in r["name"].casefold()]
        return {"entries": rows[offset : offset + limit], "total": len(rows)}

    def extract(self, archive_id, index):
        data, raw = self.read(archive_id, "asset_archive")
        rows = arc_table(raw)
        if type(index) is not int or not 0 <= index < len(rows):
            raise ToolFailure("asset_invalid", "Entry index is out of range.")
        entry = rows[index]
        value = unpack_entry(raw, entry)
        return self.blob(
            value,
            {
                "archive_id": archive_id,
                "archive_sha256": data["sha256"],
                "entry": entry,
                "game_path": data["game_path"],
            },
        )

    def text(self, entry_id, offset=0, limit=20):
        _, raw = self.read(entry_id, "asset_blob")
        _, strings = gmd_read(raw)
        return {
            "format": "gmd_unlabelled_v1",
            "total": len(strings),
            "entries": [
                {"index": i, "text": s} for i, s in enumerate(strings[offset : offset + limit], offset)
            ],
        }

    def edit_text(self, entry_id, edits):
        self.config.require_development()
        data, raw = self.read(entry_id, "asset_blob")
        changed = gmd_edit(raw, edits)
        return self.blob(
            changed,
            {
                "base_id": entry_id,
                "base_sha256": data["sha256"],
                "format": "gmd_unlabelled_v1",
                "edits": edits,
                "entry": data.get("entry"),
                "game_path": data.get("game_path"),
            },
        )

    def repack(self, archive_id, replacements):
        self.config.require_development()
        data, original = self.read(archive_id, "asset_archive")
        rows = arc_table(original)
        if len(replacements) > 100:
            raise ToolFailure("asset_invalid", "At most 100 replacements per archive.")
        result, seen, changes = bytearray(original), set(), []
        for replacement in replacements:
            index = replacement["index"]
            if type(index) is not int or not 0 <= index < len(rows) or index in seen:
                raise ToolFailure("asset_invalid", "Duplicate or invalid replacement index.")
            seen.add(index)
            entry = rows[index]
            blob, value = self.read(replacement["artifact_id"], "asset_blob")
            before = unpack_entry(original, entry)
            expected = hashlib.sha256(before).hexdigest()
            if replacement["expected_sha256"] != expected or len(value) > MAX_ENTRY:
                raise ToolFailure("asset_conflict", "Original entry differs or replacement is too large.")
            packed = zlib.compress(value, 9)
            offset = (len(result) + 15) & ~15
            result.extend(b"\0" * (offset - len(result)))
            result.extend(packed)
            struct.pack_into(
                "<III",
                result,
                8 + index * 80 + 68,
                len(packed),
                len(value) | (entry["quality"] << 29),
                offset,
            )
            changes.append(
                {
                    "index": index,
                    "name": entry["name"],
                    "type_hash": entry["type_hash"],
                    "before": expected,
                    "after": blob["sha256"],
                    "replacement": replacement["artifact_id"],
                }
            )
        reparsed = arc_table(result)
        for change in changes:
            if hashlib.sha256(unpack_entry(result, reparsed[change["index"]])).hexdigest() != change["after"]:
                raise ToolFailure("asset_invalid", "Repacked payload did not verify.")
        return self.blob(
            bytes(result),
            {
                "game_path": data["game_path"],
                "entries": reparsed,
                "base_id": archive_id,
                "base_sha256": data["sha256"],
                "changes": changes,
            },
            "asset_archive",
        )
