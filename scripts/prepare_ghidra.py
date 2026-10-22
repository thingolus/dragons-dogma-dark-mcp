"""Explicit one-time database import for the configured supported game, never automatic."""

import argparse
import asyncio
import json
from pathlib import Path

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.binary import Binary
from ddda_mcp.build import Builds, ghidra_command, run_process
from ddda_mcp.common import atomic_json
from ddda_mcp.config import GAME_SHA256, Config
from ddda_mcp.source import Source

ROOT = Path(__file__).resolve().parents[1]


async def main(symbol_name: str, analyze: bool):
    config = Config.load(ROOT)
    config.require_development()
    source = Source(config)
    source.verify()
    symbol = next(item for item in source.symbols() if item["name"] == symbol_name)
    rva = int(symbol["runtime_signature"]["rva"], 16)
    inventory = Binary(config).inventory()
    assert inventory["sha256"] == GAME_SHA256, "Unsupported executable"
    settings = config.settings
    home = (ROOT / settings.ghidra_home).resolve()
    projects = (ROOT / settings.ghidra_project_dir).resolve()
    projects.mkdir(parents=True, exist_ok=True)
    existing = (projects / (settings.ghidra_project_name + ".gpr")).exists()
    if existing and not analyze:
        raise RuntimeError("Database already exists; refusing to overwrite it")
    folder = ROOT / "private/ghidra-import"
    folder.mkdir(parents=True, exist_ok=True)
    java = Builds(config, source, Artifacts(config)).executable(settings.java, "java", "jdk21/**/java.exe")
    args = ghidra_command(home, java, folder) + [
        str(projects),
        settings.ghidra_project_name,
        "-process" if existing else "-import",
        "DDDA.exe" if existing else str(config.game / "DDDA.exe"),
        "-scriptPath",
        str(ROOT / "scripts/ghidra"),
        "-postScript",
        "PrepareMcp.java",
        GAME_SHA256,
        hex(int(inventory["image_base"], 16) + rva),
        symbol_name,
        str(folder / "prepared.json"),
        "-max-cpu",
        "2",
        "-analysisTimeoutPerFile",
        "600",
    ]
    if not analyze:
        args += ["-noanalysis"]
    result = await run_process(args, folder, folder / "import.log", 900)
    atomic_json(folder / "process.json", result)
    if result["exit_code"] != 0 or not (folder / "prepared.json").exists():
        raise RuntimeError(result)
    print(
        json.dumps({"project": str(projects), "symbol": symbol_name, "exit_code": result["exit_code"]}),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="pawn_delete")
    parser.add_argument("--analyze", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.symbol, args.analyze))
