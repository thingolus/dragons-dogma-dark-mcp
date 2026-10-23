# Dragons Dogma Dark MCP

A dedicated Model Context Protocol project for faster AI-assisted development of **Dragon's Dogma: Dark Arisen (DDDA / Dragon's Dogma 1)**.

Created by **Thingolus**. Version **0.9.0** implements 77 typed MCP tools and four resource routes over stdio. It reuses the co-op project's pinned research, signatures, runtime ABI, build targets, and deployment conventions.

The gameplay development tools now include expiring controller ownership, callback-only world inspection, reusable scenarios, failure diagnosis and isolated patch verification. Native checks have verified assignment and movement for both players while a physical controller remained connected, input release, party resources/inventories and deployment/save restoration. Combat damage, learned dodge, enemy presence and quest-state coverage remain separate gates. See [gameplay workflows](docs/GAMEPLAY_DEVELOPMENT.md) and [validation](docs/VALIDATION.md).

The scenario follow-up adds full-stick running, camera directions, forward jumping, optional solo P1 control with native pawn AI, and retained observations for interrupted actions. Native checks passed healing and solo ownership/movement, including P1 control while the main pawn is down, and registered a reload-verified quarry approach fixture. The health observer recorded real ogre HP subtraction; its strict scenario result remains inconclusive after a generation change. Damage, revival and loot outcome acceptance remain open; see the [scenario evidence and retry procedure](docs/NATIVE_SCENARIOS.md).

Version 0.9 adds behavior comparisons with analyzed Ghidra references, a reusable C++ SDK and standalone observer, private ARC/GMD editing, fixture/profile gameplay matrices, and journaled mod profiles with conflict detection and merging. See [general modding workflows](docs/MODDING_WORKBENCH.md) for supported formats, examples and recovery.

| Workflow | Tools |
| --- | --- |
| Behavior research | `compare_behavior`, `capture_behavior_experiment` |
| Reusable SDK | `ddda_sdk_catalog`, `generate_ddda_sdk`, `build_research_bridge`, `inspect_standalone_world` |
| Asset editing | `list_asset_archives`, `open_asset_archive`, `inspect_asset`, `edit_asset_text`, `repack_asset_archive` |
| Mod profiles | `import_mod`, `register_mod`, `compose_mod_profile`, `mod_profile` |
| Fixture suites | `register_gameplay_fixture`, `list_gameplay_fixtures`, `create_gameplay_suite`, `advance_gameplay_suite`, `gameplay_suite_status` |
| Gameplay development | `gameplay_catalog`, `control_gameplay`, `gameplay_action`, `inspect_world`, `diagnose_scenario`, `create_source_patch`, `create_patch_verification` |
| Project and knowledge | `project_status`, `verify_upstream`, `search_knowledge`, `lookup_symbol`, `read_source` |
| Executable analysis | `inspect_build`, `inspect_binary`, `decompile_symbol`, `investigate_symbol` |
| Owned research sessions | `session_status`, `start_session`, `stop_session`, `runtime_snapshot`, `capture_trace`, `run_scenario`, `list_scenarios` |
| Jobs and evidence | `job_status`, `cancel_job`, `read_artifact`, `compare_runs` |
| Build and deployment | `build_and_test`, `compare_source_revisions`, `compare_builds`, `prepare_deployment`, `apply_deployment`, `rollback_deployment` |
| Refusal diagnostics and compatibility | `decode_death_diagnostic`, `check_upstream_compatibility`, `runtime_snapshot(group="death_refusals")` |
| Reusable diagnostics and timelines | `list_diagnostic_adapters`, `decode_diagnostic`, `replay_diagnostic`, `build_event_timeline`, `query_event_timeline`, `replay_event_timeline` |
| Future feature research | `investigate_feature` |
| Checkpoint gameplay | `create_gameplay_checkpoint`, `launch_gameplay_checkpoint`, `run_gameplay_harness` |
| Reviewed function tracing | `list_function_traces`, `trace_function` |
| Investigation memory | `record_investigation_note`, `read_investigation_note`, `search_investigations` |
| Repeated regression trials | `create_regression_campaign`, `advance_regression_campaign`, `regression_campaign_status` |
| Saves | `backup_saves`, `restore_saves`, `save_restore_status`, `recover_save_restore` |

The local project is an independent Git repository beside `ddda-local-coop`, under the DDDA workspace. The display name is **Dragons Dogma Dark MCP**; the repository slug is `dragons-dogma-dark-mcp`.

## Install and connect

Use Python 3.13+ and [uv](https://docs.astral.sh/uv/). Keep a local checkout of [ddda-local-coop](https://github.com/thingolus/ddda-local-coop) containing commit `e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4`. By default it is a sibling folder, and the game is in the parent folder.

```powershell
uv sync --locked --extra live --python 3.13
.venv/Scripts/python.exe -m ddda_mcp --check
.venv/Scripts/python.exe -m ddda_mcp --print-client-config
```

Insert the generated `mcpServers` entry into your MCP client's configuration. It uses absolute paths and the project's own Python environment. Start the server manually with `scripts/Start-Mcp.ps1`, or use the `ddda-mcp` entry point after installation. `scripts/Install.ps1 -UvPath <path-to-uv.exe>` provides the same installation and preflight check; `-WithoutLive` omits Frida.

For Codex, run `.venv/Scripts/python.exe scripts/connect_codex.py`. It registers `dragons-dogma-dark` using the installed Codex CLI, preserves differing existing entries, and tests the saved command through an actual MCP handshake. A running chat may need a new session to discover the tools. This machine's connection has been registered and verified.

Version 0.3 adds journaled save recovery and three fixed movement recipes. Recovery has been tested across actual test-process termination; the movement recipes have synthetic contract coverage and still await loaded-game acceptance. [Workflow benchmarks](docs/BENCHMARKS.md) compare direct commands with MCP on four tasks, without claiming measured AI reasoning or token savings.

Version 0.4 adds a single-request investigation bundle, committed-source and named-build comparison, and Windows/Linux regression and release automation. Bundles gather research, source excerpts, disassembly, candidate references/callers, and optional Ghidra exports into private artifacts. Build reports flag changed exports, sections, signatures and settings without treating static findings as gameplay proof. See [analysis workflows](docs/ANALYSIS.md) and [versioned installation/releases](docs/RELEASES.md).

Version 0.4.1 pins the committed co-op 1.8 candidate at `e6a64c2`, including its new research and nine additional signatures (225 symbols plus three input thunks). The existing status, performance and input ABI remains unchanged. Shared-life state is separate from `.sav` backup/restore; see [operations](docs/OPERATIONS.md#saves).

Version 0.5 adds [death/refusal diagnostics and offline replay](docs/DIAGNOSTICS.md), plus [automated upstream compatibility checks](docs/UPSTREAM_COMPATIBILITY.md). Preflight detects committed source drift without automatically changing the reviewed baseline.

Version 0.6 adds [reviewed diagnostic adapters, event timelines, regression replay and feature investigations](docs/FUTURE_WORKFLOWS.md). Three copied-value schemas share validation and redacted replay storage. Timelines correlate compatible captured evidence and report rule findings while keeping different clocks separate. Feature reports gather pinned research, symbol/source/test candidates, include dependencies and missing evidence. All seven new tools work offline; future live fields still require native research and acceptance.

Version 0.7 adds [checkpoint gameplay, broader diagnostics, reviewed function tracing, persistent investigation memory and repeated regression campaigns](docs/LIVE_DEVELOPMENT.md). The harness requires advancing native callbacks; trials build immutable commits, deploy temporarily and restore originals. Native menu loading remains an observed client action. The diagnostic catalog now contains nine schemas.

The default profile is `read_only`. Copy [config/local.example.json](config/local.example.json) to ignored `config/local.json` to customize paths. Set `profile` to `development` explicitly to enable build jobs, native sessions, deployment, save operations, and decompilation. Relative paths resolve against this project. Starting the MCP server does not start the game.

## Develop

```powershell
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/smoke.py
```

The smoke script uses the real stdio transport and local read-only inputs. Unit tests use temporary fixtures. Native acceptance must be performed separately when no other tool or player owns the game.

Read [operations](docs/OPERATIONS.md), [architecture](docs/ARCHITECTURE.md), and [validation](docs/VALIDATION.md). The original [implementation plan](IMPLEMENTATION_PLAN.md) records delivery gates; [reuse-manifest.json](reuse-manifest.json) pins the 50 inventoried upstream files. Private traces, saves, binaries, credentials, and decompiler databases stay outside version control.

Optional Ghidra setup uses the same hash-pinned distributions as the co-op source:

```powershell
.venv/Scripts/python.exe scripts/setup_ghidra.py
.venv/Scripts/python.exe scripts/prepare_ghidra.py --analyze
.venv/Scripts/python.exe scripts/decompile_smoke.py
```

Database preparation is an explicit CLI operation; ordinary MCP decompilation opens an existing database read-only. Native acceptance scripts are described in operations and should run when DDDA is closed.

## Credits and license

**Thingolus** is the creator and project owner. This project uses the [MIT license](LICENSE): others may use, modify, and redistribute it while retaining the copyright notice naming Thingolus and the license text in copies or substantial portions. It does not require an in-game credit screen. See [CREDITS.md](CREDITS.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
