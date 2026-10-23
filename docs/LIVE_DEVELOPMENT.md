# Live development workflows

Version 0.7.0, created by Thingolus; MIT licensed. These five additions were
implemented in the requested order. All captures, saves, investigations and
campaign journals remain private local data. The source baseline remains
`e6a64c28d24bf4abda26887b0edeccc8bfd9b2a4`; dirty co-op files are never build inputs.

## 1. Checkpoint gameplay harness

With the game closed, `backup_saves` creates a hashed save backup. Launch an owned
development session, load that save through observed native menus, and use
`capture_trace` to collect at least three advancing loaded-world samples. Stop
the owned session, then call `create_gameplay_checkpoint(backup_id, trace_id,
label)`. Registration checks the current save against the backup and verifies
the native trace's build, world and evidence class.

`launch_gameplay_checkpoint(checkpoint_id)` restores the registered save through
the existing journaled transaction, retaining an undo backup, and starts an owned
game. Poll `job_status` for its session and save receipt. The AI client navigates
the observed **Load Game** menu. The MCP does not send blind confirmation keys or
invoke an unknown native save-loading function.

Call `run_gameplay_harness(checkpoint_id, recipe="observe_idle", seconds=2)` after
menu navigation. `neutral_input` is the other supported recipe. Readiness requires
three consecutive advancing actor samples, the registered stage and nearby P1
position, healthy offline transport, no menu gate and no faults. Frozen cached
flags cannot pass. Readiness waits 1–120 seconds and scenarios run 0.5–30 seconds.
The default stops the owned game after capture. `stop_after=false` retains it for
another explicit operation. Partial evidence survives cancellation or failure.

A checkpoint identifies a save inventory plus stage/position; it does not prove
full quest state or bind a trace to a native save event. Shared-life reserve is
outside `.sav` backups. Standalone launch retains the restore's undo receipt;
restore that backup explicitly when finished if the original save differed.

## 2. Broader copied diagnostics

`runtime_snapshot(group=...)` now supports these six additional groups. Their
schemas also work with `decode_diagnostic` and `replay_diagnostic`.

| Group | Copied information | Limits |
| --- | --- | --- |
| `pawn_resources` | Main-pawn HUD HP, stamina and render/sample counters | Hidden HUD values are unavailable; no P1 vitals |
| `pawn_vocation` | Cached vocation, age, freshness and policy | No complete AI decision history |
| `pawn_actions` | Generic action handoff/completion/cleanup counters | No full action graph |
| `inventory_menu` | Menu lifecycle, world generation, neutralization and returns | No item inventory or quest flags |
| `shared_life` | Reserve policy, down/revival masks and lifecycle counters | No complete combat event stream |
| `target_hud` | Ingle target validity and copied coordinates | No enemy identity or damage attribution |

The nine-adapter catalog includes the earlier runtime, performance and death
readers. Every reader checks its exact ABI size/version and byte-versus-word
argument convention. Nonfinite floats are refused, 64-bit counters remain exact
decimal strings, and pointers never cross the adapter. Sequential reads are not
an atomic world snapshot. New schemas require deliberate contract review and
native acceptance; supplied offline data remains offline evidence.

## 3. Reviewed tracing with code references

`list_function_traces` returns two reviewed observers with exact signatures,
source commit/blob references and evidence limits. `trace_function(symbol,
seconds=2, decompile=false)` accepts `native_stamina_apply` or
`goblin_health_subtract`, for 0.1–30 seconds. Set `decompile=true` to link a Ghidra
export from the existing hash-matched local database to the capture.

Tracing requires an owned healthy loaded developer session. Changed or already
hooked function prefixes are refused. Only reviewed native callbacks read actor
state: validated party ownership for stamina and validated goblin/hobgoblin life
membership for health subtraction. RPCs and timers do not inspect actor pointers.
Callbacks never modify arguments, resources or control flow. Output is capped at
256 events and reports omissions. Hook removal, callback completion and prefix
restoration are verified; failed cleanup stops the owned process. A failed start
cannot reuse a previous trace's rows.

Stamina events are not complete vitals. Health events do not establish attacker
attribution. Zero captured health events demonstrate neither combat correctness
nor that the function is unused. Adding another trace requires reviewed ownership,
calling convention, signature, output bounds and cleanup tests.

## 4. Persistent investigation memory

Use `record_investigation_note` for hypotheses, findings, failed attempts and open
questions. Attach artifact IDs and pinned source paths. Findings and supported
hypotheses require evidence references. `search_investigations` searches latest
revisions; `read_investigation_note` reads current or historical revisions and
checks evidence hashes. Update with `note_id` and `expected_revision` to prevent
concurrent overwrites. Prior versions remain immutable artifacts.

The private SQLite index and evidence artifacts survive server restarts. Limits:
160-character titles, 4,000-character bodies, 16 references of each kind and
10,000 revisions. Notes are authored claims, not instructions or automatic proof;
referenced evidence retains its original scope. Future agents should search this
history before repeating an investigation and read the cited evidence before
treating a finding as established.

## 5. Repeated regression isolation

Call `create_regression_campaign(checkpoint_id, revisions, repeats=2)` with 2–16
distinct, full commit SHAs in ancestor order and two or three trials per revision.
The initial predicate is advancing idle gameplay at the registered checkpoint,
healthy offline transport and zero faults.

1. `advance_regression_campaign(campaign_id, action="prepare")` builds and tests
   the selected immutable revision in isolation, verifies output hashes, backs up
   current saves and temporarily deploys the candidate. Its settings use that
   revision's defaults plus supported current keys, with offline/developer mode
   forced. Omitted newer settings are recorded in the trial.
2. Poll the job until `awaiting_world`, then load the save through observed menus.
   Keep the originating MCP server alive; it owns the process and the campaign.
3. Call `advance_regression_campaign(..., action="evaluate")`. It waits for
   readiness, observes two seconds, stops the owned game, rolls back deployment
   and restores the pretrial saves. Shared-life changes make the trial inconclusive.
4. Read `regression_campaign_status`, then repeat preparation/evaluation while
   state is `ready`. Endpoints are repeated before midpoint selection. Mixed or
   inconclusive results halt classification rather than becoming a bad commit.

`action="abort"` recovers the active trial and retains the journal. After a server
crash, inspect session/save recovery status and abort the interrupted campaign
before starting another. Cleanup refuses an unrelated active process/session.
Cancellation waits for the current journaled operation to finish before rollback;
this can include a build or readiness timeout. It cannot abandon a save/deployment
thread midway. Hard process termination still relies on durable recovery receipts.

A completed campaign identifies a boundary among selected commits under the
tested predicate and a monotonicity assumption. It does not prove causality,
isolate omitted commits, or test combat. This release has native acceptance for
one historical idle trial and rollback, plus synthetic repeated bisection tests;
no real known-good/known-bad gameplay boundary has been isolated yet.

## Validation and local smoke

See [validation](VALIDATION.md) for native receipts and remaining gates. The
opt-in `scripts/expanded_native_smoke.py --checkpoint <id> --candidate <name>`
temporarily deploys a trusted named candidate, launches the checkpoint, waits for
client menu navigation, reads all six groups, runs both traces and neutral input,
then restores deployment and pretrial saves. It requires a closed game and
explicit configured save roots. Its report stays in `private/`.

The ordinary pytest suite and `scripts/smoke.py` do not launch the game. Native
acceptance is separate from synthetic ABI tests and transport checks.
