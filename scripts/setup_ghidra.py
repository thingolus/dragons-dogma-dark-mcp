"""Install hash-pinned upstream Ghidra/JDK tools locally; no game or database writes."""

import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

from ddda_mcp.common import atomic_json, contained
from ddda_mcp.config import Config
from ddda_mcp.source import Source

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = Config.load(ROOT)
    source = Source(config)
    source.verify()
    pins = json.loads(source.read("tools.lock.json"))
    for item in pins["downloads"]:
        if item["name"] not in {"ghidra", "jdk21"}:
            continue
        destination = ROOT / ".tools" / item["name"]
        archive = ROOT / ".tools/downloads" / (item["name"] + ".zip")
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            print("Downloading " + item["name"] + " " + item["version"], flush=True)
            with urllib.request.urlopen(item["url"], timeout=60) as inp, archive.open("wb") as out:
                shutil.copyfileobj(inp, out, 1024 * 1024)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise RuntimeError("Hash mismatch: " + str(archive))
        if not (destination / "verified.json").exists():
            print("Extracting " + item["name"], flush=True)
            with zipfile.ZipFile(archive) as zipped:
                for entry in zipped.infolist():
                    contained(destination, destination / entry.filename)
                zipped.extractall(destination)
            atomic_json(destination / "verified.json", item)
    home = next((ROOT / ".tools/ghidra").glob("*/Ghidra/Framework/Utility/lib/Utility.jar")).parents[4]
    java = next((ROOT / ".tools/jdk21").glob("*/bin/java.exe"))
    values = config.settings.model_dump()
    values.update(ghidra_home=str(home), java=str(java), ghidra_project_dir="private/ghidra")
    atomic_json(ROOT / "config/local.json", values)
    print(json.dumps({"ghidra_home": str(home), "java": str(java)}), flush=True)


if __name__ == "__main__":
    main()
