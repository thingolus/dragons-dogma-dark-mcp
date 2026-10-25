import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "release_package", Path(__file__).parents[1] / "scripts/release_package.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.py",
        "/absolute.py",
        "pkg/private/save.json",
        "pkg/game.dll",
        "pkg/DDDA.sav",
        "pkg/config/local.json",
        "pkg/.env.token",
        "C:/config.json",
        "pkg/.venv/file.py",
        "pkg/credentials",
        "pkg/database.gpr",
    ],
)
def test_release_audit_rejects_private_or_unsafe_members(name):
    with pytest.raises(ValueError, match="Unexpected"):
        release.audit_names([name])


def test_release_audit_accepts_runtime_and_license_assets():
    release.audit_names(
        [
            "ddda_mcp/agent.js",
            "ddda_mcp/ExportMcp.java",
            "pkg/uv.lock",
            "pkg/LICENSE",
            "pkg/docs/RELEASES.md",
            "pkg.dist-info/METADATA",
        ]
    )


def source_archive(tmp_path, name, content=b"source", *, link=False):
    path = tmp_path / "source.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = "../private"
            archive.addfile(member)
        else:
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    quickstart = tmp_path / "quickstart.txt"
    quickstart.write_text("Manual install in a separate folder.")
    return path, quickstart


def test_nexus_archive_contains_plain_source_and_quickstart_reproducibly(tmp_path):
    source, quickstart = source_archive(tmp_path, "dragons_dogma_dark_mcp-0.11.0/src/example.py")
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    for destination in (first, second):
        release.make_nexus_archive(source, quickstart, destination, "0.11.0")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {
            "Dragons-Dogma-Dark-MCP-0.11.0/START_HERE.txt",
            "Dragons-Dogma-Dark-MCP-0.11.0/src/example.py",
        }
        assert archive.read("Dragons-Dogma-Dark-MCP-0.11.0/src/example.py") == b"source"


@pytest.mark.parametrize("name", ["private/save.json", "payload.zip", "game.dll", "../escape.py"])
def test_nexus_archive_rejects_private_nested_and_unsafe_files(tmp_path, name):
    source, quickstart = source_archive(tmp_path, f"dragons_dogma_dark_mcp-0.11.0/{name}")
    with pytest.raises(ValueError, match="Unexpected"):
        release.make_nexus_archive(source, quickstart, tmp_path / "out.zip", "0.11.0")
    assert not (tmp_path / "out.zip").exists()


def test_nexus_archive_rejects_links_and_wrong_version_root(tmp_path):
    source, quickstart = source_archive(tmp_path, "dragons_dogma_dark_mcp-0.11.0/link", link=True)
    with pytest.raises(ValueError, match="No links"):
        release.make_nexus_archive(source, quickstart, tmp_path / "out.zip", "0.11.0")
    source, quickstart = source_archive(tmp_path, "dragons_dogma_dark_mcp-0.10.0/README.md")
    with pytest.raises(ValueError):
        release.make_nexus_archive(source, quickstart, tmp_path / "out.zip", "0.11.0")
