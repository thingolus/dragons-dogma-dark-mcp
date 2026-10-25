# Nexus Mods upload information — 0.11.1

Prepared for Thingolus, 25 October 2026. The description below is ready to paste into the Nexus editor. Upload the ZIP as a separate toolkit page for Dragon's Dogma: Dark Arisen.

## Page and file fields

| Field | Value |
| --- | --- |
| Game | Dragon's Dogma: Dark Arisen |
| Mod name | Dragons Dogma Dark MCP - Modding Toolkit |
| Author | Thingolus |
| Version | 0.11.1 |
| Category | Modders Resources and Tutorials |
| Release status | Experimental developer release |
| File category | Main Files |
| File display name | Dragons Dogma Dark MCP 0.11.1 - Experimental |
| File to upload | `Dragons-Dogma-Dark-MCP-0.11.1-Experimental.zip` |
| Installation | Manual download; disable Download with Mod Manager if the uploader offers it |
| Language | English |
| Adult content | No |
| Source | https://github.com/thingolus/dragons-dogma-dark-mcp |
| Release | https://github.com/thingolus/dragons-dogma-dark-mcp/releases/tag/v0.11.1 |
| Issue tracker | https://github.com/thingolus/dragons-dogma-dark-mcp/issues |

### Short description

A local MCP toolkit for Dragon's Dogma: Dark Arisen mod development. Connect an AI client to 103 tools for research, supported asset and parameter editing, C++ SDK generation, and diagnostics. Experimental developer release by Thingolus.

### Main file description

Complete 0.11.1 experimental toolkit: Python source, locked dependencies, bundled licensed research, SDK source, documentation and setup scripts. Requires Python 3.13+, uv and an MCP client with local stdio support. Extract into a separate writable folder and read START_HERE.txt. Manual installation; no game files or compiled DLLs included.

## Full description — paste into the mod page

### Dragons Dogma Dark MCP

Dragons Dogma Dark MCP gives an MCP-compatible AI client a set of tools for developing mods for Dragon's Dogma: Dark Arisen. It runs locally and brings research, supported asset editing, native SDK generation and diagnostics into one workflow.

Created by **Thingolus**. This is an **experimental developer toolkit** for mod authors, researchers and people building their own DDDA tools. It is a Python package that connects to an AI client through MCP, the Model Context Protocol. It does not include an AI model or a graphical mod editor.

### What it can do

- Search bundled research and inspect known symbols and signatures.
- Inspect and edit supported item, skill, enemy, encounter and loot parameters, with named fields and explicit format limits.
- Inspect ARC archives, edit supported GMD text and repack private asset copies.
- Build an asset index and export/import supported TEX/DDS textures, with PNG previews.
- Generate a reusable C++ SDK and build a standalone native event provider.
- Compare recorded experiments, compose mod profiles and inspect private diagnostic reports.
- With the optional reviewed co-op runtime, run bounded native experiments and inspect copied gameplay observations.

Version 0.11.1 exposes **103 typed MCP tools**. Core research and standalone SDK generation use bundled licensed source, so they do not require access to the optional co-op repository.

### Requirements

For the toolkit:

- Python 3.13 or newer. Python 3.13 is the tested release setup.
- uv for dependency installation.
- An MCP-compatible client that can launch a local stdio server. Codex integration is included; other clients can use the generated configuration.
- Internet access to install dependencies and whatever access your chosen AI client requires.

For game assets and live workflows:

- Your own PC copy of Dragon's Dogma: Dark Arisen.
- Native features target Windows and the exact supported Steam executable. The toolkit checks its fingerprint before admitting native operations. Linux package tests do not establish Linux or Proton gameplay support.
- Native sessions require the optional Frida dependency, offline operation and the documented bridge/runtime setup.
- Native SDK builds require Visual Studio C++ build tools and CMake. Ghidra analysis is optional and has its own setup procedure.
- Full co-op builds and gameplay control require the separate reviewed co-op checkout and developer runtime. These are optional integrations and are not included in this download.

### Installation

1. Download the main ZIP manually and extract it into a writable folder such as `C:\ModTools\DDDA-MCP`. Keep the toolkit separate from the game installation.
2. Install Python and uv, then open PowerShell in the extracted folder.
3. Run `uv sync --locked --no-dev --python 3.13`.
4. Copy `config/local.example.json` to `config/local.json`. Set `game_root` to your DDDA installation. Use forward slashes in JSON paths. Leave `profile` as `read_only` for the initial setup.
5. Run `.venv/Scripts/python.exe -m ddda_mcp --check`.
6. Run `.venv/Scripts/python.exe -m ddda_mcp --print-client-config` and add the generated entry to your MCP client. Codex users with its CLI installed can use `.venv/Scripts/python.exe scripts/connect_codex.py`.
7. Reconnect your client and start with `project_status`, `verify_upstream` and `lookup_symbol`.

`START_HERE.txt` contains the complete setup steps. Read `docs/OPERATIONS.md` before enabling the development profile or live features. Development operations can edit files, build code, launch owned game sessions and restore saves within configured locations. Keep backups of your own files.

### Example requests

- “Find the research and signatures related to pawn movement.”
- “Inspect this supported item parameter file and show the named fields.”
- “Compare these two parameter versions and list the changed values.”
- “Generate the standalone C++ SDK and show me its example mod.”

Tool availability depends on your configured profile, files and installed prerequisites.

### Current limits

This release supports specific reviewed formats and fields. It is not a complete editor for every game system. Standalone observation has no gameplay input provider. Arbitrary quest editing and automatic target navigation are unavailable.

Local tests, isolated installation checks and selected real-game observations are documented in the repository. Long-session native stability, some combat/revival/loot outcomes and a real crashing-mod isolation campaign still need further testing. Synthetic replay results are kept separate from native game evidence.

The download contains code, documentation, licensed research and examples. It contains no game assets, saves, compiled runtime DLLs, minidumps or decompiler databases.

### Updating and removal

Stop the MCP client/server before updating. Extract the new version into a fresh folder and retain your local configuration and private evidence separately. If development tools applied profiles or deployments, restore them through the documented rollback/recovery workflow before removing the toolkit. An unused read-only installation can be removed by deleting its MCP client entry and folder.

### Source, support and credits

Source and documentation: https://github.com/thingolus/dragons-dogma-dark-mcp

Report issues: https://github.com/thingolus/dragons-dogma-dark-mcp/issues

When reporting a problem, include the toolkit version, Windows/Python versions, tool name, expected result and a minimal reproduction. Keep saves, game archives, private dumps and credentials out of public reports.

Created by **Thingolus**. AI tools were used in development and to prepare this description. Original project code is MIT licensed; copied research and third-party sources retain their included notices. See `LICENSE`, `CREDITS.md` and `THIRD_PARTY_NOTICES.md`.

## Other uploader fields

### Requirements entries

No Nexus-hosted mod is required for the core toolkit. Add these external requirements:

| Requirement | Link | Notes |
| --- | --- | --- |
| Python | https://www.python.org/downloads/ | 3.13+; 3.13 is tested |
| uv | https://docs.astral.sh/uv/getting-started/installation/ | Dependency installation |
| MCP client | The user's preferred compatible client | Must launch local MCP servers over stdio |
| Visual Studio Build Tools | https://visualstudio.microsoft.com/downloads/ | Optional, native C++ SDK builds only |
| CMake | https://cmake.org/download/ | Optional, native C++ SDK builds only |

The game is required for inspecting its local assets or running native workflows. The co-op integration is optional; do not list the co-op gameplay mod as a mandatory core requirement.

### Permissions and credits

- **Other users' assets:** this package includes licensed third-party source; see `THIRD_PARTY_NOTICES.md`.
- **Upload, modification, conversion and reuse:** allowed under the shipped MIT/BSD licenses with the required copyright, license and attribution notices retained.
- **Commercial reuse / use in monetized mods:** the shipped MIT/BSD licenses permit commercial use subject to their notices. These permissions cover shipped source, not game content.
- **Credit:** Thingolus; MinHook authors and other dependencies listed in the notices.
- **Donation Points / donations:** choose your own participation settings; licensing does not establish Nexus program eligibility.

### Tags

Choose the available developer-tool/resource tags that accurately describe the package. Use **AI-Generated Content** for the generated implementation and **AI Media** when using the description prepared here. Do not substitute **AI Assisted** merely because the project has human direction; Nexus reserves that category for limited AI involvement with the specified supporting evidence.

### Images

Use real screenshots: the connected tool list, a successful research query, and a supported parameter diff or texture preview. Crop private paths, account information and unrelated windows. A title image can say “Dragons Dogma Dark MCP / Modding Toolkit / 0.11.1 Experimental / by Thingolus.” Do not label screenshots of synthetic tests as native gameplay results.

### Changelog

First public experimental release of Dragons Dogma Dark MCP. Includes 103 typed tools, bundled research for installation without the optional co-op checkout, supported parameter and texture editing, a C++ SDK/native event provider, experiment workflows and private diagnostics. Includes a manual-install ZIP, checksums, setup guide and documented feature limits.

## Packaging and policy references

Upload the single `Experimental.zip` as the main file. The Python wheel and source tarball are alternative GitHub downloads; do not put either inside the Nexus ZIP. Keep private assets and generated binaries out of the upload.

Nexus recommends ZIP/7z and rejects nested archives: https://help.nexusmods.com/article/117-why-has-my-mod-been-quarantined

Category list: https://www.nexusmods.com/dragonsdogma/mods/categories

Submission and AI-tagging requirements: https://help.nexusmods.com/article/28-file-submission-guidelines
