# Dragons Dogma Dark MCP

A dedicated Model Context Protocol project for faster AI-assisted development of **Dragon's Dogma: Dark Arisen (DDDA / Dragon's Dogma 1)**.

Created by **Thingolus**. Version **0.4.0** implements 30 typed MCP tools and four resource routes over stdio. It reuses the co-op project's pinned research, signatures, runtime ABI, build targets, and deployment conventions.

Verified against the real game: owned startup, copied observations, performance reads, trace comparison/cancellation, competing-client refusal, process cleanup, and deployment rollback. Save restore/undo was tested on a disposable copy, and Ghidra export on a local game database. Loaded-world neutral input remains subject to native offline readiness; it is not counted as passed. See [validation and remaining gates](docs/VALIDATION.md).

| Workflow | Tools |
| --- | --- |
| Project and knowledge | `project_status`, `verify_upstream`, `search_knowledge`, `lookup_symbol`, `read_source` |
| Executable analysis | `inspect_build`, `inspect_binary`, `decompile_symbol`, `investigate_symbol` |
| Owned research sessions | `session_status`, `start_session`, `stop_session`, `runtime_snapshot`, `capture_trace`, `run_scenario`, `list_scenarios` |
| Jobs and evidence | `job_status`, `cancel_job`, `read_artifact`, `compare_runs` |
| Build and deployment | `build_and_test`, `compare_source_revisions`, `compare_builds`, `prepare_deployment`, `apply_deployment`, `rollback_deployment` |
| Saves | `backup_saves`, `restore_saves`, `save_restore_status`, `recover_save_restore` |

The local project is an independent Git repository beside `ddda-local-coop`, under the DDDA workspace. The display name is **Dragons Dogma Dark MCP**; the repository slug is `dragons-dogma-dark-mcp`.

## Install and connect

Use Python 3.13+ and [uv](https://docs.astral.sh/uv/). Keep a local checkout of [ddda-local-coop](https://github.com/thingolus/ddda-local-coop) containing commit `61ed1bf830141b75981babe362cef42579eb98e3`. By default it is a sibling folder, and the game is in the parent folder.

```powershell
uv sync --locked --extra live --python 3.13
.venv/Scripts/python.exe -m ddda_mcp --check
.venv/Scripts/python.exe -m ddda_mcp --print-client-config
```

Insert the generated `mcpServers` entry into your MCP client's configuration. It uses absolute paths and the project's own Python environment. Start the server manually with `scripts/Start-Mcp.ps1`, or use the `ddda-mcp` entry point after installation. `scripts/Install.ps1 -UvPath <path-to-uv.exe>` provides the same installation and preflight check; `-WithoutLive` omits Frida.

For Codex, run `.venv/Scripts/python.exe scripts/connect_codex.py`. It registers `dragons-dogma-dark` using the installed Codex CLI, preserves differing existing entries, and tests the saved command through an actual MCP handshake. A running chat may need a new session to discover the tools. This machine's connection has been registered and verified.

Version 0.3 adds journaled save recovery and three fixed movement recipes. Recovery has been tested across actual test-process termination; the movement recipes have synthetic contract coverage and still await loaded-game acceptance. [Workflow benchmarks](docs/BENCHMARKS.md) compare direct commands with MCP on four tasks, without claiming measured AI reasoning or token savings.

Version 0.4 adds a single-request investigation bundle, committed-source and named-build comparison, and Windows/Linux regression and release automation. Bundles gather research, source excerpts, disassembly, candidate references/callers, and optional Ghidra exports into private artifacts. Build reports flag changed exports, sections, signatures and settings without treating static findings as gameplay proof. See [analysis workflows](docs/ANALYSIS.md) and [versioned installation/releases](docs/RELEASES.md).

The default profile is `read_only`. Copy [config/local.example.json](config/local.example.json) to ignored `config/local.json` to customize paths. Set `profile` to `development` explicitly to enable build jobs, native sessions, deployment, save operations, and decompilation. Relative paths resolve against this project. Starting the MCP server does not start the game.

## Develop

```powershell
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/smoke.py
```

The smoke script uses the real stdio transport and local read-only inputs. Unit tests use temporary fixtures. Native acceptance must be performed separately when no other tool or player owns the game.

Read [operations](docs/OPERATIONS.md), [architecture](docs/ARCHITECTURE.md), and [validation](docs/VALIDATION.md). The original [implementation plan](IMPLEMENTATION_PLAN.md) records delivery gates; [reuse-manifest.json](reuse-manifest.json) pins the 42 inventoried upstream files. Private traces, saves, binaries, credentials, and decompiler databases stay outside version control.

Optional Ghidra setup uses the same hash-pinned distributions as the co-op source:

```powershell
.venv/Scripts/python.exe scripts/setup_ghidra.py
.venv/Scripts/python.exe scripts/prepare_ghidra.py --analyze
.venv/Scripts/python.exe scripts/decompile_smoke.py
```

Database preparation is an explicit CLI operation; ordinary MCP decompilation opens an existing database read-only. Native acceptance scripts are described in operations and should run when DDDA is closed.

## Credits and license

**Thingolus** is the creator and project owner. This project uses the [MIT license](LICENSE): others may use, modify, and redistribute it while retaining the copyright notice naming Thingolus and the license text in copies or substantial portions. It does not require an in-game credit screen. See [CREDITS.md](CREDITS.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
