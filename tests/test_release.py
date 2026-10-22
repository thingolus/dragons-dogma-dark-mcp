import importlib.util
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
