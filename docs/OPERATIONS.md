# Operations

Version 0.2.0 by Thingolus. Configuration is read from ignored `config/local.json` or the `--config` path. Start with `config/local.example.json`; unknown configuration fields are rejected. Relative paths resolve against the project, not the caller's working directory. Run `--check` before connecting a client.

## Read-only development loop

1. Call `project_status` and `inspect_build` to establish source and executable identity.
2. Use `search_knowledge` to find prior experiments, then `lookup_symbol` to find a function's research and signature records.
3. Use `read_source` for the pinned source lines and `inspect_binary` for bytes, disassembly, strings, or candidate absolute references. Binary offsets are RVAs, not process pointers. A candidate reference is not proof of a call graph edge.
4. Follow returned artifact IDs with `read_artifact`. Compare compatible captures with `compare_runs`.

All 24 tools advertise input and output schemas. Invalid operations return structured errors. Tool descriptions and schemas provide the precise argument names and limits. Four resource routes expose project status, build identity, symbol data, and run artifacts.

## Native sessions

Native sessions require all of the following:

- A normal Windows host with Python 3.13 and the `live` dependency extra.
- `profile: "development"` and the exact supported DDDA executable.
- A hash-valid `ddcoop-deployment.json` research installation. Player install manifests and loose DLLs are not silently adopted.
- Explicit `[coop] online_mode=0` settings; synthetic input additionally requires the runtime development gate.
- No running DDDA instance and no competing game-directory lease.

`start_session` creates a job. Poll `job_status` until completed, then use `session_status` and `runtime_snapshot`. Use `capture_trace` for bounded copied observations. The snapshot separates the live transport guard from the callback-copied fields: `native_state: pending_game_initialization` is expected before the game establishes native offline state. Observations remain available while transport is blocked. `input_admitted` stays false until the native state, developer gate, and fault checks pass.

`run_scenario` supports `observe_idle`, `neutral_input`, and `dismiss_title`. The last recipe sends one 250 ms Start press, once per owned session, only with developer input enabled and no loaded stage, generation, or actor observations. It releases input on completion/cancellation. It never presses A, selects New Game, navigates menus, or loads a save; accepting the input request does not prove the title screen advanced. Foreground/modal restrictions can prevent the game from responding. The `seconds` argument applies to observation/neutral recipes; title Start always lasts 250 ms. These recipes do not establish physical-controller or full co-op acceptance.

`cancel_job` cancels an operation and performs its cleanup. `stop_session` terminates the broker-owned game process without saving. A failure or timeout may make the session unusable; inspect its evidence and stop it before creating another. Never retry an action with an unknown outcome automatically.

## Isolated build jobs

Set `cmake` to a CMake executable path if it is not in PATH. CTest must be beside it. The build expects Visual Studio 2022 C++ tools, the Win32 target, and the pinned MinHook Git commit available in the co-op checkout's `external/minhook`. It uses Git objects, so dirty files in either source tree do not enter the build.

Call `build_and_test` with `configuration: "Debug"` or `"Release"` and `test_group: "core"` or `"all"`. Core runs the three upstream CTest entries for core/hooks, settings, and controller-session policy. All requests the full upstream build/test set and holds the game-directory lease with DDDA closed because its graphics test creates a D3D device. Poll the job and inspect its artifact summary; job completion alone does not mean tests passed. Build artifacts contain exit codes, log hashes/tails, test counts, and DLL hashes when produced. Full logs remain under the private build run folder. Build success is not native gameplay acceptance.

For an integration check without game access:

```powershell
.venv/Scripts/python.exe scripts/build_smoke.py --cmake "C:/path/to/cmake.exe"
```

## Ghidra

Set `ghidra_home`, `ghidra_project_dir`, `ghidra_project_name`, and optionally `java`. Supply an existing project containing `DDDA.exe`, close its interactive owner, and call `decompile_symbol` with an exact signature-backed symbol name. The fixed export script verifies the database's executable SHA-256, opens it read-only with analysis disabled, and bounds decompilation. Automatic import and arbitrary user scripts are not exposed.

For a new local database, `scripts/setup_ghidra.py` downloads and hash-verifies the pinned Ghidra/JDK archives into ignored `.tools` and configures their paths. Run `scripts/prepare_ghidra.py` explicitly to import the supported game and prepare `pawn_delete`; add `--analyze` for bounded full analysis, or to analyze an existing configured project. This CLI setup changes the analysis database; the MCP export does not. Java uses the distribution's required Windows launch options. `scripts/decompile_smoke.py` verifies the actual stdio export and keeps the decompiled code private.

## Acceptance scripts

- `scripts/native_smoke.py`: owned launch, status/performance, two-client refusal, observation traces, comparison, cancellation and verified stop. `--neutral` additionally requires a developer deployment and native offline readiness after a bounded title Start attempt.
- `scripts/lifecycle_smoke.py`: starts separate owned games to check stdin EOF, parent death, and heartbeat expiry. It supplies no input.
- `scripts/transaction_smoke.py`: backs up explicitly configured player saves, temporarily applies a developer candidate, rolls back byte-for-byte, and tests restore/undo on a disposable save copy. `--native` runs the neutral smoke before rollback. Player saves are checked and restored from the initial backup if the test changed them.
- `scripts/build_smoke.py --cmake <path> --group all`: full isolated build/test pipeline. Run while DDDA is closed.

These are opt-in maintenance/acceptance commands, not normal server startup behavior. Evidence goes to ignored `artifacts/validation` and `private/runs`.

## Deployment

Configure a named candidate, for example `"deployment_candidates": {"research": "private/candidates/research"}`. Its folder must contain the three payload files and `candidate.json`:

```json
{
  "game_sha256": "19facc2642f79a09d14ce55eace5f228161f2f8bab60ec67eb3c6196cc6277b8",
  "files": {
    "dinput8.dll": "<actual SHA-256>",
    "ddcoop_runtime.dll": "<actual SHA-256>",
    "ddcoop.ini": "<actual SHA-256>"
  }
}
```

Use either `dinput8.dll` or `xinput1_3.dll`, never both. The runtime must export the required co-op API and match the adapter's ABI at runtime. Call `prepare_deployment`, review the returned file hashes and before-state, then call `apply_deployment` with the receipt ID. The game must remain closed. `rollback_deployment` uses the same receipt and can recover an interrupted apply when current hashes establish ownership. It refuses unrelated edits. Loader migration and adoption of an existing player installation are outside this workflow.

## Saves

Add specific local save directories to `save_roots`. `backup_saves` copies `.sav` files with hashes into private storage while the game is closed. `restore_saves` accepts a backup ID, validates hashes and existing destinations, creates an undo backup, and restores the selected backup. It does not install missing save fixtures or change cloud synchronization. Multi-file restore is not an atomic transaction; retain the private backup directory for recovery.

## Common failures

| Error | Action |
| --- | --- |
| Source mismatch or missing commit | Fetch the pinned commit into the co-op checkout; do not replace the manifest with dirty file hashes. |
| Tool missing | Configure the installed CMake, Java, or Ghidra path. |
| Unsupported build | Use static analysis only until a separately validated adapter supports that executable. |
| Existing game / lease / restricted host | Close the owning workflow, or run the server from a normal Windows host with full process visibility. |
| Deployment unowned / changed / foreign files | Inspect the existing installation and its owner; do not overwrite its files. |
| Outcome unknown | Inspect the durable receipt and remaining process state before any manual recovery. |

Diagnostics go to stderr so stdout remains MCP transport. `artifacts/validation`, `cache`, and `private` are ignored by Git.
