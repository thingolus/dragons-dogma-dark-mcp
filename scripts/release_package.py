"""Audit distribution contents and stage versioned assets with SHA-256 checksums."""

import argparse
import hashlib
import os
import shutil
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"private", "artifacts", ".tools", ".venv", ".uv-cache", ".git", "__pycache__"}
ALLOWED_SUFFIXES = {".py", ".js", ".cjs", ".java", ".json", ".toml", ".lock", ".md", ".txt", ".ps1", ".pth"}


def audit_names(names):
    for name in names:
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or ":" in name
            or FORBIDDEN.intersection(path.parts)
            or path.name in {"local.json", ".env"}
            or path.name.startswith(".env.")
            or (path.suffix and path.suffix.lower() not in ALLOWED_SUFFIXES)
            or (
                not path.suffix
                and path.name not in {"LICENSE", "METADATA", "WHEEL", "RECORD", "PKG-INFO", ".gitignore"}
            )
        ):
            raise ValueError(f"Unexpected release member: {name}")


def stage(root=ROOT):
    project = tomllib.loads((root / "pyproject.toml").read_text())
    version = project["project"]["version"]
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/") and ref != f"refs/tags/v{version}":
        raise ValueError("Release tag must match pyproject version.")
    stem = f"dragons_dogma_dark_mcp-{version}"
    wheel = root / "dist" / (stem + "-py3-none-any.whl")
    source = root / "dist" / (stem + ".tar.gz")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        # Wheel metadata members have fixed extensionless names.
        audit_names(names)
        assert {
            "ddda_mcp/agent.js",
            "ddda_mcp/ExportMcp.java",
            "ddda_mcp/recipes.py",
            "ddda_mcp/death.py",
            "ddda_mcp/upstream_contract.json",
        } <= set(names)
        metadata = archive.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
        assert f"Version: {version}\n" in metadata and "Thingolus" in metadata
        assert any(n.endswith("/licenses/LICENSE") for n in names)
    with tarfile.open(source) as archive:
        members = archive.getmembers()
        assert all(m.isfile() or m.isdir() for m in members), "No links or devices in release archives"
        audit_names(m.name for m in members if m.isfile())
        names = {m.name for m in members}
        assert f"{stem}/docs/RELEASES.md" in names
        assert f"{stem}/uv.lock" in names
    destination = root / "dist/release"
    destination.mkdir(exist_ok=True)
    inputs = {
        wheel.name: wheel,
        source.name: source,
        "INSTALL.md": root / "docs/RELEASES.md",
        "LICENSE": root / "LICENSE",
        "CREDITS.md": root / "CREDITS.md",
    }
    unexpected = {p.name for p in destination.iterdir()} - set(inputs) - {"SHA256SUMS"}
    if unexpected:
        raise ValueError("Release staging contains unexpected/older assets; select a clean output directory.")
    lines = []
    for name, path in sorted(inputs.items()):
        shutil.copyfile(path, destination / name)
        lines.append(f"{hashlib.sha256((destination / name).read_bytes()).hexdigest()}  {name}")
    (destination / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"Audited {version}: {len(inputs)} assets, SHA256SUMS, no game/private files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    stage(parser.parse_args().root.resolve())
