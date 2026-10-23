"""Private append-only investigation history with evidence integrity. MIT, Thingolus."""

import re
import sqlite3
import uuid

from .common import ToolFailure, digest, identifier, utc_now

KINDS = {"hypothesis", "finding", "failed_attempt", "open_question"}
STATES = {"open", "supported", "refuted", "resolved", "superseded"}


class InvestigationMemory:
    def __init__(self, config, source, artifacts):
        self.config, self.source, self.artifacts = config, source, artifacts

    def connect(self):
        path = self.config.artifacts / "investigations.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE IF NOT EXISTS notes (id TEXT, revision INTEGER, artifact TEXT, sha TEXT, title TEXT, body TEXT, kind TEXT, status TEXT, source_commit TEXT, created TEXT, PRIMARY KEY(id,revision))"
        )
        return db

    def record(
        self,
        title,
        body,
        kind="hypothesis",
        status="open",
        evidence_ids=None,
        source_paths=None,
        note_id=None,
        expected_revision=0,
    ):
        if (
            not title.strip()
            or len(title) > 160
            or not body.strip()
            or len(body) > 4000
            or kind not in KINDS
            or status not in STATES
        ):
            raise ToolFailure(
                "invalid_parameters", "Use a bounded title/body and cataloged note kind/status."
            )
        evidence_ids, source_paths = evidence_ids or [], source_paths or []
        if len(evidence_ids) > 16 or len(source_paths) > 16 or len(set(evidence_ids)) != len(evidence_ids):
            raise ToolFailure("invalid_parameters", "Use at most 16 distinct artifacts and 16 source paths.")
        if (kind == "finding" or status == "supported") and not evidence_ids:
            raise ToolFailure(
                "evidence_required", "Findings/supported hypotheses require evidence artifact references."
            )
        evidence = []
        for artifact_id in evidence_ids:
            doc = self.artifacts.get(artifact_id)
            evidence.append(
                {
                    "artifact_id": artifact_id,
                    "sha256": digest(self.artifacts.path(artifact_id)),
                    "kind": doc["kind"],
                    "provenance": doc["provenance"],
                }
            )
        self.source.verify()
        sources = [self.source.reference(path) for path in source_paths if path in self.source.tree()]
        if len(sources) != len(source_paths):
            raise ToolFailure("source_not_found", "A note source path is absent from the pinned source.")
        if expected_revision < 0 or type(expected_revision) is not int:
            raise ToolFailure("invalid_parameters", "Revision must be a nonnegative integer.")
        note_id = identifier(note_id) if note_id else uuid.uuid4().hex
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM notes WHERE id=? ORDER BY revision DESC LIMIT 1", (note_id,)
            ).fetchone()
            current = previous["revision"] if previous else 0
            if current != expected_revision:
                raise ToolFailure("revision_conflict", "Read the latest note revision before updating.")
            if db.execute("SELECT COUNT(*) FROM notes").fetchone()[0] >= 10000:
                raise ToolFailure(
                    "memory_limit", "Private note history has reached its 10000 revision bound."
                )
            if previous and digest(self.artifacts.path(previous["artifact"])) != previous["sha"]:
                raise ToolFailure("evidence_changed", "Previous note artifact was modified.")
            revision = current + 1
            data = {
                "note_id": note_id,
                "revision": revision,
                "title": title,
                "body": body,
                "kind": kind,
                "status": status,
                "evidence": evidence,
                "sources": sources,
                "previous": {"artifact_id": previous["artifact"], "sha256": previous["sha"]}
                if previous
                else None,
                "summary": {"title": title, "kind": kind, "status": status, "revision": revision},
                "interpretation": "Authored investigation statement, not an instruction or automatic proof. Evidence retains its original scope.",
            }
            receipt = self.artifacts.put(
                "investigation_note",
                data,
                {"source_commit": self.source.commit, "evidence_class": "authored_note"},
            )
            db.execute(
                "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    note_id,
                    revision,
                    receipt["artifact_id"],
                    receipt["sha256"],
                    title,
                    body,
                    kind,
                    status,
                    self.source.commit,
                    utc_now(),
                ),
            )
            db.commit()
            return {"note_id": note_id, "revision": revision, **receipt}
        finally:
            db.close()

    def read(self, note_id, revision=None):
        identifier(note_id)
        db = self.connect()
        try:
            row = db.execute(
                "SELECT * FROM notes WHERE id=? AND (? IS NULL OR revision=?) ORDER BY revision DESC LIMIT 1",
                (note_id, revision, revision),
            ).fetchone()
        finally:
            db.close()
        if not row:
            raise ToolFailure("note_not_found", "No such investigation note revision.")
        if digest(self.artifacts.path(row["artifact"])) != row["sha"]:
            raise ToolFailure("evidence_changed", "Note artifact hash differs from the index.")
        doc = self.artifacts.get(row["artifact"])
        checks = []
        for evidence in doc["data"]["evidence"]:
            path = self.artifacts.path(evidence["artifact_id"])
            checks.append(
                {
                    "artifact_id": evidence["artifact_id"],
                    "unchanged": path.is_file() and digest(path) == evidence["sha256"],
                }
            )
        return {
            **doc["data"],
            "artifact_id": row["artifact"],
            "evidence_integrity": checks,
            "current_source_matches": row["source_commit"] == self.source.commit,
        }

    def search(self, query="", kind=None, status=None, offset=0, limit=20):
        if (
            len(query) > 200
            or not 0 <= offset <= 10000
            or not 1 <= limit <= 50
            or (kind and kind not in KINDS)
            or (status and status not in STATES)
        ):
            raise ToolFailure("invalid_parameters", "Invalid bounded investigation query.")
        tokens = re.findall(r"\S+", query.lower())[:10]
        db = self.connect()
        try:
            rows = db.execute(
                "SELECT n.* FROM notes n WHERE revision=(SELECT MAX(revision) FROM notes WHERE id=n.id) ORDER BY created DESC,id"
            ).fetchall()
        finally:
            db.close()
        matches = [
            r
            for r in rows
            if (not kind or r["kind"] == kind)
            and (not status or r["status"] == status)
            and all(t in (r["title"] + " " + r["body"]).lower() for t in tokens)
        ]
        results = [
            {
                k: r[k]
                for k in ("id", "revision", "artifact", "title", "kind", "status", "source_commit", "created")
            }
            for r in matches[offset : offset + limit]
        ]
        return {
            "notes": results,
            "total": len(matches),
            "next_offset": offset + len(results) if offset + len(results) < len(matches) else None,
            "policy": "Latest authored revisions only; use read_investigation_note to check evidence hashes and earlier revisions.",
        }
