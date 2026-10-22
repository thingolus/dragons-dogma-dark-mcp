import hashlib
import json
import os
import struct
import subprocess

import pytest

from ddda_mcp.common import atomic_json
from ddda_mcp.config import Config, Settings


def git(root, *args):
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.check_output(["git", "-C", str(root), *args], env=env).decode().strip()


@pytest.fixture(scope="session")
def upstream(tmp_path_factory):
    root = tmp_path_factory.mktemp("source")
    documents = {
        "docs/STATUS.md": "# Current status\n\nPawn ownership cancellation is verified only in static tests.\n"
        * 12,
        "docs/BACKLOG.md": "# Backlog\n\nInvestigate menu ownership and input lifetime.\n",
        "research/EXP-001.md": "# Evidence\n\nPawn ownership has synthetic observations, not physical controller evidence.\n",
        "research/symbols.csv": "symbol,build_sha256,rva,calling_convention,evidence,status\npawn_movement_consume,abc,0x1000,stdcall,EXP-001,live-observed\n",
        "include/coop/supported_build.hpp": 'const char* sha256="abc";\n{"pawn_movement_consume",0x1000,{0x55,0x8b,0xec,0xc3}}\n',
        "src/example.cpp": "// source test\nint answer() { return 42; }\n",
    }
    for path, content in documents.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-m", "Synthetic fixture")
    commit = git(root, "rev-parse", "HEAD")
    files = [{"path": p, "git_blob_sha1": git(root, "rev-parse", f"{commit}:{p}")} for p in documents]
    manifest = {"upstream": {"commit": commit}, "components": [{"files": files}]}
    return root, commit, manifest


@pytest.fixture
def config(tmp_path, upstream):
    source, commit, manifest = upstream
    root = tmp_path / "project"
    game = tmp_path / "game"
    root.mkdir()
    game.mkdir()
    atomic_json(root / "reuse-manifest.json", manifest)
    return Config(
        root, Settings(game_root=str(game), coop_source_root=str(source), coop_source_commit=commit)
    )


@pytest.fixture
def development(config):
    config.settings.profile = "development"
    return config


def make_pe(path, machine=0x14C):
    data = bytearray(1024)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, machine, 1, 0, 0, 0, 224, 0x102)
    opt = 0x98
    struct.pack_into("<H", data, opt, 0x10B)
    struct.pack_into("<I", data, opt + 16, 0x1000)
    struct.pack_into("<I", data, opt + 28, 0x400000)
    struct.pack_into("<II", data, opt + 32, 0x1000, 0x200)
    struct.pack_into("<II", data, opt + 56, 0x2000, 0x200)
    struct.pack_into("<H", data, opt + 68, 3)
    struct.pack_into("<I", data, opt + 92, 16)
    section = opt + 224
    data[section : section + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", data, section + 8, 512, 0x1000, 512, 512)
    struct.pack_into("<I", data, section + 36, 0x60000020)
    data[512:516] = b"\x55\x8b\xec\xc3"
    data[528:548] = b"Thingolus DDDA test!\0"
    struct.pack_into("<I", data, 600, 0x401000)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def pe(config):
    make_pe(config.game / "DDDA.exe")
    return config


@pytest.fixture
def candidate(development, monkeypatch):
    import ddda_mcp.deployment as deployment
    from ddda_mcp.config import GAME_SHA256

    root = development.root / "candidate"
    root.mkdir()
    files = {
        "dinput8.dll": b"fake-loader",
        "ddcoop_runtime.dll": b"fake-runtime",
        "ddcoop.ini": b"[coop]\nonline_mode=0\ndeveloper_input=1\n",
    }
    for name, data in files.items():
        (root / name).write_bytes(data)
    manifest = {
        "game_sha256": GAME_SHA256,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    (root / "candidate.json").write_text(json.dumps(manifest))
    development.settings.deployment_candidates = {"fixture": str(root)}
    monkeypatch.setattr(deployment.Binary, "inventory", lambda self: {"sha256": GAME_SHA256})
    monkeypatch.setattr(deployment, "require_closed", lambda: None)
    # Transaction tests use non-executable fixture bytes. Real PE validation is
    # exercised separately, without deploying any native binary.
    monkeypatch.setattr(deployment, "verify_payload", lambda root, files: None)
    return development, root
