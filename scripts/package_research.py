"""Reproduce the curated, licensed text snapshot from immutable Git objects.

Never reads the working tree or game files. Maintainers review the resulting diff
before release. A full co-op checkout remains optional for build/control features.
"""

import hashlib
import json
import subprocess
from pathlib import Path

from ddda_mcp.compatibility import WATCHED
from ddda_mcp.config import Config
from ddda_mcp.source import Source

ROOT = Path(__file__).resolve().parents[1]


def package():
    config = Config.load(ROOT)
    source = Source(config)
    source.verify()
    manifest = json.loads((ROOT / "reuse-manifest.json").read_text())
    paths = {f["path"] for c in manifest["components"] for f in c["files"]}
    paths.update(WATCHED)
    paths.update(
        ("LICENSE", "config/ddcoop.ini", "src/native_offline.cpp", "include/coop/native_offline.hpp")
    )
    rows = {}
    for path, raw in source.read_many(sorted(paths)).items():
        if b"\0" in raw or len(raw) > 2 * 1024 * 1024:
            raise ValueError(f"Not bounded text: {path}")
        rows[path] = {"git_blob_sha1": source.tree()[path][0], "text": raw.decode("utf-8")}
    pins = json.loads(source.read("tools.lock.json"))
    pin = next(p["commit"] for p in pins["sources"] if p["name"] == "minhook")
    repo = config.source / "external/minhook"
    names = (
        subprocess.check_output(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", pin])
        .decode()
        .splitlines()
    )
    vendor = {}
    for name in names:
        if name in {"CMakeLists.txt", "LICENSE.txt", "AUTHORS.txt"} or name.startswith(
            ("src/", "include/", "cmake/", "dll_resources/")
        ):
            raw = subprocess.check_output(["git", "-C", str(repo), "show", f"{pin}:{name}"])
            vendor[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "text": raw.decode("utf-8")}
    payload = {
        "commit": source.commit,
        "reuse_manifest": manifest,
        "files": rows,
        "minhook": {"commit": pin, "files": vendor},
    }
    target = ROOT / "src/ddda_mcp/pinned_research.json"
    target.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"Packaged {len(rows)} pinned research files and {len(vendor)} MinHook source/license files ({target.stat().st_size} bytes)."
    )


if __name__ == "__main__":
    package()
