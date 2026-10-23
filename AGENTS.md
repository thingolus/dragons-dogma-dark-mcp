# Dragons Dogma Dark MCP implementation instructions

Read `README.md`, `docs/VALIDATION.md`, `IMPLEMENTATION_PLAN.md`, and `reuse-manifest.json` before changes. This checkout contains the version 0.9 MCP implementation; the validation document separates verified behavior from remaining native acceptance.

- Keep this project independent from the sibling co-op repository. Do not stage, commit, reset, or overwrite that repository's active changes unless the user explicitly requests a cross-repository checkpoint. The 22 October 2026 sync request authorizes the committed 1.8 source checkpoint and reviewed MCP baseline refresh.
- Use the pinned upstream commit as the reproducible starting point. Record any newer commit explicitly before adopting it. Never describe uncommitted upstream work as part of the pinned baseline.
- Implement the first useful read-only milestone before live control. Wrap existing scripts through bounded adapters; first remove import-time execution and implicit path assumptions where needed.
- `research/runtime_api.js` starts a controller timer and publishes synthetic input on load. Extract its diagnostic reader; never load the whole script for a read-only tool.
- The legacy research mailbox has one command slot. All MCP clients share one coordinator. An MCP-only lock cannot protect against old scripts that ignore it; refuse access while another host owns the session.
- Do not start, attach to, stop, deploy to, or send input to an existing DDDA session just to implement or test the documentation/read-only milestone.
- Preserve executable fingerprint checks, native offline checks, transport checks, ABI validation, callback ownership, and deployment manifests when adapting live tools.
- Use typed, allowlisted operations. Do not expose arbitrary JavaScript evaluation, shell commands, raw game-memory writes, or arbitrary native function calls as MCP tools.
- Keep game pointers inside the native adapter. Return copied values, bounded results, provenance, and explicit evidence limitations.
- Keep source documentation authoritative. Generated indexes must point to source paths, hashes, and evidence rather than becoming a second hand-maintained research ledger.
- Keep private traces, saves, game assets, binaries, credentials, and decompiler databases out of Git, including private Git repositories. Retain upstream copyright/license notices when copying original project code.
- Preserve pending save journals and the game-directory recovery marker. Use the recovery tools before new backups/restores or owned game launches; do not delete a marker to bypass recovery.
- Run checks appropriate to each milestone. Do not call static or mock tests native gameplay acceptance. Record build identity and remaining uncertainty.
- Keep release packages limited to code, documentation, configuration examples and synthetic fixtures. Run the archive audit before uploading assets. Call encodings and lexical function contexts remain candidates until independently verified.

Preserve the user's requested Thingolus credit and MIT copyright/license notices. Run the Python tests and Ruff checks after behavioral changes; use the read-only stdio smoke for integration changes. Never convert synthetic checks into claims of native acceptance.

Death diagnostic rows are bounded refusal evidence, not proof of Game Over causality. Preserve null for unevaluated predicates and strip raw pointers inside the native adapter. Keep the reviewed upstream contract synchronized with deliberate adapter/pin changes; never regenerate it merely to hide drift.

New copied-value diagnostics should use the reviewed schema/decoder registry and replay fixtures described in `docs/FUTURE_WORKFLOWS.md`. Preserve separate timeline clock/session/evidence domains, source hashes and original captures. Supplied offline data cannot become native evidence. Feature investigations are lexical candidates with immutable source references, not verified call graphs or test coverage.

Gameplay control requires a locally hash-verified build of the reviewed developer provider. Physical-mask presence alone is not a conflict on that provider: the native developer route replaces raw samples. Do not apply this exception to unknown binaries. Keep action durations, lease expiry, callback guards and release verification. World actor reads belong only inside the signature-checked native callback; unavailable quest layouts remain unavailable. Source overlays apply only in isolated archives; preserve all campaign rollback journals.

General modding profiles own a game-directory recovery marker and a transaction-specific owner ID. Restore profiles before deployment rollback. Suite trials reload a checkpoint and restore saves/files after every trial; failed or missing outcome evidence remains inconclusive. Standalone is an offline observer with no co-op input provider. ARC v7 and unlabelled GMD v0x10201 are the only structured asset formats currently supported; never infer unsupported parameter or quest layouts. Keep private asset packages out of release archives.
