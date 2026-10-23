# Combat, healing, revival and loot acceptance

23 October 2026. Creator: **Thingolus**. MIT; retain the copyright and license notice in modified distributions.

## Current result

| Scenario | Evidence from this follow-up | Status |
| --- | --- | --- |
| Healing | P1 used one Greenwarish through observed native inventory UI. Callback captures recorded HP 958.484497 to 1019 at stage 702, generation 1 before and after. | Native `healed` predicate passed, delta 60.515503. This is a native outcome check around UI input, not an automated curative recipe. |
| Combat damage | The ogre trace recorded 34.3671875 main-resource HP subtraction, with no errors or omissions. | Native subtraction observed; strict scenario acceptance remains inconclusive because the control generation changed. Bandits remain outside reviewed class coverage. |
| Revival | P2 zero HP, solo approach and an interaction request were captured at stage 702, generation 25. P2 stayed at zero HP. | This trial failed the revival predicate. Downed-state input now works; successful revival remains unverified. |
| Loot | No confirmed pickup with a positive selected-item inventory delta. | Unverified. |

Healing artifact `d7cb9373910e43ce825101473b8f368b` has SHA-256 `9617fb67db225f2ba8dacaed1bb51936fb63799b699af54d9c2d669db098897c`. It links before-world artifact `f88eab925436488f97e558031f2e4199` and after-world artifact `9cdb3f829bc546379b6cd1fcc85a3597`. Both captures sealed successfully. The session ID is `74ce33c0924f4d9386234b52e4ec73da`. An earlier healing attempt returned an unknown predicate because its control lease expired during inventory navigation and changed the world generation; that result remains inconclusive.

The executable SHA-256 was `19facc2642f79a09d14ce55eace5f228161f2f8bab60ec67eb3c6196cc6277b8`. The reviewed Debug runtime was `61afeeca2ba9ac3c395f22cb889122ef6613b553fc80932c700ea84442571bc5`, built from unchanged pin `e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4`. The quarry fixture SHA-256 was `868370ab82d82beaaaf879e5f40f17f86d065df4d7b53e8f03353dd8289d7e8b`. Private saves, binaries and raw captures are excluded from Git and packages.

## Traversal findings and implementation changes

- Full-stick `run_forward` produced native movement with advancing callbacks and neutral provider state after each bounded action. Outdoor artifact `48b3ba49e8c549a8b32aa87e6457fb5f` recorded 342.808 game units; its SHA-256 is `5d41f6fbe740e0208b9d7721e4b80ab6bf4cc7fef1f161859ee4b69dde7cd067`. This is an observed displacement, not a speed benchmark or complete navigation test.
- The 27-action catalog adds four run directions, four camera directions and forward jumping. Synthetic JavaScript tests check pad layout, role isolation, timed neutralization, menu refusal and the 1000 ms maximum. Subsequent traversal observed native camera turns and forward-jump action/displacement, without establishing general navigation or landing guarantees.
- Two quarry attempts stopped when both actor callback counters ceased advancing. The second reproduced this without a world observer active. Its final partial movement is artifact `678bbaba125d41beb7ee5134bbc856e5`, SHA-256 `01c38eaa0bb58b2768b0108062cd6f04da1bcd49f8f969329c12a9ba741bd07c`; the following action was rejected by the callback guard. This does not establish a native crash or a root cause.
- Later UI observations showed repeated minimization and the separate `benilla worldview` window covering DDDA during a windowed diagnostic attempt. Focus contention is a possible explanation for interrupted progression; it is not retrospectively proven as the cause of every stall. Further native input was stopped to avoid competing desktop tasks.
- Future final-status guard interruptions now retain an inconclusive action artifact before release. A storage-failure test verifies that failed persistence cannot skip release.
- Nearby registry observations now identify their sampled origin role/position and explicitly decline to infer hostility. The historical `enemies` name remains for compatibility. The health observer's description now matches its existing two-class allowlist, including quarry `uEm0900`; no new native memory layout or health write was introduced.

Each attempt closed only its owned game and restored its deployment and original saves, with unchanged shared-life state. The temporary windowed 1280×720 configuration was restored byte-for-byte to the original fullscreen configuration. The dirty sibling source checkout was not modified or used for a build.

## Exclusive-desktop follow-up

The next run progressed with responsive callbacks and reached native combat. The first bandit trace is artifact `e0ee638e6b07451e8b8e4b1b08c8c904`, SHA-256 `fe7e76ec5b36a083a9f3e4ede32a909eab61028738fa9b4817faab432346d910`: sealed, zero errors, zero omissions and zero qualifying health rows. Its damage predicate is false within the observer's reviewed scope, not a general combat verdict.

P2 zero HP is captured in `53bcc2a7695242b69de78c411979f9f5` (SHA-256 `062f633fda4d2b256dacfc8eaeaae5f2a8b4b2cae6b70c77242ccf3cd03bee6f`). A later attempt captured P1 zero HP in `da39215c886647f4b68469e718c14584` (SHA-256 `1480fae97307e4f30978e7b7464c715ab5a6ca39190adbec20b8c5aad31a87c4`). Shared-life observations corroborated downed masks and recorded no completed revival. Outcome artifacts `018bbb4adfb24d218680117c4afe9d2c` and `740364ee5d7c4ed98993b05f1dda348d` remain inconclusive because party observations became unavailable or world generation changed. Native Aid was later observed on a support pawn, which is outside the two-role HP decoder and cannot satisfy this predicate.

Paired control leaves the main pawn idle while P1 is steered. The new optional `solo` mode connects only slot 0, retains pawn AI, refuses role 1 actions and preserves all existing guards. Native artifact `4e30441ecfd94fa7b8c0e221909e648c` (SHA-256 `f0f4df2f2b4e0d951e7d728d07e359b76f958069975c7dbda5e82d52897c920b`) recorded 348.006 game units of P1 displacement, advancing callbacks and neutral input afterward. The subsequent copied state had `p1=0`, `p2=-1`, session state 1, and a moving main pawn. This verifies the narrower solo ownership/movement behavior, not the remaining scenario outcomes.

A native save before the bandits was privately copied and then reloaded in a new owned session at stage 702, position `[25.676081, 652.888062, 7137.330078]`. Save SHA-256: `36555c67a8eace9f0df035e2ab7acb804ec391398e86d23b790dbd40d311ba53`. Ten advancing samples in trace `3b25df7a375b41609bcb4235caffb99a` establish loaded-world readiness. Registered checkpoint `f8dad801c071441287e62a4ef728489b` (SHA-256 `f385578b6b2e85f7a6b96ad63d28f2c878c0719146effcea45b290c9fae95225`) and fixture `21fe3441f6c3447e930ae8c3c573e007` shorten future retries. They do not guarantee AI/RNG state or combat outcomes.

The solo run reached approximately Z=12363 before a two-page support-pawn notification. That native modal paused callbacks without setting the copied menu flag. An attempted movement was interrupted and the owned game stopped when callback-based release could not be verified. Dismiss all observed notification pages before requesting more input; never infer readiness from `menu_gated` alone.

## Downed-pawn control correction and final trial

Source review at the unchanged pin found that `CoopGetStatus.menu_gated` is written from P2's `engine_gate`, which also rejects the downed flag and zero HP. Treating it as a pure menu flag prevented P1 from approaching a fallen pawn. Solo control now uses the reviewed copied `inventory_menu` diagnostic and fresh P1 callback progress. It requires known native P1 gameplay, an absent inventory lifetime, no menu lease block and matching generation. Every solo claim samples callback progress across 100 ms; active control requires progress observed within 150 ms for gameplay admission. Pair behavior is unchanged. Cancellation while a claim waits cannot later publish input.

The native trial captured P2 at zero HP in `d25c4a070dd249358ca4fd77fd6964bb` (SHA-256 `fce2a1ceacf95f6c7cb3922feadb9a7bec876b010494d39492441fcce03c2a28`). After verified paired release, solo claim succeeded while the aggregate flag remained one. Movement artifact `eba93486942149f292746292619f8dc5` (SHA-256 `c3a86db435659bf9cac57cccf98f7e57c5818269c6f7179d7e580a282e3810a4`) recorded 299.987 game units, advancing callbacks and neutral input. Further approach inputs also completed. These observations verify the downed-pawn control correction; final additional absent-inventory and cancelled-claim checks have synthetic coverage.

A visible Aid prompt was followed by bounded interaction, but the tracked main pawn remained at HP 0. Result `afaa240fd5554e29b8ab38e1dbc40c02` (SHA-256 `f0c87e440481005237234a0aed93724e85da24c225b089dc25f21074ed91363b`) has a false revival predicate, with stage 702 and generation 25 unchanged. Shared-life downed mask stayed 2 and completed-revival count stayed zero. P1 lost health during the attempt and subsequently died. The visible prompt does not establish that the targeted pawn was the main pawn or that Aid completed.

The preceding ogre interval produced artifact `dc460de357ce43c2b34cc61103dfe2af` (SHA-256 `abe1271c01ec91c55021bd45beea30ff30419ea0049cf5b9f53dd4345a4744c9`). Its sealed trace has two health rows: one secondary part and one main resource. Main HP fell from 18975.0390625 to 18940.671875, a subtraction of 34.3671875. The capture has zero errors, zero omissions, restored hook bytes and zero active callbacks. Before/after generation changed from 9 to 10, so the strict outcome remains inconclusive. The attacker is not identified. A further interval after P1's death also remained inconclusive.

Native inventory UI showed another reason not to trust the aggregate flag alone: `menu_gated=0` and cached `native_gameplay=1` while inventory lifetime was active and callbacks were paused. Final solo admission therefore checks inventory lifetime and callback freshness even with a clear aggregate flag. The synthetic contract covers this case, unknown diagnostics, generation mismatch, active-action revocation, stale callbacks and cancellation before pad publication.

The final independent restoration audit verified original DLLs, settings, deployment manifest, executable, save and shared-life hashes, byte-identical display configuration, clear recovery markers and a closed owned game. Private evidence and test saves remain excluded from Git.

## Remaining native procedure

1. Use a desktop interval without another task taking game focus. Load the verified quarry fixture and confirm advancing callbacks. Use solo control for AI-assisted traversal; pair mode is available for deliberate two-actor tests.
2. Reach and visually identify the quarry encounter using bounded movement and camera actions. The approach checkpoint is ready; a closer checkpoint after clearing the bandits would shorten further retries. Preserve the arrival fixture and original saves.
3. For damage, acquire a fresh control lease before capturing the world, start the reviewed health trace, run a bounded attack interval, stop and seal the trace, then capture the world after. World and health observations share one trace slot. Require complete, same-generation evidence with positive main-resource subtraction. Do not attribute the attacker from subtraction events alone.
4. For revival, capture a validated actor at HP ≤ 0, perform native Aid, and capture HP > 0 without changing world generation. Inspect shared-life counters alongside the transition. The current `revived` predicate proves only this HP transition; a missing callback from a downed actor must remain unavailable, never a fabricated zero.
5. For loot, capture inventory before and after a visible native pickup, select the observed item ID, and require a positive quantity delta. An interaction animation or registry object alone is insufficient. Record fixture identity and repeat each accepted check from a fresh checkpoint before claiming repeatable suite coverage.

Keep control leases out of lengthy inventory navigation unless intentionally renewed. Release only after returning to a world with advancing callbacks; otherwise the verified fallback is owned-process shutdown and restoration.
