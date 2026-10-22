# Dragons Dogma Dark MCP

A dedicated Model Context Protocol project for faster AI-assisted development of **Dragon's Dogma: Dark Arisen (DDDA / Dragon's Dogma 1)**.

Created by **Thingolus**. Version **0.1.0** implements 24 typed MCP tools and four resource routes over stdio. It reuses the co-op project's pinned research, signatures, runtime ABI, build targets, and deployment conventions.

The read-only development workflow has been verified against the real source repository and supported executable. Live sessions, deployment, save operations, and Ghidra export have implementation and automated coverage where practical, but require separate native acceptance. See [validation and remaining gates](docs/VALIDATION.md).

| Workflow | Tools |
| --- | --- |
| Project and knowledge | `project_status`, `verify_upstream`, `search_knowledge`, `lookup_symbol`, `read_source` |
| Executable analysis | `inspect_build`, `inspect_binary`, `decompile_symbol` |
| Owned research sessions | `session_status`, `start_session`, `stop_session`, `runtime_snapshot`, `capture_trace`, `run_scenario` |
| Jobs and evidence | `job_status`, `cancel_job`, `read_artifact`, `compare_runs` |
| Build and deployment | `build_and_test`, `prepare_deployment`, `apply_deployment`, `rollback_deployment` |
| Saves | `backup_saves`, `restore_saves` |

The local project is an independent Git repository beside `ddda-local-coop`, under the DDDA workspace. The display name is **Dragons Dogma Dark MCP**; the repository slug is `dragons-dogma-dark-mcp`.

## Install and connect

Use Python 3.13+ and [uv](https://docs.astral.sh/uv/). Keep a local checkout of [ddda-local-coop](https://github.com/thingolus/ddda-local-coop) containing commit `61ed1bf830141b75981babe362cef42579eb98e3`. By default it is a sibling folder, and the game is in the parent folder.

```powershell
uv sync --locked --extra live --python 3.13
.venv/Scripts/python.exe -m ddda_mcp --check
.venv/Scripts/python.exe -m ddda_mcp --print-client-config
```

Insert the generated `mcpServers` entry into your MCP client's configuration. It uses absolute paths and the project's own Python environment. Start the server manually with `scripts/Start-Mcp.ps1`, or use the `ddda-mcp` entry point after installation. `scripts/Install.ps1 -UvPath <path-to-uv.exe>` provides the same installation and preflight check; `-WithoutLive` omits Frida.

The default profile is `read_only`. Copy [config/local.example.json](config/local.example.json) to ignored `config/local.json` to customize paths. Set `profile` to `development` explicitly to enable build jobs, native sessions, deployment, save operations, and decompilation. Relative paths resolve against this project. Starting the MCP server does not start the game.

## Develop

```powershell
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/smoke.py
```

The smoke script uses the real stdio transport and local read-only inputs. Unit tests use temporary fixtures. Native acceptance must be performed separately when no other tool or player owns the game.

Read [operations](docs/OPERATIONS.md), [architecture](docs/ARCHITECTURE.md), and [validation](docs/VALIDATION.md). The original [implementation plan](IMPLEMENTATION_PLAN.md) records delivery gates; [reuse-manifest.json](reuse-manifest.json) pins the 42 inventoried upstream files. Private traces, saves, binaries, credentials, and decompiler databases stay outside version control.

## Credits and license

**Thingolus** is the creator and project owner. This project uses the [MIT license](LICENSE): others may use, modify, and redistribute it while retaining the copyright notice naming Thingolus and the license text in copies or substantial portions. It does not require an in-game credit screen. See [CREDITS.md](CREDITS.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
