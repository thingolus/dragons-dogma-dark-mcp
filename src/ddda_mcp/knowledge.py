"""Derived full-text index with immutable source references."""

import re
import sqlite3
import threading

from .common import ToolFailure
from .source import Source


class Knowledge:
    def __init__(self, source: Source):
        self.source = source
        self.lock = threading.RLock()
        self.ready = False
        self.fts = True

    def _open(self) -> sqlite3.Connection:
        self.source.config.cache.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.source.config.cache / "knowledge.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def ensure(self) -> None:
        with self.lock:
            if self.ready:
                return
            self.source.verify()
            with self._open() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT)")
                current = db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()
                revision = "2:" + self.source.commit
                if current and current[0] == revision:
                    self.fts = db.execute("SELECT value FROM metadata WHERE key='fts'").fetchone()[0] == "1"
                    self.ready = True
                    return
                paths = self.source.knowledge_paths()
                blobs = self.source.read_many(paths)
                db.execute("DROP TABLE IF EXISTS passages")
                try:
                    db.execute(
                        "CREATE VIRTUAL TABLE passages USING fts5(path UNINDEXED,line UNINDEXED,topic,body)"
                    )
                    self.fts = True
                except sqlite3.OperationalError:
                    db.execute("CREATE TABLE passages(path TEXT,line INTEGER,topic TEXT,body TEXT)")
                    self.fts = False
                for path, blob in blobs.items():
                    lines = blob.decode("utf-8-sig", errors="replace").splitlines()
                    for start in range(0, len(lines), 18):
                        body = "\n".join(lines[start : start + 24])[:6000]
                        db.execute("INSERT INTO passages VALUES (?,?,?,?)", (path, start + 1, path, body))
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('revision',?)", (revision,))
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('fts',?)", (str(int(self.fts)),))
            self.ready = True

    def search(self, query: str, topic: str = "", offset: int = 0, limit: int = 10) -> dict:
        words = re.findall(r"[\w-]+", query, flags=re.UNICODE)
        if not words or len(query) > 256 or len(words) > 20 or len(topic) > 100:
            raise ToolFailure("invalid_query", "Use 1–20 search terms, up to 256 characters.")
        if not 0 <= offset <= 10000 or not 1 <= limit <= 20:
            raise ToolFailure("invalid_parameters", "offset must be 0–10000 and limit 1–20.")
        self.ensure()
        with self.lock, self._open() as db:
            if self.fts:
                expression = " AND ".join('"' + word.replace('"', '""') + '"' for word in words)
                rows = db.execute(
                    "SELECT path,line,body FROM passages WHERE passages MATCH ? AND instr(path,?)>0 "
                    "ORDER BY rank,path,line LIMIT ? OFFSET ?",
                    (expression, topic, limit + 1, offset),
                ).fetchall()
            else:
                clauses = " AND ".join("instr(lower(body),?)>0" for _ in words)
                rows = db.execute(
                    f"SELECT path,line,body FROM passages WHERE {clauses} AND instr(path,?)>0 "
                    "ORDER BY path,line LIMIT ? OFFSET ?",
                    (*[w.lower() for w in words], topic, limit + 1, offset),
                ).fetchall()
        return {
            "query": query,
            "search_engine": "sqlite_fts5" if self.fts else "bounded_text",
            "results": [
                {
                    "excerpt": row["body"][:650],
                    "excerpt_truncated": len(row["body"]) > 650,
                    "source": self.source.reference(row["path"], int(row["line"])),
                    "evidence_class": "source_document",
                    "warning": "Historical claims retain their original scope.",
                }
                for row in rows[:limit]
            ],
            "next_offset": offset + limit if len(rows) > limit else None,
        }

    def lookup(self, name_or_rva: str, offset: int = 0, limit: int = 5) -> dict:
        if not name_or_rva or len(name_or_rva) > 128 or not 1 <= limit <= 10 or not 0 <= offset <= 10000:
            raise ToolFailure("invalid_parameters", "Provide a symbol query and bounded pagination.")
        self.source.verify()
        query = name_or_rva.lower()
        matches = []
        for item in self.source.symbols():
            addresses = [
                item.get("research", {}).get("rva", ""),
                item.get("runtime_signature", {}).get("rva", ""),
            ]
            if (query.startswith("0x") and any(a.lower() == query for a in addresses)) or query in item[
                "name"
            ].lower():
                matches.append(item)
        matches.sort(key=lambda item: (item["name"].lower() != query, item["name"]))
        return {
            "symbols": matches[offset : offset + limit],
            "total_matches": len(matches),
            "next_offset": offset + limit if len(matches) > offset + limit else None,
            "warning": "Signatures identify a pinned build; research status is not permission to call native code.",
        }
