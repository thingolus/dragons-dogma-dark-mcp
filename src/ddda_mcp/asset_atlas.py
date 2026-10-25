"""Private searchable cross-archive catalog. Copyright (c) 2026 Thingolus. MIT."""

import asyncio
import hashlib
import sqlite3
import struct
import uuid
from contextlib import contextmanager

from .assets import MAX_ARCHIVE, relative_name
from .common import ToolFailure, contained, digest
from .game_parameters import parse


def archive_header(path):
    """Read only the bounded index: a full game scan does not copy 18 GB of assets."""
    size = path.stat().st_size
    with path.open("rb") as stream:
        head = stream.read(8)
        if len(head) != 8 or head[:6] != b"ARC\0\x07\0" or size > MAX_ARCHIVE:
            raise ToolFailure("archive_unsupported", "Expected a bounded ARC v7 archive.")
        n = struct.unpack_from("<H", head, 6)[0]
        if not 1 <= n <= 8192:
            raise ToolFailure("archive_invalid", "Archive index count is out of bounds.")
        table = stream.read(80 * n)
    if len(table) != 80 * n:
        raise ToolFailure("archive_invalid", "Truncated archive index.")
    rows, keys, spans = [], set(), []
    for i in range(n):
        name, kind, packed, flags, at = struct.unpack_from("<64sIIII", table, 80 * i)
        try:
            name = name.split(b"\0", 1)[0].decode("ascii")
        except UnicodeError as exc:
            raise ToolFailure("archive_invalid", "Invalid archive entry name.") from exc
        key = (name.casefold(), kind)
        if not name or key in keys or at < 8 + 80 * n or packed < 1 or at + packed > size:
            raise ToolFailure("archive_invalid", "Invalid archive payload or duplicate entry.")
        keys.add(key)
        spans.append((at, at + packed))
        rows.append((i, name, name.replace("\\", "/").casefold(), kind, flags & 0x1FFFFFFF))
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:], strict=False)):
        raise ToolFailure("archive_invalid", "Overlapping archive payloads.")
    return hashlib.sha256(head + table).hexdigest(), size, rows


class AssetAtlas:
    def __init__(self, assets):
        self.assets, self.config = assets, assets.config
        self.root = self.config.artifacts / "asset-indexes"

    async def build(self, query=""):
        self.config.require_development()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (uuid.uuid4().hex + ".sqlite3")
        connection = sqlite3.connect(path)
        failures, count, entries = [], 0, 0
        complete = False
        try:
            connection.executescript("""
                CREATE TABLE archives(id INTEGER PRIMARY KEY,path TEXT UNIQUE,header_sha256 TEXT,bytes INTEGER);
                CREATE TABLE assets(id INTEGER PRIMARY KEY,archive INTEGER,entry INTEGER,name TEXT,normalized TEXT,type_hash INTEGER,bytes INTEGER);
                CREATE INDEX asset_name ON assets(normalized,type_hash);
            """)
            root = contained(self.config.game, self.config.game / "nativePC")
            paths = sorted(p for p in root.rglob("*.arc") if query.casefold() in p.as_posix().casefold())
            if len(paths) > 10000:
                raise ToolFailure("index_limit", "Index at most 10,000 archives in one catalog.")
            for p in paths:
                p = contained(root, p)
                name = p.relative_to(self.config.game).as_posix()
                try:
                    sha, size, rows = archive_header(p)
                except (OSError, ToolFailure) as exc:
                    failures.append({"archive": name, "error": str(exc)[:200]})
                    continue
                count += 1
                connection.execute("INSERT INTO archives VALUES(?,?,?,?)", (count, name, sha, size))
                connection.executemany(
                    "INSERT INTO assets(archive,entry,name,normalized,type_hash,bytes) VALUES(?,?,?,?,?,?)",
                    [(count, *r) for r in rows],
                )
                entries += len(rows)
                if entries > 2000000:
                    raise ToolFailure("index_limit", "Asset catalog exceeded two million entries.")
                if count % 50 == 0:
                    connection.commit()
                    await asyncio.sleep(0)
            connection.commit()
            complete = True
        finally:
            connection.close()
            if not complete:
                path.unlink(missing_ok=True)
        sha = digest(path)
        summary = {"archives": count, "assets": entries, "failed_archives": len(failures)}
        return {
            **self.assets.artifacts.put(
                "asset_index",
                {"file": path.name, "sha256": sha, "summary": summary, "failures": failures, "query": query},
                {"evidence_class": "archive_index", "private": True},
            ),
            "summary": summary,
        }

    @contextmanager
    def connect(self, index_id):
        doc = self.assets.artifacts.get(index_id)
        if doc["kind"] != "asset_index":
            raise ToolFailure("index_invalid", "Select an asset index artifact.")
        path = contained(self.root, self.root / relative_name(doc["data"]["file"]))
        if path.stat().st_size > 512 * 1024 * 1024 or digest(path) != doc["data"]["sha256"]:
            raise ToolFailure("index_changed", "Asset index hash changed.")
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def search(self, index_id, query="", duplicates_only=False, type_hash=None, offset=0, limit=20):
        with self.connect(index_id) as db:
            where = "instr(a.normalized,?) > 0"
            params = [query.replace("\\", "/").casefold()]
            if type_hash is not None:
                where += " AND a.type_hash=?"
                params.append(type_hash)
            if duplicates_only:
                where += " AND EXISTS (SELECT 1 FROM assets b WHERE b.normalized=a.normalized AND b.type_hash=a.type_hash AND b.id!=a.id)"
            total = db.execute("SELECT COUNT(*) FROM assets a WHERE " + where, params).fetchone()[0]
            rows = db.execute(
                "SELECT a.id,a.entry,a.name,a.type_hash,a.bytes,r.path AS archive FROM assets a JOIN archives r ON a.archive=r.id WHERE "
                + where
                + " ORDER BY a.id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {
            "assets": [dict(r) for r in rows],
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "duplicate_meaning": "Same logical name and type; payload equality requires extraction/hash comparison.",
        }

    def extract(self, index_id, asset_id):
        with self.connect(index_id) as db:
            row = db.execute(
                "SELECT a.entry,r.path,r.header_sha256,r.bytes FROM assets a JOIN archives r ON a.archive=r.id WHERE a.id=?",
                (asset_id,),
            ).fetchone()
        if row is None:
            raise ToolFailure("asset_not_found", "No asset with this index ID.")
        path = contained(self.config.game, self.config.game / relative_name(row["path"]))
        sha, size, _ = archive_header(path)
        if sha != row["header_sha256"] or size != row["bytes"]:
            raise ToolFailure("index_stale", "Archive index changed; rebuild the catalog.")
        archive = self.assets.open(row["path"])
        _, snapshot = self.assets.read(archive["artifact_id"], "asset_archive")
        count = struct.unpack_from("<H", snapshot, 6)[0]
        if (
            len(snapshot) != row["bytes"]
            or hashlib.sha256(snapshot[: 8 + 80 * count]).hexdigest() != row["header_sha256"]
        ):
            raise ToolFailure("index_stale", "Archive header changed during extraction; rebuild the catalog.")
        return self.assets.extract(archive["artifact_id"], row["entry"])

    def references(self, index_id, entry_id, offset=0, limit=20):
        _, raw = self.assets.read(entry_id, "asset_blob")
        _, fields = parse(raw)
        candidates = [
            (f.path, f.value.replace("\\", "/").casefold())
            for f in fields
            if f.type == "string" and ("\\" in f.value or "/" in f.value)
        ]
        rows = []
        with self.connect(index_id) as db:
            for field, value in candidates[offset : offset + limit]:
                matches = db.execute(
                    "SELECT a.id,a.name,a.type_hash,r.path AS archive FROM assets a JOIN archives r ON a.archive=r.id WHERE a.normalized=? ORDER BY a.id LIMIT 101",
                    (value,),
                ).fetchall()
                rows.append(
                    {
                        "field": field,
                        "value": value,
                        "matches": [dict(r) for r in matches[:100]],
                        "matches_truncated": len(matches) > 100,
                        "evidence": "serialized_string_exact_path_match",
                    }
                )
        return {
            "references": rows,
            "total": len(candidates),
            "next_offset": offset + limit if offset + limit < len(candidates) else None,
            "limitations": "Matching serialized paths are reference candidates; runtime loading and indirect references are not inferred.",
        }
