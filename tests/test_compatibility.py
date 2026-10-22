import asyncio
import copy
import json
import subprocess
from pathlib import Path

import pytest
from conftest import git
from mcp import Client

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.compatibility import (
    REQUIRED_EXPORTS,
    WATCHED,
    Compatibility,
    capture_contract,
    compare_contracts,
)
from ddda_mcp.server import create_server
from ddda_mcp.source import Source


@pytest.fixture
def upstream_contract(config):
    clone = config.root / "compat-source"
    subprocess.run(["git", "clone", "--quiet", str(config.source), str(clone)], check=True)
    config.source = clone
    git(clone, "config", "user.name", "Fixture")
    git(clone, "config", "user.email", "fixture@example.invalid")
    for path in WATCHED:
        target = clone / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("// synthetic contract fixture\n")
    (clone / "config").mkdir(exist_ok=True)
    (clone / "config/ddcoop.ini").write_text("[coop]\nonline_mode=0\ndeveloper_input=0\n")
    (clone / "src/runtime.cpp").write_text(
        "\n".join(
            f'extern "C" __declspec(dllexport) int __cdecl {name}() {{ return 1; }}'
            for name in REQUIRED_EXPORTS
            if name != "OfflineState"
        )
    )
    (clone / "src/network_guard.cpp").write_text(
        'extern "C" __declspec(dllexport) int __cdecl OfflineState() { return 2; }'
    )
    header = clone / "include/coop/supported_build.hpp"
    header.write_text(
        header.read_text().replace('const char* sha256="abc"', 'const char sha256[]="' + "a" * 64 + '"')
    )
    git(clone, "add", ".")
    git(clone, "commit", "-m", "Synthetic contract")
    pin = git(clone, "rev-parse", "HEAD")
    config.settings.coop_source_commit = pin
    atomic_json(
        config.root / "reuse-manifest.json", {"upstream": {"commit": pin}, "components": [{"files": []}]}
    )
    source = Source(config)
    return config, source, capture_contract(source)


def test_changed_source_defaults_and_signatures_need_review(upstream_contract):
    config, source, contract = upstream_contract
    service = Compatibility(config, source, Artifacts(config), contract)
    assert service.evaluate()["summary"]["status"] == "unchanged"
    (config.source / "include/coop/runtime_status.hpp").write_text("// changed layout\n")
    # Dirty work is never part of immutable compatibility assessment.
    assert service.evaluate()["summary"]["status"] == "unchanged"
    git(config.source, "add", ".")
    git(config.source, "commit", "-m", "Layout changed")
    report = service.evaluate()
    assert report["summary"]["status"] == "review_required"
    assert report["differences"]["watched_sources"]["items"][0]["name"] == "include/coop/runtime_status.hpp"
    (config.source / "config/ddcoop.ini").write_text("[coop]\nonline_mode=1\ndeveloper_input=0\n")
    git(config.source, "add", ".")
    git(config.source, "commit", "-m", "Unsafe default")
    report = service.evaluate()
    assert report["summary"]["status"] == "incompatible"
    assert any("online_mode" in b for b in report["summary"]["blockers"])
    assert source.commit == contract["source_commit"]  # No repinning.


@pytest.mark.parametrize("change", ["signature", "missing_export", "calling_convention", "game", "developer"])
def test_breaking_contract_changes_block(upstream_contract, change):
    _, _, contract = upstream_contract
    after = copy.deepcopy(contract)
    if change == "signature":
        next(iter(after["signatures"].values()))["rva"] = "0x9999"
    elif change == "missing_export":
        del after["exports"]["CoopGetStatus"]
    elif change == "calling_convention":
        after["exports"]["CoopSetTestPads"] = "int__stdcall()"
    elif change == "game":
        after["game_sha256"] = "b" * 64
    else:
        after["settings"]["coop.developer_input"] = "1"
    assert compare_contracts(contract, after)["summary"]["status"] == "incompatible"


def test_additions_and_large_diffs_remain_reviewable(upstream_contract):
    _, _, contract = upstream_contract
    after = copy.deepcopy(contract)
    after["signatures"].update({f"new_{i}": {"rva": "0x1000", "sha256": "b" * 64} for i in range(105)})
    report = compare_contracts(contract, after)
    assert report["summary"]["status"] == "review_required"
    assert report["differences"]["signatures"]["total"] == 105
    assert report["differences"]["signatures"]["truncated"]


def test_missing_contract_inputs_and_unreviewed_pin_fail_closed(upstream_contract):
    config, source, contract = upstream_contract
    wrong = copy.deepcopy(contract)
    wrong["source_commit"] = "a" * 40
    assert Compatibility(config, source, Artifacts(config), wrong).status()["status"] == "unavailable"
    (config.source / "include/coop/performance.hpp").unlink()
    git(config.source, "add", ".")
    git(config.source, "commit", "-m", "Missing ABI input")
    service = Compatibility(config, source, Artifacts(config), contract)
    with pytest.raises(ToolFailure, match="Missing required"):
        service.evaluate()
    with pytest.raises(ToolFailure, match="immutable"):
        service.evaluate("--help")


def test_mcp_status_checks_upstream_and_explicit_check_saves_report(upstream_contract):
    config, source, contract = upstream_contract

    async def run():
        server, app = create_server(config)
        app.compatibility = Compatibility(config, source, app.artifacts, contract)
        async with Client(server) as client:
            status = await client.call_tool("project_status", {})
            assert status.structured_content["data"]["upstream_compatibility"]["status"] == "unchanged"
            result = await client.call_tool("check_upstream_compatibility", {})
            assert not result.is_error
            artifact = app.artifacts.get(result.structured_content["data"]["artifact_id"])
            assert artifact["provenance"]["dirty_inputs_used"] is False

    asyncio.run(run())


def test_shipped_contract_and_pin_are_consistent():
    import ddda_mcp
    from ddda_mcp.config import BASELINE, GAME_SHA256

    contract = json.loads(Path(ddda_mcp.__file__).with_name("upstream_contract.json").read_text())
    assert contract["source_commit"] == BASELINE and contract["game_sha256"] == GAME_SHA256
    assert set(WATCHED) == contract["watched_sources"].keys()
    assert set(REQUIRED_EXPORTS) <= contract["exports"].keys()
    assert compare_contracts(contract, contract)["summary"]["status"] == "unchanged"
