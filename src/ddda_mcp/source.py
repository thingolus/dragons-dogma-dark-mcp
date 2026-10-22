"""Immutable Git source access; never executes the active checkout's scripts."""

import hashlib
import re
import subprocess
from pathlib import PurePosixPath

from .common import ToolFailure, read_json
from .config import Config


class Source:
    def __init__(self, config: Config):
        self.config = config
        self.commit = config.settings.coop_source_commit
        self._tree: dict[str, tuple[str, int]] | None = None
        self._blobs: dict[str, bytes] = {}

    def git(self, *args: str, stdin: bytes | None = None, timeout: int = 30) -> bytes:
        try:
            proc = subprocess.run(
                ["git", "-C", str(self.config.source), *args],
                input=stdin,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ToolFailure("source_unavailable", "Cannot read the configured Git source.") from exc
        if proc.returncode:
            raise ToolFailure("source_unavailable", proc.stderr.decode("utf-8", errors="replace")[:1000])
        return proc.stdout

    def tree(self) -> dict[str, tuple[str, int]]:
        if self._tree is None:
            resolved = self.git("rev-parse", "--verify", f"{self.commit}^{{commit}}").decode().strip()
            if resolved != self.commit:
                raise ToolFailure("source_mismatch", "Upstream commit does not resolve exactly.")
            rows = self.git("ls-tree", "-r", "-l", "-z", self.commit).split(b"\0")
            tree = {}
            for row in rows:
                if not row:
                    continue
                meta, name = row.split(b"\t", 1)
                mode, kind, sha, size = meta.split()
                if kind == b"blob" and mode in (b"100644", b"100755"):
                    tree[name.decode("utf-8")] = (sha.decode(), int(size))
            self._tree = tree
        return self._tree

    def read_many(self, paths: list[str]) -> dict[str, bytes]:
        tree = self.tree()
        for path in paths:
            if path not in tree:
                raise ToolFailure("source_not_found", f"No regular file at the pinned commit: {path}")
            if tree[path][1] > 2 * 1024 * 1024:
                raise ToolFailure("source_too_large", f"Source exceeds 2 MiB: {path}")
        missing = list(dict.fromkeys(p for p in paths if p not in self._blobs))
        if missing:
            raw = self.git("cat-file", "--batch", stdin="".join(tree[p][0] + "\n" for p in missing).encode())
            offset = 0
            for path in missing:
                end = raw.index(b"\n", offset)
                sha, kind, length = raw[offset:end].split()
                length = int(length)
                value = raw[end + 1 : end + 1 + length]
                expected = hashlib.sha1(f"blob {length}\0".encode() + value).hexdigest()
                if kind != b"blob" or sha.decode() != tree[path][0] or expected != sha.decode():
                    raise ToolFailure("source_mismatch", f"Git blob verification failed: {path}")
                self._blobs[path] = value
                offset = end + length + 2
        return {path: self._blobs[path] for path in paths}

    def read(self, path: str) -> str:
        return self.read_many([path])[path].decode("utf-8-sig", errors="replace")

    def reference(self, path: str, line: int = 1) -> dict:
        sha, _ = self.tree()[path]
        return {
            "path": path,
            "line": line,
            "commit": self.commit,
            "git_blob_sha1": sha,
            "url": f"https://github.com/thingolus/ddda-local-coop/blob/{self.commit}/{path}#L{line}",
        }

    def verify(self) -> dict:
        manifest = read_json(self.config.root / "reuse-manifest.json")
        if manifest["upstream"]["commit"] != self.commit:
            raise ToolFailure("source_mismatch", "Config commit differs from the reviewed reuse manifest.")
        files = [f for group in manifest["components"] for f in group["files"]]
        for file in files:
            if self.tree().get(file["path"], (None,))[0] != file["git_blob_sha1"]:
                raise ToolFailure("source_mismatch", f"Source inventory mismatch: {file['path']}")
        return {"commit": self.commit, "verified_files": len(files), "dirty_inputs_used": False}

    def knowledge_paths(self) -> list[str]:
        return [
            p
            for p in self.tree()
            if (p.startswith("docs/") and p.endswith(".md"))
            or (p.startswith("research/EXP-") and p.endswith(".md"))
            or p in ("research/symbols.csv", "include/coop/supported_build.hpp")
        ]

    def read_lines(self, path: str, start_line: int, limit: int) -> dict:
        self.verify()
        if not 1 <= start_line or not 1 <= limit <= 100:
            raise ToolFailure("invalid_parameters", "start_line must be positive; limit must be 1–100.")
        if PurePosixPath(path).suffix not in {
            ".md",
            ".py",
            ".cpp",
            ".hpp",
            ".h",
            ".js",
            ".csv",
            ".ps1",
            ".txt",
            ".java",
            ".json",
        }:
            raise ToolFailure("invalid_parameters", "Only text source formats may be read.")
        lines = self.read(path).splitlines()
        chunk, chars = [], 0
        for index in range(start_line - 1, min(len(lines), start_line - 1 + limit)):
            text = lines[index][:2000]
            if chars + len(text) > 10000:
                break
            chunk.append({"line": index + 1, "text": text, "line_truncated": len(lines[index]) > len(text)})
            chars += len(text)
        next_line = start_line + len(chunk)
        return {
            "source": self.reference(path, start_line),
            "lines": chunk,
            "total_lines": len(lines),
            "next_line": next_line if next_line <= len(lines) else None,
        }

    def symbols(self) -> list[dict]:
        import csv
        import io

        records: dict[str, dict] = {}
        for row in csv.DictReader(io.StringIO(self.read("research/symbols.csv"))):
            name = row["symbol"]
            records[name] = {
                "name": name,
                "research": row,
                "sources": [self.reference("research/symbols.csv")],
            }
        header = self.read("include/coop/supported_build.hpp")
        pattern = r'\{"([a-zA-Z0-9_]+)",\s*(0x[0-9a-fA-F]+),\s*\{([^}]+)\}'
        for match in re.finditer(pattern, header):
            name, address, values = match.groups()
            record = records.setdefault(name, {"name": name, "sources": []})
            signature = bytes(int(x.strip(), 0) for x in values.split(",") if x.strip())
            record["runtime_signature"] = {"rva": address.lower(), "bytes": signature.hex(" ")}
            record["sources"].append(
                self.reference("include/coop/supported_build.hpp", header[: match.start()].count("\n") + 1)
            )
        return list(records.values())
