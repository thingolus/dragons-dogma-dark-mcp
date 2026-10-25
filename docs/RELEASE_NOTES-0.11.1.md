# Dragons Dogma Dark MCP 0.11.1 — Experimental

Created by **Thingolus**. A local development toolkit for Dragon's Dogma: Dark Arisen with **103 typed MCP tools**.

This release makes core research and standalone SDK generation available without access to the optional co-op source repository. Bundled research and MinHook sources retain their licenses and immutable source identities.

Version 0.11.1 corrects cross-platform release validation for synthetic checkpoints and Windows temporary-directory aliases. Native Windows ownership guards remain enforced.

## Included workflows

- Search pinned research, inspect signatures and compare builds.
- Inspect and edit supported ARC/GMD, item, skill, enemy, encounter and loot data within the documented format and field limits.
- Build an ARC asset index and export/import supported TEX/DDS textures with PNG previews.
- Generate a C++ SDK and build the standalone native event provider.
- Run bounded native experiments with the optional reviewed co-op runtime, and inspect copied observations and private crash reports.
- Compose journaled mod profiles and compare recorded experiments.

## Downloads

- **Nexus/manual Windows setup:** `Dragons-Dogma-Dark-MCP-0.11.1-Experimental.zip`. Extract into a separate writable folder and follow `START_HERE.txt`. This ZIP contains plain source files and no nested archives.
- **Python installation:** `dragons_dogma_dark_mcp-0.11.1-py3-none-any.whl`.
- **Source distribution:** `dragons_dogma_dark_mcp-0.11.1.tar.gz`.
- `SHA256SUMS` verifies all release assets. `NEXUS_LISTING.md` contains the prepared Nexus upload fields and description.

Use Python 3.13 and uv for the tested setup. An MCP client with local stdio support is required. Native features additionally require Windows, the exact supported Steam game build and the prerequisites in [operations](https://github.com/thingolus/dragons-dogma-dark-mcp/blob/v0.11.1/docs/OPERATIONS.md). The default profile is read-only.

## Validation and limits

Release CI validates Windows and Linux, audits the wheel/source/Nexus ZIP and exercises a separately installed wheel without a game or co-op checkout. Linux CI covers the Python/offline package; it does not establish Linux or Proton gameplay support. Native observations and synthetic tests are documented separately in [validation](https://github.com/thingolus/dragons-dogma-dark-mcp/blob/v0.11.1/docs/VALIDATION.md).

This is an experimental developer release. Long-session native stability, some combat/revival/loot outcomes and a real crashing-mod isolation campaign remain unverified. Unsupported formats, arbitrary quest editing and autonomous target navigation remain unavailable. Standalone observation has no input provider. No game assets, saves, native binaries or private traces are included.

Report reproducible issues with the version, affected tool and expected/actual behavior. Keep private dumps, saves and game files out of public issues.

MIT licensed. Preserve Thingolus's copyright and all included third-party notices.
