# Dragons Dogma Dark MCP

A dedicated Model Context Protocol project for faster AI-assisted development of **Dragon's Dogma: Dark Arisen (DDDA / Dragon's Dogma 1)**.

Start with [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). It maps the existing co-op project's research host, runtime diagnostics, symbol knowledge, build pipeline, and regression checks into a focused MCP implementation.

**Status: planning baseline, 22 October 2026.** The MCP server is not implemented yet. This repository contains the implementation plan, a pinned reuse inventory, and configuration guidance. No game runtime, deployment, controller input, or saves are changed by this planning project.

| Item | Location |
| --- | --- |
| Implementation plan and delivery gates | [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |
| Pinned source paths and Git object identities | [reuse-manifest.json](reuse-manifest.json) |
| Proposed local configuration | [config/local.example.json](config/local.example.json) |
| Instructions for subsequent implementation | [AGENTS.md](AGENTS.md) |
| Existing co-op source | [thingolus/ddda-local-coop](https://github.com/thingolus/ddda-local-coop) |

The local project is an independent Git repository beside `ddda-local-coop`, under the DDDA workspace. The display name is **Dragons Dogma Dark MCP**; the repository slug is `dragons-dogma-dark-mcp`.

The first useful release will expose project knowledge, executable identity, and bounded static analysis. Live diagnostics and reproducible experiment orchestration follow in separate stages. The initial implementation should adapt the existing tools instead of building another game runtime.

`config/local.example.json` documents the proposed configuration contract. It is not a runnable server configuration yet. Machine-specific paths, private traces, saves, and game binaries stay outside version control.
