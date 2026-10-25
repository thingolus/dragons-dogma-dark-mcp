# General mod development workflows

Version 0.11.1. Created by **Thingolus**, MIT licensed. The server has 103 typed tools. Private artifacts carry hashes and evidence labels; none of the workflows below distribute game data.

## Find, edit and compare parameters

The named parameter editor covers XFS/PRPZ, SKL, reviewed LOT encounters and IST loot tables alongside the existing ITL2 item editor. See [format coverage, limits and examples](GAME_PARAMETERS.md). Expected-value checks, lossless patching and field conflict detection make small balance changes reviewable. Private ARC repacking and journaled mod profiles provide the deployment and rollback path.

## Run a native experiment

Create a plan with `create_experiment_plan`, then call `run_native_experiment(plan_id)` in an owned offline co-op session with a hash-verified developer-provider build. `require`, `action`, and `wait` steps read callback-copied observations while the plan is executing. Goals measure movement, HP decrease, HP increase, zero-to-positive HP, or item-quantity gain. Reports include observations, action acknowledgments, measured results, and cleanup receipts. The resulting native recording can be queried and replayed with the same offline tools.

```json
{
  "label": "Movement regression",
  "control_mode": "solo",
  "goal": {"kind": "movement", "subject": {"role": 0}, "minimum": 1},
  "max_duration_ms": 10000,
  "steps": [
    {"kind": "require", "condition": {"predicate": "menu_closed"}},
    {"kind": "action", "command": {"action": "backward", "duration_ms": 750}, "timeout_ms": 5000}
  ]
}
```

Choose movement direction and location from current observations. Input remains limited to the reviewed fixed action catalog. `use_item`, `approach_target` and `interact_target` are replay-only contracts and are refused before native input; arbitrary item selection and navigation are not implemented. The standalone backend has no input provider. This prevents a plan from claiming semantics the adapter cannot verify.

Native plans sample every 500 ms, allow at most 256 frames/120 seconds, and require a sample-gap tolerance of at least 500 ms. Menu stalls, unavailable actors, changed world/lifetime, provider faults and incomplete observations make the result inconclusive. IDs are valid within a capture; targets from an earlier capture must not be reused. HP and inventory changes do not establish causality. Plans do not independently restore saves/files.

For repeatable installation/save isolation, register a fixture and bind its ID in the plan. Pass that plan ID in the matching `SuiteCase` to `create_gameplay_suite`. `advance_gameplay_suite("prepare")` restores the checkpoint and launches the owned game. Observe each menu before loading the game, then `evaluate`. The suite restores saves, profiles and deployment after each trial. A fixture cannot guarantee deterministic AI or RNG.

## Search assets and edit supported textures

`build_asset_index` creates a private SQLite atlas from ARC v7 headers. Search by logical path, type hash or repeated logical names with `search_assets`. `extract_indexed_asset` validates the indexed archive header and extracts a chosen occurrence. An index describes header metadata, not a frozen copy of every payload. Rebuild after archive changes.

`inspect_asset_references` resolves serialized parameter strings against exact indexed paths. Results are candidate references, not a complete engine dependency graph. Repeated names/types are logical duplicates; compare extracted hashes to establish byte equality.

`export_texture(entry_id, mip)` produces DDS plus a PNG preview for TEX 0x99 single-surface 2D DXT1/DXT5 textures (reviewed types 20/25 and 24/31/47). It preserves all mip payloads. Preview channels are stored channels: normal maps are not reconstructed and no color-space transform is implied. Up to 14 mips are supported; preview a smaller mip above four million pixels. Cubemaps, arrays and other encodings are refused.

Edit a separate DDS copy with an external editor, preserving dimensions, mip count and compression. Configure its folder in `mod_sources`, then call `import_texture_dds` with the named source, relative path and expected SHA-256. The imported private blob preserves TEX metadata and validates the round trip. Repack it through the normal archive/profile workflow.

## Build a standalone native mod

`generate_ddda_sdk` writes a versioned C++/JSON SDK, a native event provider, offline guard, CMake project, license and `example_mod.cpp`. `build_research_bridge` builds the Win32 DLLs and runs both contract executables. Bundled pinned source and MinHook allow this without a co-op checkout. Windows, Visual Studio C++ build tools and CMake are required for the native DLL; schema contracts also build with `DDDA_BUILD_BRIDGE=OFF`.

The public C ABI is `DdSdkStart`, `DdSdkReadEvents`, `DdSdkStatus`, and `DdSdkStop` in `native_sdk.hpp`. A signature-checked native stamina callback copies party values into a bounded ring. Events are samples, sampled stamina requests, HP changes, inventory changes and observed actor replacement. The queue has one consumer, 512 slots and explicit loss/error counters. Sampling is at most 5 Hz per party role; it is not a complete damage/death/loot event bus. Observed replacement IDs do not prove engine-wide lifetime tracking.

Status separates queue overflow (`dropped`) from callbacks skipped because the sampling lock was busy (`contended_callbacks`). Contention can include non-party callbacks and does not count lost queued events. Neither counter establishes complete gameplay coverage.

For a mod, link `research_bridge.lib`, call `ResearchInitialize` from a worker, then start after world load. Drain events regularly and inspect status. `example_mod.dll` exports `SampleStart`, `SamplePoll` (a small HP-change logger), and `SampleStop`. Stop disables the hook and retains its trampoline for in-flight return paths; a later start reuses it after signature checks. Keep DLLs loaded until process exit, and never initialize/stop under the loader lock. `DdSdkStop` must verify original bytes and callback quiescence; failure requires stopping the owned process. See the generated `NATIVE_SDK.md`.

For an MCP capture, start `backend="standalone"` with the successful bridge build ID, then use `capture_native_sdk_events`. Standalone launch refuses active co-op loaders; use a journaled profile with `mod_ids=[]` and named `disable_loaders` to temporarily disable them. Restore that profile afterward. The legacy world observer and the native SDK provider cannot own the same hook concurrently.

## Diagnose exceptions, hangs and mod interactions

`capture_session_diagnostic` captures bounded module-relative thread frames from the owned game. `include_dump=true` also writes a private Windows minidump. The dump remains private because it can contain stacks and user paths. A bounded parser returns module/exception metadata without exposing process addresses or treating stack words as unwound frames. Repeated thread snapshots can help investigate a stall; they do not automatically prove a deadlock.

Native exceptions are retained even after the game exits. `list_crash_reports` and `analyze_crash_report` distinguish observed exceptions, fatal detach reports and unexpected detach. A handled exception is not a crash. Source links require an exact known RVA; nearest exported symbol names are hints. A recent exception associated with a fatal detach remains a candidate cause. Installed DLL hashes identify files on disk, not proof that every file was loaded.

`create_mod_isolation` takes 2–16 registered mods, one fixture case, a failure criterion and two or three repeats. It first requires a passing original-installation baseline and a reproducibly failing full set. `advance_mod_isolation` drives restored suites through subsets and complements, supporting interactions between mods. Observe/load the game between `prepare` and `evaluate`; `mod_isolation_status` retains progress across restarts. `abort` remains available even if an input artifact changed.

Dependencies, static conflicts, flaky results, missing evidence and failed cleanup produce inconclusive results. The suite budget is bounded to 4–64 sets. A completed result is a one-minimal reproducing subset for this installation and fixture, not a universally minimal set or proof of root cause. Crash mode requires actual fatal crash reports, not a caller-supplied failure flag. Native crash-set isolation still needs validation against a real reproducing mod combination; model tests are not that evidence.
