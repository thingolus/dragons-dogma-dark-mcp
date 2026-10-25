# General DDDA modding workbench

Version 0.11.1, created by **Thingolus**, MIT licensed. See [version 0.11 general modding](GENERAL_MODDING.md) for parameter formats, native plans, atlas/textures, native events and isolation. The original twenty workbench tools extend the research, gameplay, build and save APIs. Version 0.10 also adds [offline experiment/SDK extensions](OFFLINE_EXPERIMENTS.md) and [named item parameters](ITEM_PARAMETERS.md). All generated assets, SDK workspaces, profiles and native evidence remain in the configured private artifact directory.

## Behavior to code

In an owned co-op session, `capture_behavior_experiment(action="neutral", role=0, duration_ms=350)` claims the reviewed input provider, captures the world, performs one allowlisted action with health-event observation, captures the world again, and releases input. It preserves partial evidence on failure. Movement and action effects are observations; health events do not establish attacker attribution.

Pass its `before.artifact_id` and `after.artifact_id` to `compare_behavior`, with a feature name and optional successful `decompile_symbol` artifact IDs. The comparison normalizes inventory quantities by item ID, preserves unavailable fields, refuses incompatible executable/runtime/bridge identities, and links differences to immutable source references. Ghidra exports now include bounded incoming references to the function entry and outgoing analyzed call references. Indirect calls can be absent. Enemy IDs are capture-local and are never paired across captures by array position. Reports generate research hypotheses, not proof that a candidate function caused a change.

## Reusable SDK and standalone observation

1. `ddda_sdk_catalog` describes schema v1, copied party fields, reviewed layout references and backend capabilities.
2. `generate_ddda_sdk` writes a C++ header, JSON schema with source identities, contract test, CMake project and minimal offline bridge sources from the exact reviewed upstream commit.
3. `build_research_bridge(bundle_id=...)` submits a Win32 build/test job. Use `job_status` to obtain its successful build artifact ID. Generated source, DLL and observer identities are verified before launch. Visual Studio 2022 C++ tools, CMake, and the pinned upstream MinHook checkout are required.
4. If a proxy loader is installed, compose and apply a restorable mod profile with `disable_loaders=["dinput8.dll"]` (or the actual supported loader). Stop the game before profile changes. A configured local mod may supply a harmless INI payload when only a loader-disable profile is needed.
5. `start_session(backend="standalone", bridge_id=...)` launches an owned offline game with the minimal bridge. Observe and navigate the menus through the client's computer-use adapter, then call `inspect_standalone_world(seconds=2)`.
6. `stop_session`, then `mod_profile(operation="restore")`, restore the installation. Use the save backup/restore tools around checkpoint testing.

Standalone does not load the co-op runtime or its control provider. It offers callback-only party, resources, inventory and nearby-enemy observation on the supported executable. It has no standalone gameplay control or quest-state decoder. The SDK is an interface/schema foundation, not a complete native engine API. Callers must supply validated copied samples; the generated header does not make arbitrary actor access safe. The native observer drains in-flight callbacks before detaching, verifies restored signature bytes, and stops the owned game if cleanup cannot be verified.

## Asset editing

Use `list_asset_archives(query="bbsrpg_core")`, then `open_asset_archive(relative_path="nativePC/rom/bbsrpg_core.arc")`. The latter snapshots the original privately and returns an index. Search with `inspect_asset(operation="entries", artifact_id=..., query="itemName_eng")`, extract the selected index, then inspect its text with `operation="text"`.

`edit_asset_text(entry_id=..., edits=[{"index":0,"expected":"Airtight Flask","text":"Airtight Flask [test]"}])` validates the original value and keeps the text index stable. Use the actual observed text, not this example blindly. `repack_asset_archive` takes replacements containing the archive index, edited artifact ID and expected original entry SHA-256. It updates only selected index records, appends replacement compressed payloads, preserves unchanged compressed bytes and re-extracts replacements to verify them. No installed file changes until a profile is applied.

Supported structured formats:

| Format | Capability | Boundary |
| --- | --- | --- |
| Little-endian unencrypted ARC v7 | Index, extract, replace and repack | 512 MiB archive, 8192 entries, 32 MiB decompressed entry |
| Unlabelled GMD v0x10201 | UTF-8 text edits by index | No label/pointer tables; at most 100 edits per operation |
| ITL2 v20121105 | Eleven named item fields, reference validation, bit-preserving patches and field-level merges | At most 100 field edits; unknown fields/layouts remain untouched; gameplay effects unverified |
| Other ARC payloads | Opaque extraction/replacement | No semantic validation of general XFS, LOT, TEX, meshes, quest, skill or enemy layouts |

Unknown layouts are refused by the structured editor. Archives retain unused original compressed payload bytes when replacements are appended; repacking is intentionally not a compacting operation. Test data and binaries are never included in software release packages.

## Mod profiles, merging and packaging

`register_mod` records private asset IDs and targets, optional named hook declarations and required mod IDs. Targets are nativePC ARC files or root DLL/INI files; DLL payloads must be x86 PE files. `import_mod` imports a trusted directory named in local `mod_sources` configuration. Its `mod.json` contains `label`, `files` with `source`, `target`, `sha256`, and optional `hooks`/`requires`. Paths stay under that configured directory and every imported byte stream is hash-checked.

`compose_mod_profile` detects duplicate targets, missing dependencies and declared hook overlaps. It can merge independent entries of archives derived from the same recorded base, independent supported GMD text-index edits, and ITL2 changes to distinct item/field pairs within an entry. Conflicting field/text changes and opaque replacements remain unresolved. Static compatibility does not prove undeclared hook or gameplay compatibility.

`mod_profile(operation="apply", profile_id=...)` backs up originals, writes the game-directory recovery marker, and replaces only known hashes. `operation="restore"` restores original and originally absent files. Unknown user edits block recovery without being overwritten. Keep the marker and journal until recovery succeeds; do not delete them to bypass guards. Restore a profile before rolling back an underlying deployment. Suite-owned profiles also record a transaction owner so another suite cannot restore them accidentally.

`operation="package"` creates a deterministic ZIP with profile metadata, payload hashes and Thingolus credits. This is a **private local test package**, potentially containing game data; it is excluded from Git and MCP software releases. No upload is performed.

## Reusable fixtures and gameplay matrices

Register an existing save checkpoint with `register_gameplay_fixture`. Optional native world evidence must match its stage/location and have sealed, error-free observations. Traits such as vocations and nearby enemy count are observations from that capture, not promises about AI/RNG or quest state after reload.

`create_gameplay_suite` combines cases, profiles (use `null` for the original installation) and 1–3 repeats, up to 24 trials. Each case selects a registered fixture, reviewed recipe and predicate. Optionally name a configured deployment candidate; its manifest identity is frozen at creation.

For each trial, call `advance_gameplay_suite(action="prepare")` and poll its job. The suite backs up current saves, deploys the optional candidate, applies that profile and restores/launches a fresh checkpoint. The returned `client_navigation` tells an AI client how to observe and navigate the title menus. This requires the client's computer-use capability; the MCP server has no screen recognizer or blind menu-key loop. After observing the loaded world, call `action="evaluate"`. Native readiness is checked independently before the recipe runs. Evaluation records before/after captures, scenario evidence and diagnosis, then stops the owned game, restores profile/deployment/saves and checks the shared-life reserve. Repeat while state is `ready`.

Predicates are explicit: scenario completion, observed goblin-family main-resource damage, HP increase, zero-to-positive HP transition, or an item-ID quantity increase. Revival means only that HP transition; complete engine revival state is not inferred. Missing, incomplete or incompatible evidence remains inconclusive. The selected fixture and action recipe must actually exercise the requested outcome; an idle inn cannot establish combat damage or healing coverage.

Use `gameplay_suite_status` to inspect outcomes and recovery. `action="abort"` restores a partially prepared/evaluated trial. Cancellation waits for an in-progress transaction, then performs journaled cleanup. After an MCP restart, abort the old suite before starting another trial; recovery refuses to stop a different owned session or replace unknown edits.
