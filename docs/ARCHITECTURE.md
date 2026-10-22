# Architecture

Version 0.2.0 by Thingolus. The Python MCP server runs outside DDDA and exposes a typed stdio interface. Tools return structured envelopes containing request ID, operation, capture time, duration, provenance, and success or a machine-readable error. Larger results become local artifacts with bounded reads.

## Reuse and source identity

The server reads immutable Git objects at the commit in `reuse-manifest.json`; it does not import scripts from the active co-op working tree. It verifies the 42 inventoried blob identities and builds a SQLite FTS5 index from pinned documentation and experiment records. Symbol results merge research records with generated signature entries and point back to their source. This preserves the co-op project's accumulated knowledge while leaving its active work untouched.

Static inspection parses one immutable byte snapshot of the PE file, derives its SHA-256, and uses Capstone for bounded x86 disassembly. Unknown executables can receive static analysis but cannot enter native operation paths. The native adapter requires the supported executable fingerprint recorded in the manifest.

## Native boundary

The original plan proposed wrapping the legacy mailbox. The implementation instead uses a dedicated typed child-process broker, adapting the existing research host's checks and ABI readers. The legacy mailbox has a single slot and is not a reliable multi-client coordination boundary. Existing game processes cause a refusal; there is no takeover or arbitrary attach tool.

The broker validates the research deployment, offline settings, executable, and normal Windows host before spawning a suspended game process. AppContainer hosts are refused because process enumeration there cannot establish that another game is absent. A shared game-directory lock serializes MCP ownership. The broker records PID and creation time, verifies the offline transport check, loads an inert Frida script, and resumes only its own process. Its watchdog closes that process if the parent or heartbeat disappears.

The agent copies the known 132-byte status ABI and 2448-byte performance ABI into plain JSON. It also reads the transport guard directly: copied fields may remain zero at startup before game callbacks run. A pending native offline state permits guarded observation but never admits neutral gameplay input. It installs no controller timer and emits no input on load or read. Neutral input requires native readiness; a separate fixed title Start recipe is limited to 250 ms once per session with no loaded world and a verified transport guard. No tool accepts arbitrary JavaScript, native addresses to call, or raw memory writes. Stop terminates the owned process without saving.

Session operations are serialized. A mismatched broker response, timeout, or invalid snapshot makes the session unusable rather than replaying an uncertain action. Capture cleanup releases synthetic input. Cancelled and failed captures retain partial evidence and their failure classification.

## Jobs, builds, and evidence

Jobs have durable receipts, bounded concurrency, cancellation, and explicit outcome-unknown handling after loss of the owning process. Artifacts separate summaries from paginated records and include source/build/evidence provenance. Comparisons require compatible evidence and recipes and show changed inputs. Simulated test data is not native gameplay evidence.

Build jobs export the pinned source and pinned MinHook commit into a private run directory, use existing CMake/MSVC tools, and parse CTest JUnit results. They never build inside the active co-op checkout. The full suite holds the game lease because its D3D test conflicts with a running fullscreen game. Ghidra exports use a fixed script, one known symbol, an existing read-only database, hash verification, the distribution's VM options, and a bounded subprocess. Explicit CLI commands provide hash-pinned tool installation and database preparation.

The broker stops both its game and command loop on heartbeat expiry or parent death, releasing the lease. Runtime SHA-256 identifies the installed native artifact. The knowledge/source commit does not establish the runtime's compilation provenance; that commit is reported as unknown unless the deployment recorded it.

## Deployment and saves

Deployment accepts named local candidates with an exact three-file hash inventory: one loader, the research runtime, and settings. It validates x86 exports, offline settings, current ownership, and game identity. Prepare creates a receipt; apply journals backups before replacement; rollback reconciles interrupted writes against before/after hashes. Unknown files and loader migration require a separate workflow.

Save roots are explicitly configured. Backups include hashes, and restore makes an undo backup and refuses changed targets. Restore currently requires the target files to exist. Automatic fixture installation, cloud-save coordination, and transactional recovery across an interrupted multi-file save restore are not implemented. Save backup files remain available for manual recovery if a restore is interrupted.
