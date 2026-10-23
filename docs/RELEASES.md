# Install and release Dragons Dogma Dark MCP

Created by **Thingolus**, MIT licensed. Version 0.6.0. Retain the copyright and license notices when modifying or redistributing this software.

## Install a versioned package

Download the source archive, wheel and `SHA256SUMS` from this private repository's release or Actions artifact. Verify the files against `SHA256SUMS` (Windows: `Get-FileHash -Algorithm SHA256`; Linux: `sha256sum --check SHA256SUMS`). Extract the source archive into its own project folder, outside the co-op source checkout. It contains configuration examples, the pinned reuse manifest, scripts and documentation; the wheel alone does not provision these project inputs.

Install Python 3.13 and uv, then run `uv sync --locked` in the extracted project. On Windows, add `--extra live` only when native sessions are needed. A local checkout of `thingolus/ddda-local-coop` containing commit `e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4` is required for the research tools; configure `coop_source_root` if it is not a sibling. The game, research DLLs, saves and Ghidra database are not included. Static tests and CI use synthetic fixtures and require none of them.

Copy `config/local.example.json` to ignored `config/local.json`, set your explicit paths, and run `.venv/Scripts/python.exe -m ddda_mcp --check`. The default profile is read-only. Register with Codex using `scripts/connect_codex.py` or generate another client's stdio configuration using `--print-client-config`. Use `docs/OPERATIONS.md` for development mode and native prerequisites. Never infer loaded-game acceptance from installation or CI success.

## Automated validation and release

Pushes to main, pull requests, manual dispatch and version tags run the same workflow on Windows and Linux. It installs locked dependencies, requires Node for the synthetic native-adapter contract, runs Ruff and pytest (including actual MCP stdio and crash-recovery tests where supported), builds a wheel/source archive, audits their contents and installs the wheel in a separate environment. Only test XML and audited packages are uploaded; private runtime evidence is excluded. Action versions are pinned to reviewed commit hashes.

`scripts/release_package.py` audits package paths, requires credits/runtime assets, checks tag/version agreement, and stages only this version's packages plus installation/license files and checksums. Its explicit distribution allowlist and archive audit reject private directories, local configuration, executables, DLLs, saves and databases. Local release staging refuses leftover assets from another version.

A `vX.Y.Z` tag matching the package version creates a **draft** GitHub release only after both operating systems pass. The release job alone has repository write permission. It does not publish to PyPI or change repository visibility. To prepare a release, commit the matching version and lockfile, push the version tag, and inspect the draft's checksums and test results. A maintainer may publish the draft after review.

For local checks: `uv run pytest -q`, `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv build`, then `uv run python scripts/release_package.py`. Local tool/game integration checks remain separate from hosted CI.
