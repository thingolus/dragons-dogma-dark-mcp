"""CI/CLI drift gate. --fetch refreshes origin/main; never changes the checkout or pin."""

import argparse
import json
from pathlib import Path

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.compatibility import Compatibility
from ddda_mcp.config import Config
from ddda_mcp.source import Source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--revision", help="Full committed SHA; defaults to local HEAD, or fetched origin/main"
    )
    parser.add_argument(
        "--fetch", action="store_true", help="Fetch origin/main using existing Git authentication"
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report destination")
    args = parser.parse_args()
    config = Config.load(args.project)
    source = Source(config)
    try:
        if args.fetch:
            source.git("fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main", timeout=60)
        revision = args.revision
        if args.fetch and revision is None:
            revision = (
                source.git("rev-parse", "--verify", "refs/remotes/origin/main^{commit}").decode().strip()
            )
        report = Compatibility(config, source, Artifacts(config)).evaluate(revision)
        code = {"unchanged": 0, "review_required": 2, "incompatible": 3}[report["summary"]["status"]]
    except ToolFailure as exc:
        report = {"summary": {"status": "unavailable", "code": exc.code, "message": str(exc)}}
        code = 1
    if args.output:
        atomic_json(args.output, report)
    print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
