# Dragons Dogma Dark MCP implementation instructions

Read `README.md`, `IMPLEMENTATION_PLAN.md`, and `reuse-manifest.json` before implementation. This checkout currently contains a plan, not a working MCP server.

- Keep this project independent from the sibling co-op repository. Do not stage, commit, reset, or overwrite that repository's active changes.
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
- Run checks appropriate to each milestone. Do not call static or mock tests native gameplay acceptance. Record build identity and remaining uncertainty.

The user's current task created the plan and private repository. Full server implementation is subsequent work.
