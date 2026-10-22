"""Command line entry point. Use --check for diagnostics; default is MCP stdio."""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import Config
from .server import create_server


def main():
    parser = argparse.ArgumentParser(description="Dragons Dogma Dark MCP — by Thingolus (MIT)")
    parser.add_argument(
        "--project", type=Path, default=Path.cwd(), help="Project directory containing reuse-manifest.json"
    )
    parser.add_argument("--config", type=Path, help="Explicit local JSON configuration")
    parser.add_argument("--check", action="store_true", help="Print read-only setup diagnostics and exit")
    parser.add_argument(
        "--print-client-config", action="store_true", help="Print generic MCP stdio client configuration"
    )
    parser.add_argument(
        "--version", action="version", version=f"Dragons Dogma Dark MCP {__version__} — Thingolus"
    )
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    root = args.project.resolve()
    if args.print_client_config:
        arguments = ["-m", "ddda_mcp", "--project", str(root)]
        if args.config:
            arguments.extend(["--config", str(args.config.resolve())])
        print(
            json.dumps(
                {"mcpServers": {"dragons-dogma-dark-mcp": {"command": sys.executable, "args": arguments}}},
                indent=2,
            )
        )
        return
    try:
        config = Config.load(root, args.config)
        server, app = create_server(config, args.config)
        if args.check:
            import asyncio

            async def check():
                try:
                    status = await app.invoke("project_status", app.project_status)
                    build = await app.invoke("inspect_build", app.binary.inventory)
                    print(
                        json.dumps(
                            {"project": status.structured_content, "build": build.structured_content},
                            indent=2,
                        )
                    )
                    if not status.structured_content["success"]:
                        return 1
                    compatibility = status.structured_content["data"].get("upstream_compatibility", {})
                    return {"unchanged": 0, "review_required": 2, "incompatible": 3}.get(
                        compatibility.get("status"), 1
                    )
                finally:
                    await app.close()

            raise SystemExit(asyncio.run(check()))
        server.run(transport="stdio")
    except (OSError, ValueError) as exc:
        print(f"DDDA MCP setup error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
