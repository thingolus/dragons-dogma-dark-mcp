# Combat, healing, revival and loot acceptance

23 October 2026. Creator: **Thingolus**. MIT; retain the copyright and license notice in modified distributions.

## Current result

| Scenario | Evidence from this follow-up | Status |
| --- | --- | --- |
| Healing | P1 used one Greenwarish through observed native inventory UI. Callback captures recorded HP 958.484497 to 1019 at stage 702, generation 1 before and after. | Native `healed` predicate passed, delta 60.515503. This is a native outcome check around UI input, not an automated curative recipe. |
| Combat damage | Traversal toward the quarry encounter was interrupted before a damage observation. | Unverified; earlier synthetic predicate coverage remains separate. |
| Revival | No captured downed-to-revived transition. | Unverified. |
| Loot | No confirmed pickup with a positive selected-item inventory delta. | Unverified. |

Healing artifact `d7cb9373910e43ce825101473b8f368b` has SHA-256 `9617fb67db225f2ba8dacaed1bb51936fb63799b699af54d9c2d669db098897c`. It links before-world artifact `f88eab925436488f97e558031f2e4199` and after-world artifact `9cdb3f829bc546379b6cd1fcc85a3597`. Both captures sealed successfully. The session ID is `74ce33c0924f4d9386234b52e4ec73da`. An earlier healing attempt returned an unknown predicate because its control lease expired during inventory navigation and changed the world generation; that result remains inconclusive.

The executable SHA-256 was `19facc2642f79a09d14ce55eace5f228161f2f8bab60ec67eb3c6196cc6277b8`. The reviewed Debug runtime was `61afeeca2ba9ac3c395f22cb889122ef6613b553fc80932c700ea84442571bc5`, built from unchanged pin `e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4`. The quarry fixture SHA-256 was `868370ab82d82beaaaf879e5f40f17f86d065df4d7b53e8f03353dd8289d7e8b`. Private saves, binaries and raw captures are excluded from Git and packages.

## Traversal findings and implementation changes

- Full-stick `run_forward` produced native movement with advancing callbacks and neutral provider state after each bounded action. Outdoor artifact `48b3ba49e8c549a8b32aa87e6457fb5f` recorded 342.808 game units; its SHA-256 is `5d41f6fbe740e0208b9d7721e4b80ab6bf4cc7fef1f161859ee4b69dde7cd067`. This is an observed displacement, not a speed benchmark or complete navigation test.
- The 27-action catalog adds four run directions, four camera directions and forward jumping. Synthetic JavaScript tests check pad layout, role isolation, timed neutralization, menu refusal and the 1000 ms maximum. Camera and forward-jump native behavior was not separately verified.
- Two quarry attempts stopped when both actor callback counters ceased advancing. The second reproduced this without a world observer active. Its final partial movement is artifact `678bbaba125d41beb7ee5134bbc856e5`, SHA-256 `01c38eaa0bb58b2768b0108062cd6f04da1bcd49f8f969329c12a9ba741bd07c`; the following action was rejected by the callback guard. This does not establish a native crash or a root cause.
- Later UI observations showed repeated minimization and the separate `benilla worldview` window covering DDDA during a windowed diagnostic attempt. Focus contention is a possible explanation for interrupted progression; it is not retrospectively proven as the cause of every stall. Further native input was stopped to avoid competing desktop tasks.
- Future final-status guard interruptions now retain an inconclusive action artifact before release. A storage-failure test verifies that failed persistence cannot skip release.
- Nearby registry observations now identify their sampled origin role/position and explicitly decline to infer hostility. The historical `enemies` name remains for compatibility. The health observer's description now matches its existing two-class allowlist, including quarry `uEm0900`; no new native memory layout or health write was introduced.

Each attempt closed only its owned game and restored its deployment and original saves, with unchanged shared-life state. The temporary windowed 1280×720 configuration was restored byte-for-byte to the original fullscreen configuration. The dirty sibling source checkout was not modified or used for a build.

## Remaining native procedure

1. Use a desktop interval without another task taking game focus. Load the verified quarry fixture and confirm advancing callbacks. Keep party separation modest while navigating; the proposed paired traversal retry has not been completed.
2. Reach and visually identify the quarry encounter using bounded movement and camera actions. Register a fresh native save checkpoint near the encounter so subsequent trials avoid the long approach. Preserve the arrival fixture and original saves.
3. For damage, capture the world before, start the reviewed health trace, run a bounded attack interval, stop and seal the trace, then capture the world after. World and health observations share one trace slot. Require complete, same-generation evidence with positive main-resource subtraction. Do not attribute the attacker from subtraction events alone.
4. For revival, capture a validated actor at HP ≤ 0, perform native Aid, and capture HP > 0 without changing world generation. Inspect shared-life counters alongside the transition. The current `revived` predicate proves only this HP transition; a missing callback from a downed actor must remain unavailable, never a fabricated zero.
5. For loot, capture inventory before and after a visible native pickup, select the observed item ID, and require a positive quantity delta. An interaction animation or registry object alone is insufficient. Record fixture identity and repeat each accepted check from a fresh checkpoint before claiming repeatable suite coverage.

Keep control leases out of lengthy inventory navigation unless intentionally renewed. Release only after returning to a world with advancing callbacks; otherwise the verified fallback is owned-process shutdown and restoration.
