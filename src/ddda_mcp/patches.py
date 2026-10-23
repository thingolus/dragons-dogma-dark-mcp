"""Hash-checked source overlays and local build cache. MIT, Thingolus."""

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

from .common import ToolFailure, contained, digest


def edit_path(value):
    p = PurePosixPath(value)
    if (
        p.is_absolute()
        or len(p.parts) < 2
        or p.parts[0] not in {"src", "include", "tests"}
        or any(
            not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in {".", ".."} or part.endswith(".")
            for part in p.parts
        )
        or p.suffix not in {".cpp", ".hpp", ".h", ".c"}
    ):
        raise ToolFailure(
            "invalid_patch", "Only relative C/C++ files under src/include/tests can be overlaid."
        )
    return str(p)


class Patches:
    def __init__(self, source, artifacts):
        self.source, self.artifacts = source, artifacts

    def create(self, label, edits):
        self.source.config.require_development()
        if not label.strip() or len(label) > 120 or not 1 <= len(edits) <= 16:
            raise ToolFailure("invalid_patch", "Use a label and 1–16 bounded file replacements.")
        self.source.verify()
        normalized, seen = [], set()
        for edit in edits:
            path = edit_path(edit["path"])
            if path in seen or len(edit["content"].encode("utf-8")) > 131072 or "\x00" in edit["content"]:
                raise ToolFailure("invalid_patch", "Duplicate, binary or oversized replacement.")
            seen.add(path)
            existing = self.source.read(path).encode("utf-8") if path in self.source.tree() else None
            expected = hashlib.sha256(existing).hexdigest() if existing is not None else None
            if edit.get("expected_sha256") != expected:
                raise ToolFailure("patch_conflict", "Expected source hash differs: " + path)
            normalized.append(
                {
                    "path": path,
                    "expected_sha256": expected,
                    "content": edit["content"],
                    "sha256": hashlib.sha256(edit["content"].encode("utf-8")).hexdigest(),
                }
            )
        if sum(len(e["content"].encode("utf-8")) for e in normalized) > 524288:
            raise ToolFailure("invalid_patch", "Overlay exceeds 512 KiB.")
        return self.artifacts.put(
            "source_patch",
            {"label": label, "edits": normalized, "summary": {"files": len(normalized), "label": label}},
            {"source_commit": self.source.commit, "evidence_class": "authored_patch"},
        )

    def apply(self, patch_id, source_root, revision):
        doc = self.artifacts.get(patch_id)
        if doc["kind"] != "source_patch" or doc["provenance"]["source_commit"] != revision:
            raise ToolFailure("patch_conflict", "Overlay base differs from the selected build.")
        for edit in doc["data"]["edits"]:
            target = contained(source_root, source_root / edit_path(edit["path"]))
            if (digest(target) if target.exists() else None) != edit["expected_sha256"]:
                raise ToolFailure("patch_conflict", "Isolated source differs: " + edit["path"])
            encoded = edit["content"].encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != edit["sha256"]:
                raise ToolFailure("patch_conflict", "Overlay content hash differs.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encoded)
        return doc


def cache_key(source, cmake, configuration, test_group, patch_sha):
    """Local toolchain identity; cached CTest evidence retains its original capture time."""
    roots = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft Visual Studio",
        Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio",
    ]
    compilers = sorted(
        {
            str(p): digest(p)
            for root in roots
            for p in root.glob("2022/*/VC/Tools/MSVC/*/bin/Hostx64/x86/cl.exe")
        }.items()
    )
    # Without a known compiler identity, skip caching rather than trusting just PATH.
    if not compilers:
        return None
    value = {
        "version": 1,
        "source": source.commit,
        "tools": source.read("tools.lock.json"),
        "cmake": digest(Path(cmake)),
        "compilers": compilers,
        "configuration": configuration,
        "test_group": test_group,
        "patch": patch_sha,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
