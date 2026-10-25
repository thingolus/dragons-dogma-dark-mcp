"""Audit distribution contents and stage versioned assets with SHA-256 checksums."""

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"private", "artifacts", ".tools", ".venv", ".uv-cache", ".git", "__pycache__"}
ALLOWED_SUFFIXES = {
    ".py",
    ".js",
    ".cjs",
    ".java",
    ".json",
    ".toml",
    ".lock",
    ".md",
    ".txt",
    ".ps1",
    ".pth",
    ".cpp",
    ".hpp",
}


def audit_snapshot(raw):
    doc = json.loads(raw)
    assert len(doc["commit"]) == 40
    assert "LICENSE" in doc["files"] and "LICENSE.txt" in doc["minhook"]["files"]
    for group, key in ((doc["files"], "git_blob_sha1"), (doc["minhook"]["files"], "sha256")):
        for name, row in group.items():
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or FORBIDDEN.intersection(path.parts)
                or "\\" in name
                or ":" in name
            ):
                raise ValueError(f"Unexpected bundled source: {name}")
            if (
                path.suffix
                not in {
                    ".md",
                    ".py",
                    ".js",
                    ".java",
                    ".cpp",
                    ".hpp",
                    ".h",
                    ".c",
                    ".csv",
                    ".txt",
                    ".json",
                    ".ini",
                    ".def",
                    ".rc",
                    ".in",
                    ".ps1",
                }
                and name != "LICENSE"
            ):
                raise ValueError(f"Unexpected bundled source type: {name}")
            content = row["text"].encode("utf-8")
            assert b"\0" not in content and len(content) <= 2 * 1024 * 1024
            actual = (
                hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
                if key == "git_blob_sha1"
                else hashlib.sha256(content).hexdigest()
            )
            assert actual == row[key], f"Bundled source hash differs: {name}"


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


def make_nexus_archive(source, quickstart, destination, version):
    """Repack audited source files directly; Nexus rejects nested archives."""
    source_root = f"dragons_dogma_dark_mcp-{version}"
    zip_root = f"Dragons-Dogma-Dark-MCP-{version}"
    contents = {f"{zip_root}/START_HERE.txt": quickstart.read_bytes()}
    with tarfile.open(source) as archive:
        members = archive.getmembers()
        if any(not (member.isfile() or member.isdir()) for member in members):
            raise ValueError("No links or devices in Nexus archives")
        audit_names(member.name for member in members if member.isfile())
        for member in members:
            relative = PurePosixPath(member.name).relative_to(source_root)
            if not member.isfile():
                continue
            name = f"{zip_root}/{relative}"
            if name in contents:
                raise ValueError(f"Duplicate Nexus member: {name}")
            contents[name] = archive.extractfile(member).read()
    audit_names(contents)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None, "Corrupt Nexus ZIP member"
    return destination


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
            "ddda_mcp/standalone.js",
            "ddda_mcp/pinned_research.json",
            "ddda_mcp/native_sdk.cpp",
            "ddda_mcp/native_sdk.hpp",
            "ddda_mcp/example_mod.cpp",
            "ddda_mcp/crash_observer.js",
            "ddda_mcp/crashes.py",
            "ddda_mcp/asset_atlas.py",
            "ddda_mcp/textures.py",
            "ddda_mcp/game_parameters.py",
            "ddda_mcp/encounters.py",
            "ddda_mcp/native_experiments.py",
            "ddda_mcp/mod_isolation.py",
            "ddda_mcp/authoring_tools.py",
            "ddda_mcp/workbench.py",
            "ddda_mcp/assets.py",
            "ddda_mcp/behavior.py",
            "ddda_mcp/sdk.py",
            "ddda_mcp/mods.py",
            "ddda_mcp/suites.py",
            "ddda_mcp/gameplay_data.py",
            "ddda_mcp/gameplay_events.py",
            "ddda_mcp/experiments.py",
            "ddda_mcp/experiment_tools.py",
            "ddda_mcp/sdk_contracts.py",
            "ddda_mcp/parameters.py",
            "ddda_mcp/parameter_tools.py",
            "ddda_mcp/agent.js",
            "ddda_mcp/control.js",
            "ddda_mcp/world.js",
            "ddda_mcp/control.py",
            "ddda_mcp/scenarios.py",
            "ddda_mcp/patches.py",
            "ddda_mcp/ExportMcp.java",
            "ddda_mcp/recipes.py",
            "ddda_mcp/death.py",
            "ddda_mcp/diagnostics.py",
            "ddda_mcp/timeline.py",
            "ddda_mcp/features.py",
            "ddda_mcp/harness.py",
            "ddda_mcp/copied_groups.py",
            "ddda_mcp/tracing.js",
            "ddda_mcp/trace_catalog.py",
            "ddda_mcp/tracing.py",
            "ddda_mcp/memory.py",
            "ddda_mcp/regression.py",
            "ddda_mcp/upstream_contract.json",
        } <= set(names)
        audit_snapshot(archive.read("ddda_mcp/pinned_research.json"))
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
    nexus = make_nexus_archive(
        source,
        root / "docs/NEXUS_README.txt",
        root / "dist" / f"Dragons-Dogma-Dark-MCP-{version}-Experimental.zip",
        version,
    )
    destination = root / "dist/release"
    destination.mkdir(exist_ok=True)
    inputs = {
        wheel.name: wheel,
        source.name: source,
        nexus.name: nexus,
        "INSTALL.md": root / "docs/RELEASES.md",
        "LICENSE": root / "LICENSE",
        "CREDITS.md": root / "CREDITS.md",
        "RELEASE_NOTES.md": root / "docs" / f"RELEASE_NOTES-{version}.md",
        "NEXUS_LISTING.md": root / "docs/NEXUS_LISTING.md",
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
