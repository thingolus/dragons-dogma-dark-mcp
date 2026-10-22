# Validation and remaining acceptance

Validated on 22 October 2026 for version 0.1.0, by Thingolus's development workflow. The checks below describe what was actually run. They do not imply full native gameplay acceptance.

## Passed

| Check | Result |
| --- | --- |
| Python suite | 48 tests passed on Python 3.13 / Windows. Temporary fixture tests ran outside the restricted sandbox because its temporary directories were inaccessible. |
| Ruff | All checks passed for `src`, `tests`, and `scripts`. |
| Real stdio client | SDK client connected to the actual server subprocess, listed 24 tools with output schemas, read resources, and called project, knowledge, source, symbol, and PE tools. |
| Immutable source reuse | All 42 manifest entries verified against `61ed1bf830141b75981babe362cef42579eb98e3`; dirty co-op changes were excluded. |
| Real knowledge index | 134 pinned research/documentation files indexed and searched. |
| Real executable | SHA-256 `19facc2642f79a09d14ce55eace5f228161f2f8bab60ec67eb3c6196cc6277b8`; x86, image base `0x400000`; bounded disassembly completed without launching or attaching. |
| Real isolated C++ build | MCP `build_and_test` job configured MSVC 19.44 / Win32, built core targets from the pinned Git archive and MinHook commit, and passed all three selected CTest entries with zero failures. |
| Configuration | Example config validated; `--check` passed against the real source/game files. |
| Packaging | Locked dependency resolution, source distribution, and wheel built. Wheel contains the JS agent, Java exporter, Thingolus author metadata, MIT license, and third-party notices. Distribution inventory excludes local private state and caches. |

The isolated build used MinHook commit `c3fcafdc10146beb5919319d0683e44e3c30d537`. CTest entries were `core_and_hook_tests`, `settings_validation`, and `controller_session_policy`. Its completed MCP job ID was `793e31e044a7476da24866def179f728`; evidence artifact ID `009508b6b2b4487a847dce2bf2bcafc0`, SHA-256 `0a2de3d908fadc2704346b303c4c53ecc6eef2c197d15dad85eb659c94ab4666`. It completed in approximately 25 seconds outside the sandbox. The initial sandboxed attempt stalled in compiler execution and was cancelled at the smoke script's ten-minute deadline; it is not counted as a passing build.

## Automated coverage

Tests exercise immutable Git reads despite dirty working files, fingerprint failures, symbol merging, literal FTS searches, concurrent indexing, PE bounds, malformed DLLs, path/archive escapes, real SDK schemas and stdio transport, profile refusals, deployment ownership and rollback, interrupted deployment recovery, save undo backups, job cancellation before/after start, subprocess timeout cleanup, artifact bounds and complete pagination of long strings, and compatible-evidence comparisons.

Native protocol tests use a synthetic session and a Node-hosted Frida API fixture. They verify that loading/reading the shipped agent produces no input, ABI size/version mismatches fail, large integer counters retain precision, neutral input is explicit, stale broker replies disable the session, and failed/cancelled captures retain partial evidence with cleanup. These tests validate adapter contracts; they do not run Frida inside DDDA.

## Measurements

The final read-only stdio smoke measured six searches on this machine with an existing index. The first request took 8.268 ms. The following five had a median of 3.292 ms and a range of 3.033–3.375 ms, returning about 6 KB per response. This is a small local latency sample. It is not an AI productivity benchmark. No end-to-end speedup or token reduction claim has been established.

Machine-local reports are ignored by Git: `artifacts/validation/stdio-smoke.json` and `artifacts/validation/core-build.json`. Full build logs and durable receipts remain in `private/runs`.

## Remaining acceptance

- An owned native game session, real Frida bootstrap/offline transport check, status/performance reads, watchdog termination, and neutral-input cleanup inside the supported game.
- Deployment/rollback and save backup/restore on a dedicated research installation with disposable saves. Fixture tests passed, but the actual user's installation and saves were not changed.
- Ghidra execution against a configured database and installed Java/Ghidra toolchain.
- Full upstream build/test group; this run selected the three core CTest entries only.
- Physical-controller behavior, combat, menus, pawn behavior, and long-running stability. The current recipes only observe or supply neutral synthetic input.
- Controlled before/after measurements for actual AI development workflows.

Another co-op task was using the game during implementation. No game was launched, attached, stopped, redeployed, or supplied input by this implementation task. Native acceptance should run when that owner has finished, using an explicitly configured development profile and research installation.

## Design limitations

Version 0.1 uses a dedicated typed broker instead of the legacy single-slot mailbox. It does not attach to existing games, import a new Ghidra database, migrate loader types, adopt player deployments, install missing save fixtures, coordinate Steam Cloud, or provide atomic recovery of a multi-file save restore. Stopping an owned session terminates it without saving. These boundaries are described in [operations](OPERATIONS.md).

The MIT license permits modification and redistribution while requiring retention of the copyright/license notice. It supplies the requested attribution through the **Thingolus** copyright notice; it does not require a visible in-game credits screen. See the [license text](../LICENSE) and [OSI MIT reference](https://opensource.org/license/mit).
