import json
import subprocess

import pytest
from conftest import git

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.config import Config
from ddda_mcp.features import Features
from ddda_mcp.knowledge import Knowledge
from ddda_mcp.source import Source


@pytest.fixture
def feature_project(config, tmp_path):
    root = tmp_path / "feature-source"
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(config.source), str(root)], check=True)
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    files = {
        "include/coop/inventory.hpp": "// shared inventory\nstruct SharedInventory {};\n",
        "src/inventory.cpp": '#include "coop/inventory.hpp"\n// shared inventory implementation\n',
        "tests/inventory_tests.cpp": '#include "coop/inventory.hpp"\n// shared inventory boundary test\n',
        "src/consumer.cpp": '#include "coop/inventory.hpp"\n// No feature term outside include\n',
    }
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(root, "add", ".")
    git(root, "commit", "-m", "Feature fixtures")
    commit = git(root, "rev-parse", "HEAD")
    manifest = json.loads((config.root / "reuse-manifest.json").read_text())
    manifest["upstream"]["commit"] = commit
    atomic_json(config.root / "reuse-manifest.json", manifest)
    config.settings.coop_source_root = str(root)
    config.settings.coop_source_commit = commit
    return Config(config.root, config.settings)


def service(config):
    source = Source(config)
    return Features(source, Knowledge(source), Artifacts(config))


def test_feature_reports_pinned_sources_dependencies_and_candidate_tests(feature_project):
    feature = service(feature_project)
    result = feature.investigate("shared inventory", ["shared inventory"])
    doc = feature.artifacts.get(result["artifact_id"])["data"]
    assert doc["test_candidates"] == ["tests/inventory_tests.cpp"]
    assert any(
        edge["from"] == "src/consumer.cpp" and edge["resolved_candidates"] == ["include/coop/inventory.hpp"]
        for edge in doc["dependency_candidates"]
    )
    for candidate in doc["source_candidates"]:
        assert candidate["hits"][0]["source"]["commit"] == feature_project.settings.coop_source_commit
        assert candidate["hits"][0]["source"]["git_blob_sha1"]
    assert doc["summary"]["native_acceptance"] == "unverified"
    assert any("No matching known symbol" in gap for gap in doc["evidence_gaps"])


def test_feature_ignores_dirty_source_and_research_remains_cited(feature_project):
    (feature_project.source / "src/inventory.cpp").write_text("// SECRET_DIRTY_SENTINEL")
    feature = service(feature_project)
    result = feature.investigate("pawn ownership")
    doc = feature.artifacts.get(result["artifact_id"])["data"]
    assert doc["symbols"][0]["name"] == "pawn_movement_consume"
    assert doc["research"] and all(
        row["source"]["commit"] == feature_project.settings.coop_source_commit for row in doc["research"]
    )
    assert "SECRET_DIRTY_SENTINEL" not in json.dumps(doc)
    found = feature.investigate("shared inventory")
    assert "src/inventory.cpp" in found["leading_source_paths"]


def test_scan_budget_is_explicit(feature_project, monkeypatch):
    monkeypatch.setattr("ddda_mcp.features.MAX_FILES", 1)
    result = service(feature_project).investigate("shared inventory")
    assert result["summary"]["scanned_files"] == 1
    assert result["summary"]["omitted_files"] > 0
    assert any("budget" in gap for gap in result["evidence_gaps"])


@pytest.mark.parametrize(
    "feature,terms",
    [
        ("", None),
        ("x" * 257, None),
        ("and the for", None),
        ("x", []),
        ("x", ["x"] * 9),
        ("x", ["x; rm"]),
        ("x", ["a" * 49]),
    ],
)
def test_feature_input_bounds(config, feature, terms):
    with pytest.raises(ToolFailure):
        service(config).investigate(feature, terms)


def test_no_matches_are_gaps_not_feasibility_claims(config):
    result = service(config).investigate("unknown_feature_9876")
    assert result["summary"]["source_candidates"] == 0
    assert result["summary"]["symbol_candidates"] == 0
    assert len(result["evidence_gaps"]) >= 5
