# Gameplay development — version 0.8

Created by Thingolus. MIT; retain the copyright and license notice in modified distributions.

## Control and inspection

Build the pinned source using `build_and_test`, then deploy that build through a candidate or verification campaign. Input ownership requires its unchanged local build receipt and DLL hash, a development profile, an owned session, offline guards, and a loaded world. A source-commit label alone cannot authorize ownership. Modified native source is not automatically approved as the reviewed input provider; such patches can still use idle verification. Test-only overlays retain the provider review.

`control_gameplay(claim)` supplies neutral synthetic pads, claims P1 with a fresh Start edge, then holds Start to join P2. The game must have focus. Slots 0/1 are fixed; conflicting assignments are refused. The pinned runtime replaces physical samples with developer samples, so a connected physical controller does not require unplugging or device changes. This is synthetic-provider acceptance, not a physical-controller test.

`gameplay_action` accepts only named actions from `gameplay_catalog`. Individual input lasts 50–1000 ms and returns observed movement, action and menu changes. It never exposes arbitrary pad bytes or native calls. The lease expires after 30 seconds without an action, has a two-minute absolute limit, and releases on world/assignment/fault/frame-stall changes. The underlying runtime also expires provider samples after two seconds. Heartbeats do not renew the lease. Old input recipes refuse to compete with it.

The catalog now has 27 fixed actions, including full-stick `run_forward`, `run_backward`, `run_left`, `run_right`, four `camera_*` directions and `jump_forward`. The existing walking actions retain their half-stick input. These additions use the same duration, role, menu and release guards. Running is not a stamina-consuming sprint command. Reported distance is raw coordinate displacement: unresolved region-origin shifts can produce large jumps, so it must not be treated as movement speed. Camera and forward-jump input contracts have synthetic coverage; their native effects still require acceptance.

If the final control status reports a guard interruption, `gameplay_action` saves its copied before/sampled state, request and guard status as an inconclusive artifact before releasing input. The error includes that artifact reference. Cleanup still runs if artifact storage fails. A focus loss or minimized game can stop callbacks; the guard does not identify the underlying cause. Keep other desktop automation out of a native acceptance run.

`control_gameplay(release)` disconnects synthetic pads and requires advancing callbacks with no held input and no assigned slots. If that cannot be verified, the owned game is stopped without saving. Menus may suppress callback advancement, so shutdown is a valid fallback and is reported separately.

The dodge request uses the researched Strider RB, then RB+A+direction sequence. It requires 350–1000 ms to deliver both phases and a recent world observation of Strider/daggers. Learned evasion and successful dodge semantics are not inferred from sending this request. Attack commands similarly do not imply damage.

`inspect_world` installs the reviewed stamina observer for 0.2–10 seconds. Actor, inventory and registry reads happen only in its native callback. RPC reads return copied results. It reports:

- P1/P2 position, action, vocation, weapon kind, HP/max/white HP and stamina where validated.
- Inventory item IDs and quantities, at most 256 entries per player, with availability flags and identity rechecks.
- Nearby registry candidate IDs/type/category/position under the historical `enemies` field, capped at 24 results and 256 registry entries scanned. Membership does not establish hostility. Resources are decoded only for the two reviewed classes, including quarry `uEm0900`; other classes retain null resources. Radius is 3000 game units around the last sampled party actor, without an occlusion claim. Co-op captures include `origin_role` and `origin_position`, so an empty scan around a distant P2 is not mistaken for an empty area around P1.
- Observation timestamps/ages, omissions, callback errors, and verified hook cleanup.

IDs are opaque and scoped to one capture and observed lifetime. Address reuse between observations cannot be ruled out. Missing callbacks, unreadable inventories and unsupported enemy health remain unavailable. Quest fields are explicitly unavailable because no reviewed quest layout has been established. The inn checkpoint's stage/name is not quest-state evidence. Maximum stamina requires a native calculation and is not fabricated from current stamina.

## Reusable scenarios and diagnosis

`run_gameplay_harness` accepts the existing idle recipes plus `movement_pair`, `attack_pair`, `jump_pair`, `menu_roundtrip`, and `interaction_menu`. Every scenario checks its checkpoint first, claims input, records each bounded step and evaluates an explicit predicate. Movement requires displacement; attack/jump require an action transition; menu cases require gate changes. An interaction fixture must face an appropriate object. A timeout or missing observation is inconclusive; a completed but unsatisfied predicate fails.

Scenario captures include a bounded native trace (health for attacks, stamina otherwise), step observations, input release and cleanup, and the owning broker's redacted log tail. Saturation and zero events remain visible. Observers are detached and verified before release; an unsealed observer stops the owned process. The default also stops the game after successful tests.

`diagnose_scenario` identifies the first observed failed/unknown step, preserves errors/cleanup, and links immutable source references and up to eight trace/Ghidra artifacts. Same-session events can be inspected together. Cross-session evidence and static decompilation are not silently merged into a causal timeline. No crash dump is collected automatically; process failure is not a root-cause finding.

## Isolated patch verification

1. Use `create_source_patch` with exact original SHA-256 hashes and full replacement text. Up to 16 C/C++ files under `src/`, `include/`, or `tests/` are allowed, 128 KiB per file and 512 KiB total. New files use a null original hash. Build scripts and arbitrary commands are not accepted.
2. Optionally run `build_and_test(patch_id=...)` first. Patches apply only inside an immutable Git archive. The sibling working tree is never used or edited.
3. Call `create_patch_verification(checkpoint_id, patch_id, recipe, repeats)`. Baseline and candidate use the same save and selected predicate, with 1–3 trials each.
4. Use `advance_regression_campaign(prepare)`, navigate observed Load Game menus, then `advance_regression_campaign(evaluate)`. Repeat until completed. Each evaluation stops its game, rolls back its deployment and restores its original saves. Abort recovers an interrupted trial through the existing journals.
5. Read `regression_campaign_status`: baseline/candidate verdicts, improved/regressed/unchanged comparison, diagnosis links and an evidence-linked investigation note. Inconsistent trials and changed shared-life state remain inconclusive. “Unchanged” covers only the tested predicate.

Local build reuse keys include immutable source, patch artifact hash, dependency lock, CMake/compiler identity, configuration and test group. Reused binaries and evidence are rehashed. Cached CTest results retain their original timestamps and never count as fresh native acceptance. Native trials always run again. Unknown compiler identities disable reuse. Keep caches private and invalidate them after external toolchain/SDK changes not reflected in these identities.

The original regression campaign API also accepts a selected recipe. Patches, saves, binaries, broker logs, native traces, build caches and investigation databases remain private and are excluded from releases.
