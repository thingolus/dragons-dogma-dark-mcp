"""Decode a copied 520-word ring or saved MCP death_diagnostic JSON; never opens the game."""

import argparse
import json
from pathlib import Path

from ddda_mcp.common import read_json
from ddda_mcp.death import decode_death


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    document = read_json(args.capture, 128 * 1024)
    words = document if isinstance(document, list) else document.get("data", document).get("words")
    result = decode_death(words)
    result["evidence_class"] = "offline_replay"
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
