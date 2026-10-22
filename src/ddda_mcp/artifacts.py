"""Local evidence catalog. Artifact IDs never resolve to caller-supplied paths."""

import json
import uuid

from .common import ToolFailure, atomic_json, contained, digest, identifier, read_json, utc_now
from .config import Config


class Artifacts:
    def __init__(self, config: Config):
        self.config = config

    def path(self, artifact_id: str):
        return contained(self.config.artifacts, self.config.artifacts / f"{identifier(artifact_id)}.json")

    def put(self, kind: str, data: dict, provenance: dict) -> dict:
        artifact_id = uuid.uuid4().hex
        document = {
            "schema_version": 1,
            "id": artifact_id,
            "kind": kind,
            "created_at": utc_now(),
            "provenance": provenance,
            "data": data,
        }
        if (
            len((json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode())
            > self.config.settings.limits.max_trace_bytes
        ):
            raise ToolFailure("result_too_large", "Artifact exceeds the configured byte limit.")
        path = self.path(artifact_id)
        atomic_json(path, document)
        return {
            "artifact_id": artifact_id,
            "uri": f"ddda://runs/{artifact_id}/summary",
            "sha256": digest(path),
        }

    def get(self, artifact_id: str) -> dict:
        path = self.path(artifact_id)
        if not path.is_file():
            raise ToolFailure("artifact_not_found", "No artifact with that ID exists in this project.")
        document = read_json(path, self.config.settings.limits.max_trace_bytes)
        if document.get("id") != artifact_id or document.get("schema_version") != 1:
            raise ToolFailure("artifact_invalid", "Artifact identity/schema mismatch.")
        return document

    def read_page(self, artifact_id: str, start_line: int = 1, limit: int = 40) -> dict:
        if start_line < 1 or not 1 <= limit <= 100:
            raise ToolFailure("invalid_parameters", "Use positive start_line and limit 1–100.")
        doc = self.get(artifact_id)
        raw_lines = json.dumps(doc, indent=2, ensure_ascii=False).splitlines()
        # Split long JSON strings into display lines without dropping their content.
        # Pagination uses these display lines so even one huge string can be read fully.
        lines = [line[i : i + 2000] for line in raw_lines for i in range(0, max(1, len(line)), 2000)]
        selected, count = [], 0
        for line in lines[start_line - 1 : start_line - 1 + limit]:
            if count + len(line) > 10000:
                break
            selected.append(line)
            count += len(selected[-1])
        return {
            "artifact_id": artifact_id,
            "kind": doc["kind"],
            "line_format": "JSON display lines; original lines longer than 2000 characters are wrapped",
            "lines": selected,
            "start_line": start_line,
            "total_lines": len(lines),
            "next_line": start_line + len(selected) if start_line + len(selected) <= len(lines) else None,
        }

    def summary(self, artifact_id: str) -> dict:
        doc = self.get(artifact_id)
        return {
            "artifact_id": artifact_id,
            "kind": doc["kind"],
            "created_at": doc["created_at"],
            "provenance": doc["provenance"],
            "summary": doc["data"].get("summary", {}),
            "read_more": "Use read_artifact with this artifact ID for paginated evidence.",
        }

    def compare(self, before_id: str, after_id: str) -> dict:
        before, after = self.get(before_id), self.get(after_id)
        for key in ("game_sha256", "evidence_class", "recipe"):
            if before["provenance"].get(key) != after["provenance"].get(key):
                raise ToolFailure("incompatible_evidence", f"Runs differ in {key}; comparison refused.")
        if before["kind"] != after["kind"]:
            raise ToolFailure("incompatible_evidence", "Artifact kinds differ.")
        first, second = before["data"].get("summary", {}), after["data"].get("summary", {})
        metrics = {
            key: {"before": value, "after": second[key], "delta": second[key] - value}
            for key, value in first.items()
            if type(value) in (int, float) and type(second.get(key)) in (int, float)
        }
        return {
            "before": before_id,
            "after": after_id,
            "metrics": metrics,
            "changed_inputs": {
                k: [v, after["provenance"].get(k)]
                for k, v in before["provenance"].items()
                if after["provenance"].get(k) != v
            },
            "conclusion": "Measured differences only; no automatic gameplay acceptance or speedup claim.",
        }
