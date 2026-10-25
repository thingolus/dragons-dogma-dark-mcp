DRAGONS DOGMA DARK MCP 0.11.1 - EXPERIMENTAL
Created by Thingolus. MIT license; retain the included notices.

A local mod-development toolkit for Dragon's Dogma: Dark Arisen.
Connect an MCP-compatible AI client to 103 typed research, asset-editing,
SDK and diagnostic tools. This download is a Python source package.

MANUAL INSTALLATION

1. Install Python 3.13+ and uv. Use Python 3.13 for the tested setup.
   Python: https://www.python.org/downloads/
   uv: https://docs.astral.sh/uv/getting-started/installation/
2. Extract this folder somewhere writable, for example C:\ModTools\DDDA-MCP.
   Keep it separate from the game folder. Do not install it through Vortex.
3. Open PowerShell in the extracted folder and run:

   uv sync --locked --no-dev --python 3.13
   Copy-Item config/local.example.json config/local.json

4. Edit config/local.json. Set game_root to your DDDA installation using
   forward slashes in JSON, for example:

   "game_root": "C:/Program Files (x86)/Steam/steamapps/common/DDDA"

   Leave profile as "read_only" for the initial setup. Core tools use the
   bundled research when coop_source_root does not exist. The optional
   co-op integration requires a separate reviewed checkout.
5. Run:

   .venv/Scripts/python.exe -m ddda_mcp --check
   .venv/Scripts/python.exe -m ddda_mcp --print-client-config

6. Add the generated mcpServers entry to your client's MCP configuration,
   then reconnect the client. A client that supports local MCP over stdio
   is required. Codex users with its CLI installed can instead run:

   .venv/Scripts/python.exe scripts/connect_codex.py

7. Start with project_status, verify_upstream and lookup_symbol.

DEVELOPMENT AND LIVE FEATURES

Read docs/OPERATIONS.md and docs/GENERAL_MODDING.md before changing profile
to "development". Enable the optional Frida dependency with:

   uv sync --locked --no-dev --extra live --python 3.13

Live tools require Windows, the exact supported Steam DDDA executable,
an offline owned session and the documented runtime/bridge prerequisites.
The standalone C++ SDK requires Visual Studio C++ build tools and CMake.
Full co-op control additionally requires its optional source checkout and
verified developer runtime. Standalone observation has no input provider.

The package contains code, documentation, licensed research and examples.
It contains no game assets, saves, compiled DLLs or decompiler databases.
Dependency installation requires an internet connection.

EXPERIMENTAL LIMITS

Supported formats and fields are deliberately bounded. Long-session native
stability, some combat/revival/loot outcomes and real crashing-mod isolation
remain unverified. Read docs/VALIDATION.md for evidence and exact limits.
Back up your own files before editing or enabling development operations.
Keep private traces, saves and dumps out of public reports.

UPDATING OR REMOVING

Stop the MCP client/server before updating. Keep your existing local
configuration and private evidence separate from a fresh extracted version.
If development tools applied profiles or deployments, restore those using
the documented recovery/rollback workflow before removing the toolkit.
For an unused read-only installation, remove its client entry and folder.

SOURCE AND SUPPORT

https://github.com/thingolus/dragons-dogma-dark-mcp
https://github.com/thingolus/dragons-dogma-dark-mcp/issues

Include version, Windows/Python versions, tool name, expected result and a
minimal reproduction. Do not upload game files, saves, dumps or credentials.
