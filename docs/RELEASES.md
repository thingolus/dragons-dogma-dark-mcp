# Install and release Dragons Dogma Dark MCP

Created by **Thingolus**, MIT licensed. Version 0.11.0. Retain the copyright and license notices when modifying or redistributing this software.

Version 0.11 provides 103 typed tools across parameter editing, native experiments, global asset discovery and texture workflows, a standalone native event SDK, and crash/mod-isolation diagnostics. See [workflows and explicit limits](GENERAL_MODDING.md) and [validation](VALIDATION.md).

## Install a versioned package

For a manual Windows/Nexus installation, download `Dragons-Dogma-Dark-MCP-0.11.0-Experimental.zip`, extract it into a separate writable folder and follow `START_HERE.txt`. It contains the audited source distribution as plain files, without nested archives. [Nexus upload fields and description](NEXUS_LISTING.md) are included for the maintainer.

Download the source archive, wheel and `SHA256SUMS` from the repository release or Actions artifact. Verify the files against `SHA256SUMS` (Windows: `Get-FileHash -Algorithm SHA256`; Linux: `sha256sum --check SHA256SUMS`). Extract the source archive into its own project folder, outside the co-op source checkout. It contains configuration examples, the pinned reuse manifest, scripts and documentation; the wheel also includes the curated research snapshot, so core status/research can run from an empty project directory. Local configuration remains your responsibility.

Install Python 3.13 and uv, then run `uv sync --locked` in the extracted project. On Windows, add `--extra live` only when native sessions are needed. Bundled pinned research and licensed MinHook source support core tools and standalone SDK builds without a co-op checkout. An optional checkout of `thingolus/ddda-local-coop` at commit `e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4` enables full co-op builds/control; that separate repository may have restricted access. An absent source directory selects the bundle, while an existing invalid checkout fails explicitly. The game, research DLLs, saves and Ghidra database are not included. Static tests and CI use synthetic fixtures and require none of them.

Copy `config/local.example.json` to ignored `config/local.json`, set your explicit paths, and run `.venv/Scripts/python.exe -m ddda_mcp --check`. The default profile is read-only. Register with Codex using `scripts/connect_codex.py` or generate another client's stdio configuration using `--print-client-config`. Use `docs/OPERATIONS.md` for development mode and native prerequisites. Never infer loaded-game acceptance from installation or CI success.

## Automated validation and release

Pushes to main, pull requests, manual dispatch and version tags run the same workflow on Windows and Linux. It installs locked dependencies, requires Node for the synthetic native-adapter contract, runs Ruff and pytest (including actual MCP stdio and crash-recovery tests where supported), builds a wheel/source archive, audits their contents and installs the wheel in a separate environment. The installed wheel must pass an isolated stdio handshake, source verification, symbol/source queries and SDK generation with no game or source checkout. Only test XML and audited packages are uploaded; private runtime evidence is excluded. Action versions are pinned to reviewed commit hashes.

`scripts/release_package.py` audits package paths, requires credits/runtime assets, checks tag/version agreement, and stages only this version's packages plus installation/license files, release notes, Nexus listing and checksums. It builds the Nexus ZIP directly from the audited source tarball, refuses links/unsafe paths/nested archives and uses reproducible ZIP metadata. Its explicit distribution allowlist and archive audit reject private directories, local configuration, executables, DLLs, saves and databases. Local release staging refuses leftover assets from another version.

A `vX.Y.Z` tag matching the package version creates an **experimental prerelease draft** on GitHub only after both operating systems pass. The release job alone has repository write permission. It does not publish to PyPI or change repository visibility. To prepare a release, commit the matching version and lockfile, push the version tag, and inspect the draft's checksums and test results. A maintainer may publish the draft after review.

For local checks: `uv run pytest -q`, `uv run ruff check src tests scripts`, `uv run ruff format --check src tests scripts`, `uv build`, then `uv run python scripts/release_package.py`. Local tool/game integration checks remain separate from hosted CI.
