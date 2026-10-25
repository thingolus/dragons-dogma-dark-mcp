"""DDDA TEX 0x99 / DDS round trips and BC texture previews. MIT, Thingolus.

The original TEX metadata and mip offsets are retained on import. Decoding is
for inspection: channel-packed normal/material maps are shown as stored RGBA.
"""

import hashlib
import struct
import zlib

from .assets import MAX_ENTRY, relative_name
from .common import ToolFailure, contained, digest

FORMATS = {20: b"DXT1", 25: b"DXT1", 24: b"DXT5", 31: b"DXT5", 47: b"DXT5"}


def texture(raw):
    if not 20 <= len(raw) <= MAX_ENTRY or raw[:4] != b"TEX\0":
        raise ToolFailure("texture_unsupported", "Expected DDDA TEX 0x99.")
    a, b, c = struct.unpack_from("<3I", raw, 4)
    version, mips, width, height, images, kind, depth = (
        a & 0xFFF,
        b & 63,
        (b >> 6) & 8191,
        b >> 19,
        c & 255,
        (c >> 8) & 255,
        (c >> 16) & 8191,
    )
    if version != 0x99 or not 1 <= mips <= 14 or not 1 <= width <= 8191 or not 1 <= height <= 8191:
        raise ToolFailure("texture_invalid", "Invalid TEX version, dimensions or mip count.")
    if images != 1 or depth != 1 or kind not in FORMATS:
        raise ToolFailure("texture_unsupported", "Only single-surface 2D BC1/BC3 textures are supported.")
    if len(raw) < 16 + 4 * mips or mips > max(width, height).bit_length():
        raise ToolFailure("texture_invalid", "Invalid mip table.")
    spans = []
    for i in range(mips):
        offset = struct.unpack_from("<I", raw, 16 + i * 4)[0]
        w, h = max(1, width >> i), max(1, height >> i)
        size = ((w + 3) // 4) * ((h + 3) // 4) * (8 if FORMATS[kind] == b"DXT1" else 16)
        if (
            offset < 16 + 4 * mips
            or offset + size > len(raw)
            or (spans and offset < spans[-1][0] + spans[-1][1])
        ):
            raise ToolFailure("texture_invalid", "Overlapping or truncated TEX mip payload.")
        spans.append((offset, size, w, h))
    if spans[-1][0] + spans[-1][1] != len(raw):
        raise ToolFailure("texture_invalid", "Unexpected trailing TEX data.")
    return {
        "width": width,
        "height": height,
        "mips": mips,
        "type": kind,
        "fourcc": FORMATS[kind].decode(),
        "spans": spans,
    }


def to_dds(raw):
    spec = texture(raw)
    words = [0] * 31
    words[0:7] = [
        124,
        0x81007 | (0x20000 if spec["mips"] > 1 else 0),
        spec["height"],
        spec["width"],
        spec["spans"][0][1],
        0,
        spec["mips"],
    ]
    words[18:21] = [32, 4, int.from_bytes(spec["fourcc"].encode(), "little")]
    words[26] = 0x1000 | (0x400008 if spec["mips"] > 1 else 0)
    return b"DDS " + struct.pack("<31I", *words) + b"".join(raw[o : o + n] for o, n, _, _ in spec["spans"])


def from_dds(original, dds):
    spec = texture(original)
    if not 128 <= len(dds) <= MAX_ENTRY + 128 or dds[:4] != b"DDS ":
        raise ToolFailure("texture_invalid", "Expected a bounded DDS file.")
    words = struct.unpack_from("<31I", dds, 4)
    if (
        words[0] != 124
        or words[2:4] != (spec["height"], spec["width"])
        or words[6] != spec["mips"]
        or words[18:21] != (32, 4, int.from_bytes(spec["fourcc"].encode(), "little"))
        or words[5] != 0
        or words[27] != 0
    ):
        raise ToolFailure(
            "texture_incompatible", "DDS dimensions, mips, format or surface type differ from TEX."
        )
    expected = 128 + sum(n for _, n, _, _ in spec["spans"])
    if len(dds) != expected:
        raise ToolFailure("texture_invalid", "DDS payload length differs from its mip chain.")
    result, pos = bytearray(original), 128
    for offset, size, _, _ in spec["spans"]:
        result[offset : offset + size] = dds[pos : pos + size]
        pos += size
    texture(result)
    if to_dds(result)[128:] != dds[128:]:
        raise ToolFailure("texture_roundtrip", "Texture import failed readback.")
    return bytes(result)


def rgb565(value):
    return ((value >> 11) * 255 // 31, ((value >> 5) & 63) * 255 // 63, (value & 31) * 255 // 31)


def decode(raw, mip=0):
    spec = texture(raw)
    if not 0 <= mip < spec["mips"]:
        raise ToolFailure("texture_invalid", "Select an existing mip level.")
    offset, _, w, h = spec["spans"][mip]
    if w * h > 4194304:
        raise ToolFailure("texture_preview_limit", "Preview a smaller mip; limit is four million pixels.")
    result = bytearray(w * h * 4)
    bc3 = spec["fourcc"] == "DXT5"
    for by in range((h + 3) // 4):
        for bx in range((w + 3) // 4):
            alpha = [255] * 16
            if bc3:
                a, b = raw[offset : offset + 2]
                palette = [a, b]
                if a > b:
                    palette += [((7 - i) * a + i * b) // 7 for i in range(1, 7)]
                else:
                    palette += [((5 - i) * a + i * b) // 5 for i in range(1, 5)] + [0, 255]
                indices = int.from_bytes(raw[offset + 2 : offset + 8], "little")
                alpha = [palette[(indices >> (3 * i)) & 7] for i in range(16)]
                offset += 8
            c0, c1, indices = struct.unpack_from("<HHI", raw, offset)
            offset += 8
            first, second = rgb565(c0), rgb565(c1)
            colors = [(*first, 255), (*second, 255)]
            if c0 > c1 or bc3:
                colors += [
                    tuple((2 * a + b) // 3 for a, b in zip(first, second, strict=True)) + (255,),
                    tuple((a + 2 * b) // 3 for a, b in zip(first, second, strict=True)) + (255,),
                ]
            else:
                colors += [
                    tuple((a + b) // 2 for a, b in zip(first, second, strict=True)) + (255,),
                    (0, 0, 0, 0),
                ]
            for i in range(16):
                x, y = bx * 4 + i % 4, by * 4 + i // 4
                if x < w and y < h:
                    color = colors[(indices >> (2 * i)) & 3]
                    at = 4 * (y * w + x)
                    result[at : at + 4] = bytes((*color[:3], alpha[i] if bc3 else color[3]))
    return w, h, bytes(result)


def png(w, h, rgba):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        )

    rows = b"".join(b"\0" + rgba[i * w * 4 : (i + 1) * w * 4] for i in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class Textures:
    def __init__(self, assets):
        self.assets, self.config = assets, assets.config

    def export(self, entry_id, mip=0):
        data, raw = self.assets.read(entry_id, "asset_blob")
        spec = texture(raw)
        w, h, rgba = decode(raw, mip)
        root = self.config.artifacts / "texture-exports" / data["sha256"]
        root.mkdir(parents=True, exist_ok=True)
        outputs = {"texture.dds": to_dds(raw), f"mip-{mip}.png": png(w, h, rgba)}
        for name, content in outputs.items():
            path = root / name
            if path.exists() and path.read_bytes() != content:
                raise ToolFailure(
                    "texture_changed",
                    "Export already exists with different content; preserve external edits separately.",
                )
            if not path.exists():
                path.write_bytes(content)
        return {
            "entry_id": entry_id,
            "spec": {k: v for k, v in spec.items() if k != "spans"},
            "dds_path": str(root / "texture.dds"),
            "preview_path": str(root / f"mip-{mip}.png"),
            "dds_sha256": hashlib.sha256(outputs["texture.dds"]).hexdigest(),
            "preview_note": "Stored channels; no normal-map reconstruction or color-space conversion.",
        }

    def replace(self, entry_id, source_name, relative_path, expected_sha256):
        self.config.require_development()
        source = self.config.settings.mod_sources.get(source_name)
        if source is None:
            raise ToolFailure("mod_source", "Select a configured mod_sources directory.")
        root = (self.config.root / source).resolve()
        path = contained(root, root / relative_name(relative_path))
        if (
            path.suffix.lower() != ".dds"
            or path.stat().st_size > MAX_ENTRY + 128
            or digest(path) != expected_sha256
        ):
            raise ToolFailure("texture_changed", "DDS file type, size or expected hash differs.")
        dds = path.read_bytes()
        if hashlib.sha256(dds).hexdigest() != expected_sha256:
            raise ToolFailure("texture_changed", "DDS changed during import.")
        data, raw = self.assets.read(entry_id, "asset_blob")
        changed = from_dds(raw, dds)
        return self.assets.blob(
            changed,
            {
                "base_id": entry_id,
                "base_sha256": data["sha256"],
                "format": "ddda_tex_0099",
                "entry": data.get("entry"),
                "game_path": data.get("game_path"),
                "dds_sha256": expected_sha256,
            },
        )
