# Death/refusal diagnostics

Version 0.5 adds copied-value decoding for the co-op 1.8 developer diagnostic, by Thingolus (MIT). This is observation and offline interpretation, not a revival operation.

## Owned native capture

In an existing MCP-owned development session, call `runtime_snapshot` with `group: "death_refusals"`. The runtime must enable developer input, expose `CoopSharedLifeDownDebugStatus`, and pass the existing status/offline checks. The native export receives **520 unsigned words**, not 2080 as its count; its output is 2080 bytes, version 1, eight header words and eight 64-word rows. Missing exports, refused reads and unexpected layouts return errors; no input is supplied.

Caller and opaque object pointers are stripped inside the native adapter before values cross the process boundary. The server checks the ring header, sequence, predicate masks and reasons, then saves a private `death_diagnostic` artifact containing redacted words and decoded output. Read the artifact using its returned ID. Server code does not dereference those game objects or clear the native ring.

The result distinguishes entry, post-native and capacity refusals. It reports Arisen/main-pawn role, evaluated predicates, reasons, action IDs, HP, control/input ages, recorded world/generation, counters and exact decimal-string 64-bit sequences. A predicate value of **null means it was not evaluated**. Native short-circuit evaluation must not be interpreted as a failed check. Unknown age sentinels and nonfinite HP become null with explicit context.

## Offline replay

Call `decode_death_diagnostic` with a `words` list of exactly 520 unsigned integers. This works in the read-only profile and needs no game session. It returns no pointer fields and does not establish that supplied data came from a real runtime.

Alternatively run:

```powershell
.venv/Scripts/python.exe scripts/replay_death_diagnostic.py private/runs/<artifact-id>.json
```

The CLI accepts a saved MCP diagnostic artifact, an object containing `words`, or a bare word array. A recording from another source must use the same reviewed layout. Invalid size/version/sequence/masks are rejected rather than decoded speculatively.

## Evidence limits

Only the most recent eight recorded refusals remain. Rows may belong to earlier worlds or generations. Successful revivals, some early exits, and late-death paths are not a complete event log. An empty ring does not prove the absence of a failure. A recorded refusal explains the predicates observed on that path; it does not by itself establish the cause of Game Over.

Offline tests exercise synthetic rings and the actual shipped JavaScript adapter in a synthetic Frida environment, including word-count versus byte-count, native refusal, unavailable exports, disabled developer mode and redaction. Loaded-world diagnostic capture and the original gameplay input gate remain unverified.
