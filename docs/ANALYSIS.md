# Investigation and comparison workflows

Version 0.4.0, by Thingolus. These tools do not launch DDDA or deploy files. Results are private, paginated artifacts; proprietary disassembly, DLLs and decompiled code stay out of Git and release packages.

## Investigation bundle

Call `investigate_symbol` with an exact symbol name, an optional research `query`, and `include_decompilation` (default false). Poll the returned job through `job_status`. Its result contains an artifact ID and compact summary; use `read_artifact` or the run resource to inspect the details.

The bundle contains symbol/signature records, up to five research excerpts, source passages, a bounded disassembly excerpt, encoded absolute references, and candidate direct relative-call sites. The call scan covers at most 16 MiB of executable-section bytes, examines at most 100,000 E8 candidates, and returns at most 20 matches. It does not recognize indirect calls or prove instruction/function boundaries; zero candidates is not proof of no callers. Bounds and truncation are recorded in the artifact.

Binary analysis at recorded RVAs requires the supported executable. Missing/unsupported binaries produce a partial bundle with explicit unavailable components rather than applying known addresses to an unknown game. Changing executable bytes during collection is an error. Optional Ghidra export requires the development profile and existing hash-matched database; the bundle links the export artifact, keeping potentially large decompiled code separately paginated. Missing Ghidra tools/database or export failure are explicit partial results. Cancellation propagates to the export subprocess.

Example: `investigate_symbol(symbol_name="pawn_delete", query="pawn", include_decompilation=true)`. Job completion means evidence collection finished; `summary.complete` describes requested component availability, not gameplay acceptance or exhaustive caller coverage.

## Compare committed source

`compare_source_revisions(before_commit, after_commit, offset=0, limit=50)` accepts full 40-character commit SHAs already present in the configured co-op source repository. It does not accept mutable branch names, run Git hooks, alter the checkout, or read dirty source files. The returned artifact records both commits, changed paths/blob IDs, signature deltas, bounded diff excerpts and lexical function-context candidates.

Follow `summary.next_offset` to inspect another page. Each page contains at most 50 files. Text excerpts are limited to files up to 64 KiB and 2,000 lines, with at most 150 diff lines / 6,000 characters per file; larger and binary files receive hash comparisons. Up to 100 signature deltas are listed with total/truncation counts. Function contexts are a lexical aid, not complete semantic analysis. ABI/signature/settings path changes trigger review hints. A new comparison commit does not replace the manifest's pinned baseline.

## Compare named runtime builds

`compare_builds(before_name, after_name)` accepts `installed` or a directory named in `analysis_builds` or `deployment_candidates`. Add paths to trusted local configuration, for example `"analysis_builds": {"baseline": "private/builds/baseline", "trial": "private/builds/trial"}`. Each named directory needs `candidate.json` containing a target `game_sha256` and exact `files` SHA-256 mapping for one loader DLL, `ddcoop_runtime.dll` and `ddcoop.ini`, as described in operations. Comparison checks bytes against this inventory and never deploys the build.

Reports cover added/removed payloads, machine type, DLL marking, PE export names/ordinals/RVAs/forwarders, imports, section hashes and settings. Missing required exports, non-x86 binaries, changed preferred image base, changed developer-input settings and absent offline settings are flagged. Named analysis builds may intentionally be incompatible so they can be inspected; deployment still applies its separate strict checks.

Export movement is not proof of function-body change, and section changes cannot identify every changed function without symbols. Compilation provenance declared by a candidate manifest is labeled as a declaration rather than independently established fact. Reports never mark a build approved for deployment or gameplay.

## Local integration check

Run `.venv/Scripts/python.exe scripts/analysis_smoke.py --decompile` when the configured game/source/database are present. This compares the pinned source to its parent, creates a private copied build with only developer-input settings changed, and investigates `pawn_delete` through actual stdio including Ghidra. It verifies the installed payload hashes remain unchanged. Hosted CI instead exercises synthetic source/PE fixtures and does not include the game or database.
