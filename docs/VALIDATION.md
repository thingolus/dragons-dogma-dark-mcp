# Validation and remaining acceptance

Version **0.7.0**, validated on 23 October 2026. Creator: **Thingolus**. This record distinguishes synthetic implementation tests, actual native observations and remaining gameplay coverage. Earlier milestone sections below retain their historical evidence scope.

## Five live-development additions

The Windows suite passes **217 tests**, including real stdio checkpoint registration and investigation persistence across subprocess restarts, cancellation/cleanup, stale evidence, copied ABI decoding, repeated bisection and immutable build/deploy/restore orchestration. Ruff, the real-project stdio smoke, future-workflow smoke, archive audit and isolated wheel import pass. Three native investigation notes persisted across a fresh stdio server and all evidence hashes rechecked successfully. The server exposes **50 typed tools** and four resource routes. The nine-adapter catalog and two reviewed trace signatures are linked to the unchanged `e6a64c2` research baseline. See [workflows and limits](LIVE_DEVELOPMENT.md).

Fresh native acceptance used owned sessions and the existing inn save at stage 220:

- Checkpoint registration binds a hash-checked backup to an advancing native trace. Loaded-world neutral input completed with eight samples and verified release; its harness artifact is `087535223d5049f1b68e7d3a6705eb40`, SHA-256 `106db6a1d7abf1d39a47f9c00933d98cbdf74dc741c38f80a6f15c617b467605`.
- All six new copied groups returned valid native data: pawn resources, vocation, actions, inventory/menu lifecycle, shared life and target HUD. Hidden/unavailable caches retain their availability flags. The death-refusal ring was valid and empty; the performance collector was inactive. Neither result proves combat behavior.
- The stamina observer captured 200 native events, no omissions, and verified hook removal. Artifact `17a4428e44df43779e4f721a3ea80fb3`, SHA-256 `784f58241a68ebd8e0ea5e3fbbb31031f94cd7a396fac6cb77d2f0e835b0d7b7`. The health observer installed and removed successfully but captured zero events; combat damage acceptance is unverified.
- A real Ghidra export for the stamina function passed: artifact `a9eef0f1e2d94254b0a3d74e80b7db16`, SHA-256 `881c3a81019dce44b0f2879621b8df9d766cec9f122db08d11f48bd5ad617f63`. This validates the export separately from the live observer; it is not proof of a complete call graph.
- Historical source `61ed1bf830141b75981babe362cef42579eb98e3` built from its immutable archive and passed all **122 CTests**. The first native attempt caught an unsupported newer `recovery.endless_lives` setting. Candidate generation now uses selected-source defaults and supported overrides, recording omissions. Subsequent menu timeouts remained inconclusive and restored originals.
- Campaign `fce0500b9d0a44b9a55ab3a43f10d388` then completed a real loaded-world idle trial with eight advancing samples, no faults, verified process exit, deployment rollback, save restore and byte-identical shared-life state. Evidence `8f0dc1ffe1f24352942aece6a68b83c9`, SHA-256 `5118eb3246e89b6a7d5f3993127a97d5c2560cc5620b255d01607b61f54286a4`. The acceptance campaign was deliberately ended after that trial. No full native bisection boundary is claimed.

The physical controller mask was 1 and player assignments were -1; physical-controller movement and combat remain unverified. Menu navigation was performed through observed native UI. No Windows security prompt needed action. Runtime identity was captured by DLL hash; the pre-existing installation's source identity is unknown, while the historical trial has an exact source commit. The original installation, saves and shared-life reserve were restored; dirty sibling source was not used or modified. Private evidence remains excluded from Git and packages.


## Diagnostic framework, timelines and future feature research

The v0.6 Windows suite passes 183 tests. New coverage includes strict copied schemas, exact counters, pointer redaction, immutable input handling, original diagnostic replay, decoder/rule mismatch reporting, changed-evidence refusal, timeline pagination, clock/session/build/evidence separation, unknown identities, ambiguous equal timestamps, unobserved actors, world changes, ring overlap and saturated duplicates, failed cleanup/cancellation evidence, source scan budgets, dirty-source exclusion and cited dependency/test candidates. All seven new tools are exercised through an actual MCP stdio subprocess using synthetic fixtures in the normal test suite.

The real-project `scripts/future_workflows_smoke.py` also passes: 39 discovered tools, diagnostic replay, timeline query/replay and feature investigations against the exact pinned `e6a64c2` source. It scans 902 eligible files / 5,793,684 bytes without source-budget omissions. Shared inventory (terms inventory/pickup) finds 18 symbol candidates, 43 source candidates and 11 test candidates; pawn commands finds 25/314/38; shared-life revival finds 18/57/17. These are lexical matches, not established feature feasibility or test coverage. Result caps and omitted result counts are preserved in the artifacts.

The native performance/death capture persistence paths now use the reviewed registry. Their new integration is covered synthetically, including absence of controller input calls; no fresh game launch or native acceptance was performed. Existing native reader code remains unchanged. No co-op source, installed game payload, save or shared-life reserve was changed. The baseline and Thingolus/MIT credits are preserved. See [workflow contracts and extension guide](FUTURE_WORKFLOWS.md).

## Refusal diagnostics and compatibility gates

Version 0.5 adds a native copied-value reader for the 2080-byte/520-word death-refusal ring, offline replay and conservative upstream drift detection. All 142 tests pass on Windows, including short-circuit null predicates, wrapped/saturated ring sequences, exact 64-bit values, nonfinite HP, malformed layouts/masks, redacted replay artifacts, disabled profiles and the actual shipped JavaScript under a synthetic Frida contract. Synthetic native reads verify word-count versus byte-count, missing exports, refused calls and zero controller-input calls.

Compatibility regression tests use independent committed synthetic repositories and mutations: changed ABI source, signatures, calling convention, missing exports, game fingerprint, unsafe defaults, missing contract inputs, immutable revision validation, dirty-file exclusion and bounded reports. The shipped reviewed contract matches the real `e6a64c2` baseline; automatic preflight reports `unchanged`. An explicit fetch/check command is available without changing the checkout or reviewed pin. The Windows/Linux CI runs these regressions without private upstream credentials.

The new diagnostic's loaded-game capture has **not** been verified. Offline replay is not a claim that a synthetic record occurred in the game or that the unresolved Game Over is fixed. No co-op source, game file, deployment, save or shared-life reserve was changed in this milestone. See [diagnostic semantics](DIAGNOSTICS.md) and [compatibility scope](UPSTREAM_COMPATIBILITY.md).

## Current co-op baseline refresh

The user's synchronization request promoted the completed co-op source checkpoint to `main` at `e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4`; the remote has no `master` branch. MCP defaults, example/local configuration and all 42 reuse-manifest identities now use that commit. The source checkpoint includes narrative research, original artwork and synthetic test fixtures; raw local acceptance receipts and packaged binaries remain local.

All 225 named signatures and three input thunks match the supported executable. All 219 previous records are unchanged; the nine additions cover NPC damage attribution, restricted-container hits and pickup rendering. The existing status (132 bytes/version 2), performance (2448 bytes/version 1) and four-pad input ABI is unchanged. The developer-only down-refusal diagnostic was not exposed in v0.4.1; v0.5 adds the reader described above.

Fresh checks passed: 110 Python tests, Ruff lint/format, the real 30-tool stdio handshake, all nine new symbol lookups, EXP-089 research retrieval and a complete `npc_damage_source_context` investigation. The index now contains 139 documents. An isolated Debug build of the exact committed source passed all 125 CTest entries, including D3D. Build job `766eebd19d8e4ce6923b2207adc8e2ee`, artifact `c9bbabf10fa6445e89727498545ba1b6`, artifact SHA-256 `a30912f3941964a808c39d4a88a364c2cc4deb3fb0a7e64b078b46acb2531e47`. Co-op packaging tests also passed 144 cases and five synthetic observer suites.

No game launch, deployment or save mutation was performed during this refresh. The installation's shared-life reserve is outside MCP `.sav` backup/restore; see [operations](OPERATIONS.md#saves). The loaded-game MCP input gate remains unverified. Earlier results below retain their original source/build pins rather than inheriting native acceptance from this update.

## Passed

| Check | Evidence |
| --- | --- |
| Python suite | 217 tests passed on Python 3.13 / Windows; Ruff lint and format checks pass. |
| Real MCP stdio | 50 typed tools with output schemas and four resource routes; actual client calls against the server subprocess. |
| Codex connection | `dragons-dogma-dark` registered through Codex CLI; saved command verified by a real stdio handshake and v0.4 project-status call. Re-running registration preserved the identical entry. Existing chats may need a new session for discovery. |
| Investigation bundle | Real `pawn_delete` bundle collected five research excerpts, source passages, disassembly, absolute references, bounded candidate caller scan and Ghidra export. Zero caller candidates in this bounded scan is not proof of no callers. |
| Source comparison | On the v0.4 baseline, real pinned commit versus its parent reported 71 changed files, paginated in groups up to 50, with ABI/settings review hints. Tests verify dirty checkout exclusion, pagination and runtime-signature differences. |
| Build comparison | Real installed research payload versus a private copied fixture reports the changed developer-input setting. Installed files are unchanged. Synthetic PE fixtures additionally verify removed exports, section changes, malformed inputs and hash-tampering rejection. |
| Release packaging | Wheel and source archive built and audited locally and on hosted Windows/Linux; checksums, installation guide and Thingolus license/credits included. Separate wheel installation and isolated startup pass on all three environments. |
| Hosted regression | [GitHub Actions run 39789706792](https://github.com/thingolus/dragons-dogma-dark-mcp/actions/runs/39789706792), commit `0a004d7`: Windows 110 passed; Linux 109 passed, one Windows-specific test skipped. Both package audits and clean wheel installations passed. Tagged releases repeat these checks before draft creation. |
| Save crash recovery | Actual subprocess termination before replacement, after the first file, and after the last file; both resume and rollback reconstruct the full intended set. Recovery and undo also pass through actual MCP stdio. Interrupted rollback, partial staging, unknown edits, corrupted backups, duplicate paths, terminal-marker cleanup and cross-config launch blocking are covered. Fixtures only. |
| Recipe contracts | Six cataloged recipes, including P1 forward/right and P2 forward. Synthetic tests cover assigned slots, input contents/packet progression, guards, one-shot limits, world changes, cancellation evidence and stop-on-cleanup-failure. No real movement acceptance claimed. |
| Paired tool workflows | Four tasks, five alternating pairs each. Exact source/identity checks pass; latency and response bytes recorded in [benchmarks](BENCHMARKS.md). No AI reasoning or model-token measurement. |
| Pinned research and PE | 42 source inventory entries verified, 139 documents indexed, supported x86 executable identified and disassembled. Dirty co-op source is excluded. |
| Full isolated build | Current baseline: all 125 upstream CTest entries passed through `build_and_test`, including D3D. The earlier 122-test result below belongs to the previous pin. |
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

## Historical v0.2 loaded-game input gate (superseded by v0.7 neutral acceptance)

The native `neutral_input` acceptance run did not reach native offline readiness and is **not passed**. A Windows Security prompt for OpenJDK covered the desktop. The user was away and unable to dismiss it; it was left untouched. A bounded title-screen Start request was accepted by the research runtime and released, but it did not establish game progression or native offline readiness. No A/confirm input, New Game selection, save loading, or combat actions were sent.

The implementation retains its readiness restriction. `dismiss_title` is one fixed 250 ms Start request per owned session, limited to no loaded stage/generation/actors; successful submission does not claim UI progression. Loaded-world neutral input, physical-controller behavior, combat, and long-running gameplay stability require later native acceptance in a ready game. These are not inferred from the synthetic agent tests or title-screen observation.

## Evidence and reproducibility

Run the opt-in scripts documented in [operations](OPERATIONS.md). Local reports include `stdio-smoke.json`, `analysis-smoke.json`, `codex-connection.json`, `all-build.json`, `native-observation.json`, `native-neutral.json`, `transactions.json`, `lifecycle.json`, and `ghidra.json` under ignored `artifacts/validation`. Native-neutral retains its failed outcome; passing observation and transaction reports do not replace that result. Detailed session, job, deployment, and save receipts remain in `private/runs`.

The automated suite covers source identity, bounds, schemas, paths, deployment interruption/rollback, save undo, cancellation, live readiness refusal, one-shot title input and cleanup, lease exclusion for the full build, artifact pagination, and overflow with partial evidence. The shipped JS agent is tested against a synthetic Frida ABI as well as real observation calls; synthetic tests do not establish gameplay acceptance.

The v0.1 warm-search sample had a median of 3.292 ms over five requests on this machine. Version 0.3 includes [paired direct-command/MCP workflows](BENCHMARKS.md), which measure tool execution and response bytes. No paired AI productivity or token-reduction benchmark has established an overall development speedup. There is no claim of extreme speedup.

## Scope boundaries

The MCP does not attach to existing games, adopt player installations, migrate loader types, accept arbitrary scripts/native calls, or manipulate Steam Cloud. Database import/analysis is an explicit setup CLI action; the MCP export remains read-only. Save restore requires existing files and now provides journaled recovery with per-file atomic replacement. The entire set is not simultaneously atomic; recovery after process death is tested, sudden power loss and hardware failure are not. External game launches and save writers do not honor the MCP lease.

Thingolus's credit and MIT license are retained. Modifications and redistribution are allowed with retention of the copyright and permission notice; MIT does not require a visible in-game credit screen. See [LICENSE](../LICENSE) and the [OSI MIT reference](https://opensource.org/license/mit).
