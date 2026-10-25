# Contributing

Created by Thingolus. Contributions are licensed under the project's MIT license; preserve existing copyright and third-party notices.

Use Python 3.13+, Git, Node.js and uv. Run `uv sync --locked`, `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, and `uv run pytest -q`. Tests use synthetic fixtures and need no game installation. Native acceptance is separate and must identify the exact game/runtime/bridge build and cleanup receipts.

Read `AGENTS.md` and the relevant workflow document before changing adapters. Keep MCP operations typed and bounded. New formats need corruption/extent tests and lossless round trips. New native access needs reviewed signatures, callback ownership, copied values, offline checks and cleanup on every exit. Do not add arbitrary eval, raw memory write or native-call tools.

Do not submit game archives, textures, saves, dumps, native binaries, private traces, local configuration, credentials or decompiler databases. Use small synthetic fixtures. Describe the problem, resulting behavior, validation, and remaining limits in pull requests. Tests alone must never be described as native gameplay acceptance.

`scripts/package_research.py` reproduces curated licensed text from immutable Git objects. Review its diff and license inventory; it must never package a working tree or private evidence. `uv build` followed by `uv run python scripts/release_package.py` verifies the distribution and stages checksummed release assets.
