# Automated upstream compatibility checks

The MCP retains a reviewed source contract in `src/ddda_mcp/upstream_contract.json`, tied to the same immutable commit as its default configuration and reuse manifest. It records hashes/RVAs for 228 signature/thunk records, 48 recognized exported C declarations, INI defaults, the executable fingerprint and 15 watched source/build inputs. It contains no executable, save or raw native trace.

`project_status` and `python -m ddda_mcp --check` automatically compare the configured co-op repository's **local HEAD** with that contract. Changes to dirty files are excluded. `check_upstream_compatibility` performs the same comparison and saves a private report; supply `candidate_commit` as a full SHA to examine a different committed revision. Neither tool fetches, merges, modifies the co-op repository, replaces the reviewed pin or deploys a runtime.

For a command-line or external CI gate:

```powershell
.venv/Scripts/python.exe scripts/check_upstream.py --output artifacts/validation/upstream-compatibility.json
.venv/Scripts/python.exe scripts/check_upstream.py --fetch --output artifacts/validation/upstream-compatibility.json
```

The second command explicitly fetches `origin/main` into its remote-tracking ref using existing Git authentication, then checks that immutable commit. It does not change the working tree or configuration. `--revision <full-sha>` selects another commit; with `--fetch`, the fetch happens first. Remote commits are not monitored in the background: ordinary preflight sees changes after a local fetch/pull/checkout, and the explicit fetch command checks the remote on demand.

| Status | Exit code | Meaning |
| --- | --- | --- |
| `unchanged` | 0 | No differences in the reviewed contract. |
| `unavailable` | 1 | Required source inputs, matching contract or valid revision are unavailable; do not treat this as a pass. |
| `review_required` | 2 | Additions, default changes, watched implementation/layout/loader or build changes need review. |
| `incompatible` | 3 | Reviewed signatures changed/disappeared, required exported declarations changed/disappeared, the game fingerprint changed, or online/developer defaults are no longer explicitly disabled. |

Reports show before/after values, category counts and truncation. Watched whole-file hashes deliberately report harmless edits for review too. They cover status/performance/input/death layouts, refusal recorder implementation, guards, loaders, settings, CMake and dependency pins. Export extraction recognizes this project's C-definition syntax; it is not a general C++ parser or compiled ABI verifier. Unwatched code and indirect dependencies can still change behavior. `unchanged` is not native gameplay acceptance.

The normal Windows/Linux MCP CI runs synthetic drift tests for changed layouts, signatures, calling conventions, export removal, executable identity, unsafe defaults, missing inputs and oversized reports. It also verifies that the shipped contract matches the package's default pin. Hosted CI does not silently obtain credentials for the separate private co-op repository. A CI runner with an authenticated checkout can invoke the same CLI and enforce its exit code.

To adopt a new upstream commit, first review the report and relevant source, update adapters and regression fixtures as needed, then regenerate the contract using `capture_contract(Source(config))` against that exact reviewed commit together with the reuse manifest/default pin. Run the regression and integration checks before committing all related files together. Never overwrite the reviewed contract merely to turn a failing gate green.
