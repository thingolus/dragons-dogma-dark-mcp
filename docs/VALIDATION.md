# Validation and remaining acceptance

Version **0.3.0**, validated on 22 October 2026. Creator: **Thingolus**. This record distinguishes implementation tests, real native observations, and the remaining loaded-game input gate. Native/build/Ghidra observations below were established during v0.2; v0.3 adds client integration, recoverable saves, recipes and benchmark checks without launching DDDA.

## Passed

| Check | Evidence |
| --- | --- |
| Python suite | 82 tests passed on Python 3.13 / Windows; Ruff passes. |
| Real MCP stdio | 27 typed tools with output schemas and four resource routes; actual client calls against the server subprocess. |
| Codex connection | `dragons-dogma-dark` registered through Codex CLI; saved command verified by a real stdio handshake and v0.3 project-status call. Re-running registration preserved the identical entry. Existing chats may need a new session for discovery. |
| Save crash recovery | Actual subprocess termination before replacement, after the first file, and after the last file; both resume and rollback reconstruct the full intended set. Recovery and undo also pass through actual MCP stdio. Interrupted rollback, partial staging, unknown edits, corrupted backups, duplicate paths, terminal-marker cleanup and cross-config launch blocking are covered. Fixtures only. |
| Recipe contracts | Six cataloged recipes, including P1 forward/right and P2 forward. Synthetic tests cover assigned slots, input contents/packet progression, guards, one-shot limits, world changes, cancellation evidence and stop-on-cleanup-failure. No real movement acceptance claimed. |
| Paired tool workflows | Four tasks, five alternating pairs each. Exact source/identity checks pass; latency and response bytes recorded in [benchmarks](BENCHMARKS.md). No AI reasoning or model-token measurement. |
| Pinned research and PE | 42 source inventory entries verified, 134 documents indexed, supported x86 executable identified and disassembled. Dirty co-op source is excluded. |
| Full isolated build | All 122 upstream CTest entries passed through `build_and_test`, including the D3D test; zero failures. |
| Owned native launch | Real Frida bootstrap and offline transport self-test, exact executable/runtime/settings hashes, copied status and performance ABI reads. |
| Observation workflow | Two bounded captures, comparison, cancellation with partial evidence, and post-cancellation status succeeded. A second MCP client was refused ownership. |
| Process lifecycle | Real stdin EOF, supervisor death, and heartbeat expiry stopped the owned game and broker. Observed cleanup after the trigger was about 0.31 s, 0.20 s, and 26.78 s respectively; the heartbeat deadline starts before the test's ready message. |
| Deployment | A temporary developer-input candidate was prepared/applied through MCP and rolled back to byte-identical DLLs, settings, and original ownership manifest. |
| Saves | Player save backup verified. Restore and undo ran on a disposable copy. The actual player save hash was preserved. |
| Ghidra | Hash-pinned Ghidra 12.1.4 and JDK 21 installed locally; supported game database explicitly imported; full analysis completed successfully in 496 seconds; `pawn_delete` exported/decompiled through real MCP stdio, initially returning 301 characters of C. |

Full build job: `08b783d9a1e845d595f3c3bf917c2bdf`. Artifact: `42e9d3d0eb2a407b91f03d3722928db2`, SHA-256 `ea555bfd2768c27e8e9e5253c1151fc71d87a351d3662bf05ec5e0c93522e8a4`. The source commit is `61ed1bf830141b75981babe362cef42579eb98e3` and MinHook commit is `c3fcafdc10146beb5919319d0683e44e3c30d537`.

Native tests used installed runtime SHA-256 `49e784556849fa3ed1cde9fc26d3018dfd72215eebe33efb2fa5af296c5f4ddf` and game SHA-256 `19facc2642f79a09d14ce55eace5f228161f2f8bab60ec67eb3c6196cc6277b8`. The runtime came from the existing research deployment; its compilation source commit is not established by the MCP knowledge pin. The active co-op working tree was not modified.

## Defects found and corrected with real checks

- Startup copied fields report native offline readiness as pending. Version 0.1 incorrectly treated this as a failed guard and disabled observation. The agent now reads the transport guard directly and reports pending native state explicitly. Neutral input still requires native readiness and no faults.
- Heartbeat expiry originally stopped the game but left the broker loop and lease alive. The watchdog now signals broker shutdown, and unexpected Frida detachment also ends the loop. The three real lifecycle checks pass after the fix.
- Running a fullscreen DDDA instance alongside the upstream graphics test caused a D3D device-creation failure. All 122 tests passed with DDDA closed. Full MCP builds now hold the shared game lease to prevent this conflict.
- Direct Java execution needs Ghidra's shipped VM options, including its class loader. The MCP and setup CLI now use the distribution's Windows options; real export passes.
- Trace accounting now includes pretty-printed storage overhead so a small byte budget still preserves readable partial evidence.

## Loaded-game input gate remains unverified

The native `neutral_input` acceptance run did not reach native offline readiness and is **not passed**. A Windows Security prompt for OpenJDK covered the desktop. The user was away and unable to dismiss it; it was left untouched. A bounded title-screen Start request was accepted by the research runtime and released, but it did not establish game progression or native offline readiness. No A/confirm input, New Game selection, save loading, or combat actions were sent.

The implementation retains its readiness restriction. `dismiss_title` is one fixed 250 ms Start request per owned session, limited to no loaded stage/generation/actors; successful submission does not claim UI progression. Loaded-world neutral input, physical-controller behavior, combat, and long-running gameplay stability require later native acceptance in a ready game. These are not inferred from the synthetic agent tests or title-screen observation.

## Evidence and reproducibility

Run the opt-in scripts documented in [operations](OPERATIONS.md). Local reports include `stdio-smoke.json`, `all-build.json`, `native-observation.json`, `native-neutral.json`, `transactions.json`, `lifecycle.json`, and `ghidra.json` under ignored `artifacts/validation`. Native-neutral retains its failed outcome; passing observation and transaction reports do not replace that result. Detailed session, job, deployment, and save receipts remain in `private/runs`.

The automated suite covers source identity, bounds, schemas, paths, deployment interruption/rollback, save undo, cancellation, live readiness refusal, one-shot title input and cleanup, lease exclusion for the full build, artifact pagination, and overflow with partial evidence. The shipped JS agent is tested against a synthetic Frida ABI as well as real observation calls; synthetic tests do not establish gameplay acceptance.

The v0.1 warm-search sample had a median of 3.292 ms over five requests on this machine. Version 0.3 includes [paired direct-command/MCP workflows](BENCHMARKS.md), which measure tool execution and response bytes. No paired AI productivity or token-reduction benchmark has established an overall development speedup. There is no claim of extreme speedup.

## Scope boundaries

The MCP does not attach to existing games, adopt player installations, migrate loader types, accept arbitrary scripts/native calls, or manipulate Steam Cloud. Database import/analysis is an explicit setup CLI action; the MCP export remains read-only. Save restore requires existing files and now provides journaled recovery with per-file atomic replacement. The entire set is not simultaneously atomic; recovery after process death is tested, sudden power loss and hardware failure are not. External game launches and save writers do not honor the MCP lease.

Thingolus's credit and MIT license are retained. Modifications and redistribution are allowed with retention of the copyright and permission notice; MIT does not require a visible in-game credit screen. See [LICENSE](../LICENSE) and the [OSI MIT reference](https://opensource.org/license/mit).
