# Offline experiments and SDK extensions

Version 0.11.0, created by **Thingolus**, MIT licensed.

This milestone implements the offline parts of the experiment runner and broader SDK. It can validate a plan, replay copied observations and recorded actions, explain an inconclusive outcome, and generate reusable C++/JSON contracts with the game closed. The offline replay module has no native session or desktop dependency. Version 0.11 adds a separate `run_native_experiment` dispatcher; see [native workflows](GENERAL_MODDING.md). It does not launch DDDA, navigate menus, send input, load checkpoints, or restore an installation.

## Workflow

1. Call `experiment_catalog` for bounded steps, outcome meanings and backend capabilities.
2. Call `create_experiment_plan(plan=...)` to save an immutable plan. An optional registered `fixture_id` binds the fixture/checkpoint hashes; it never loads that save.
3. Call `record_gameplay_observations(recording=...)` with typed copied frames, optional recorded actions and cleanup claims. All supplied data is labelled `offline_supplied`, even if the caller selects a co-op or standalone source identity.
4. Call `replay_gameplay_experiment(plan_id=..., recording_id=...)`. The response contains a compact verdict, measurement, first failure and artifact ID. Detailed steps and recorded cleanup remain in the paginated artifact.
5. Call `query_gameplay_events(recording_id=..., kind=..., entity_key=..., offset=..., limit=...)` to replay and page derived events. It compares the current decode with the original recorded decode.

Plans support `require`, `action` and `wait`. Conditions cover HP, selected inventory quantities, menu state and distance to an exact recorded target. A wait without a condition waits for the plan's goal. A target-distance check evaluates copied positions; it is not pathfinding. Actions must match the recorded command, duration, role, item/target and before/after frame references exactly. The runner never retries an uncertain action or invents an action missing from the tape.

Example healing plan, requiring a recording of the selected item use:

```json
{
  "label": "Healing item regression",
  "control_mode": "solo",
  "goal": {"kind": "healing", "subject": {"role": 0}, "minimum": 1},
  "steps": [
    {"kind": "require", "condition": {"predicate": "menu_closed"}},
    {"kind": "action", "command": {"action": "use_item", "item_id": 43, "role": 0, "duration_ms": 350}},
    {"kind": "wait", "timeout_ms": 5000}
  ]
}
```

`use_item`, `approach_target` and `interact_target` are typed future operations that can be replayed. Their native backend capabilities are **false**. Saving this plan does not make item selection or targeted interaction work in the game. Existing fixed-input tools remain available separately under their existing guards.

## Observation contract

Recordings have a single session/build/clock identity and at most 256 strictly ordered frames over 120 seconds. Co-op and standalone identities require the appropriate runtime or bridge hash. Each frame has a stage, generation, sequence, elapsed time, completeness/omission flags, optional menu state and at most 26 copied actors. Inventories are bounded to 256 entries; duplicate item stacks are summed by item ID.

Actor keys are opaque strings, not pointers. Capture-scoped IDs only match within their declared capture epoch. Session-scoped IDs additionally require an incarnation, so a replacement actor cannot silently inherit its predecessor's identity. **Native adapters supply capture-scoped recordings; verified session-wide lifetime identities remain unavailable.** A caller assigning an incarnation to supplied data does not establish native lifetime tracking. Existing raw world captures must not be relabelled with fabricated cross-capture identities.

Unknown HP, position, menu or inventory stays unavailable. Incomplete observations, nonadjacent sequences, excessive sample gaps, changed stages/generations and changed actor lifetimes prevent comparisons. No delta is inferred across those boundaries. Raw pointer fields, unknown commands, nonfinite numbers and unbounded lists are rejected by the schemas.

Derived events are `hp_decreased`, `hp_increased`, `zero_hp_to_positive`, `inventory_delta`, and `action_changed`. They describe sample differences, not notifications from the engine. In particular:

- Combat measures net HP reduction for the selected subject; it does not identify an attacker or prove a particular attack caused damage.
- Healing measures a net HP increase from a positive initial HP.
- Revival requires initially zero HP and subsequently positive HP; complete engine revival state remains unknown.
- Loot measures a selected item's net quantity increase; pickups, purchases and transfers are not distinguished.

The event response is capped at 4,096 events and reports omissions. Pagination does not turn a truncated event stream into complete evidence.

## Failure and measurement semantics

Each plan has at most 32 steps, bounded action/wait deadlines, a total budget of at most 120 seconds and a maximum allowed sampling gap. Solo plans cannot command P2. A positive measurement never overrides an interrupted/unknown recording or unverified cleanup. A short recording ending before its deadline is inconclusive. An observed unsatisfied condition at its deadline fails the replay. Missing evidence remains inconclusive.

Cleanup fields are **recorded claims** about input release, observers and restoration. Replay does not independently verify those claims against the installation. All outcomes remain `offline_replay` with `native_acceptance: unverified`.

Metrics report decoder elapsed milliseconds, consumed recorded milliseconds, matched actions, completed steps and consumed/unused frames. `response_payload_bytes` measures the compact payload before adding that metric, excluding the MCP envelope and duplicate transport representations. `model_tokens` remains null. These are not paired development-efficiency or token-savings measurements.

## SDK generation and offline compilation

`generate_ddda_sdk` now also writes:

- `ddda_observations.hpp`, namespace `ddda::observations_v1`, with typed identities, availability flags, inventory, derived events and commands.
- `gameplay_schemas.json`, generated from the same Pydantic models used by MCP.
- `observation_contract.cpp`, an executable validation contract.

The existing `ddda_sdk.hpp` / `PartySample` v1 interface remains unchanged. The extension contains host-side copied types, not native memory overlays, newly reviewed engine exports or a dispatch implementation. Capability checks distinguish existing co-op fixed inputs from unavailable standalone/semantic commands.

The generated CMake project supports `-DDDDA_BUILD_BRIDGE=OFF` for building only the two SDK contract executables without MinHook or native bridge dependencies. The existing `build_research_bridge` builds the bridge and both contracts from pinned sources; building does not launch the game.

## Remaining live work

Live integration still needs callback-verified lifetime identities, broader enemy/event coverage, standalone input ownership, safe target-aware movement and interaction, item/menu selection, and native scenario fixtures. The new runner is not connected to `advance_gameplay_suite` for native dispatch. That connection must retain the existing session lease, guard checks, deployment/save journals and cleanup verification. New upstream signatures also require deliberate compatibility review before adoption; this milestone retains the existing pin.

Run `pytest -q`, the read-only stdio smokes, and `scripts/offline_workbench_smoke.py` for implementation checks. The latter exercises synthetic replay and a real private item-file round trip without launching DDDA or applying a mod profile. Native acceptance remains a separate future step.
