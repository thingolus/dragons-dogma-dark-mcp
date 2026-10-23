# Diagnostic adapters, timelines and feature investigations

Version 0.6.0 by Thingolus adds seven tools, bringing the catalog to 39. These workflows run without gameplay or a development profile. They save private evidence artifacts; they do not modify the game or the co-op source checkout. The existing native ownership, deployment and offline gates remain in force.

## Reviewed diagnostic adapters

`list_diagnostic_adapters()` returns the input schemas, ABI sizes/versions, native export names, decoder versions and live requirements for three adapters:

| Adapter | Input | Native ABI | Scope |
| --- | --- | --- | --- |
| `runtime` | Copied status fields and two actor records | 132 bytes / version 2 | Runtime, assignments, world, actor observations |
| `performance` | Copied fields with decimal-string counters | 2448 bytes / version 1 | Existing callback instrumentation counters |
| `death_refusals` | `{"words": [520 unsigned integers]}` | 2080 bytes / version 1 | Last eight recorded down/refusal rows |

Call `decode_diagnostic(adapter, payload)` to validate supplied copied values and save a `diagnostic_capture`. The result includes a receipt, decoder version, redacted payload hash and decoded values. Supplied payloads always receive `offline_supplied` evidence classification; callers cannot promote them to native observations by supplying metadata. Undeclared object fields are discarded. Invalid integers, booleans in integer fields, nonfinite actor floats and overflowing counters are rejected. Death-ring pointer columns are zeroed before storage, in addition to existing native-side redaction before RPC.

`replay_diagnostic(artifact_id)` runs the current decoder against the retained payload, verifies its hash and compares the result with the original decode. It returns `matches_recorded_decode`, both decoder versions and up to 25 changed JSON paths. A mismatch is a regression signal for review, not necessarily a decoder bug: a deliberate semantic correction can change the expected output. Original artifacts are never overwritten. Existing v0.5 `death_diagnostic` artifacts remain readable; legacy captures without a stored payload hash cannot independently establish their original integrity.

Live `runtime_snapshot(group="death_refusals")` uses this adapter layer and keeps the existing response and artifact kind. `runtime_snapshot(group="performance")` now also retains a replayable diagnostic artifact while preserving its runtime/performance response. Both still require an owned guarded development session. The runtime adapter also validates archived trace samples during offline timeline construction. No new native export, hook, timer or game-memory reader is introduced.

### Adding a future adapter

1. Establish the native field meanings and supported build. Record the authoritative ABI source and upstream compatibility contract.
2. Add a strict copied-value schema and an `Adapter` entry in `diagnostics.py`. Declare ABI size/version and decoder version. Keep 64-bit counters as decimal strings, missing observations distinct from zero, and unknown predicates distinct from false.
3. If new live data is required, add a reviewed allowlisted native reader and broker operation. Strip pointers inside the native boundary before RPC. Preserve ownership, offline, thread/callback and readiness requirements; the catalog alone cannot authorize a read.
4. Add synthetic fixtures for valid data, malformed layouts, overflow, absent exports, partial observations and redaction. Route capture persistence through the common decoder.
5. Add a timeline projection only when its timestamp domain and event meaning are established. Add a rule version when rule semantics change and replay older evidence before adopting new expectations.
6. Record native acceptance separately when the game observation has actually been verified.

This is an internal reviewed-code extension point, not a dynamic plugin loader. Arbitrary scripts, functions, addresses and memory writes are not MCP inputs.

## Event timelines and regression replay

`build_event_timeline(artifact_ids)` accepts 1–16 distinct artifacts of these kinds:

- `runtime_trace`, `movement_trace`, `title_start`
- `death_diagnostic`, `diagnostic_capture`

It emits an `event_timeline` with source document hashes, normalized copied values, stream identities, rule findings and original artifact/row references. At most 10,000 events are admitted. Overflow is refused rather than silently truncating the timeline; the configured artifact byte limit applies too.

Example tool sequence, using actual returned IDs in place of the placeholders:

```text
build_event_timeline(artifact_ids=["<runtime-trace-id>", "<death-capture-id>"])
query_event_timeline(artifact_id="<timeline-id>", kind="death_refusal", actor="Arisen")
query_event_timeline(artifact_id="<timeline-id>", text="revival", offset=0, limit=25)
replay_event_timeline(artifact_id="<timeline-id>")
```

Queries filter by exact event kind, exact actor or case-insensitive literal text in event details. Actor filtering applies to actor-tagged refusal events; runtime events contain both actor records. Pagination returns a total match count and next offset. Findings for the returned events accompany the page; `read_artifact` exposes the complete report.

Rules currently identify state/assignment/menu changes, observed actor action/input-state changes, nonzero native fault/error observations, performance failures, revival refusals, overwritten refusal history and incomplete capture/cleanup outcomes. Actor actions are compared only when both actor observations are available in the same stage and generation. Equal-time conflicting samples from separate captures are marked ambiguous rather than used to infer a transition. Recipe metadata records requested input and cleanup, not confirmed movement or physical-controller input.

### Time and evidence limits

Events are ordered within compatible streams, not across the entire timeline:

- `utc_capture`: host capture timestamps; not exact native event time.
- `native_tick_ms`: exact decimal-string refusal recorder ticks; not UTC.
- `ordinal`: original order for legacy samples lacking timestamps; local to that artifact.
- `utc_artifact`: when supplied offline values were saved; their observation time is unknown.

Cross-capture correlation requires a known matching session ID, executable hash, runtime hash, evidence class and clock. Missing identities remain separate. Clock regression within a timestamped trace is refused. Exact overlapping refusal rows across captures are deduplicated with all source references retained, while identical rows within one saturated ring remain separate. Polling can miss intermediate events; proximity and refusal records do not establish Game Over causality.

`replay_event_timeline` reloads the original inputs, requires unchanged source document hashes, applies current decoders/rules, and compares normalized events and findings. It retains a new replay artifact, both rule versions and bounded difference paths. `matches_recorded_events` and `matches_recorded_findings` must both be true for an unchanged replay. This replays observations, not game simulation. A deleted or edited source artifact prevents a valid comparison.

## Feature investigation and change-impact candidates

`investigate_feature(feature, terms=None)` gathers a report from the pinned immutable source. For example:

```text
investigate_feature(feature="shared inventory", terms=["inventory", "pickup"])
investigate_feature(feature="pawn commands", terms=["pawn", "command"])
investigate_feature(feature="shared-life revival", terms=["shared_life", "revival"])
```

When terms are omitted, up to eight nontrivial words are extracted from the feature description. Explicit terms improve focus and can include phrases. These are lexical searches, not semantic interpretation of arbitrary feature requests.

The saved report includes:

- Ranked known-symbol candidates with source references and ready-to-use `investigate_symbol` arguments.
- Related research passages with their original evidence limitations and immutable source links.
- Candidate implementation/test files, matching terms, line excerpts and Git blob identities.
- Quoted-include dependencies involving selected candidates, including incoming references. Include resolution is a source-path heuristic, not compiler configuration or a verified call graph.
- Candidate test files, evidence gaps and suggested static, offline, build and native validation stages. Test-name matches do not prove coverage.

The scan admits at most 1,000 source files / 16 MiB, with a 2 MiB per-file bound. It returns at most 60 source candidates, 20 symbols, 20 research passages, 100 dependency edges and 30 test paths. Each file has up to three matching excerpts. Reports state omitted counts and whether research search has more results. Source is read from Git objects; dirty files are excluded. Nothing executes from the co-op checkout and no automatic baseline update occurs.

For narrower implementation details, follow the report's symbol investigations and read the cited source passages. Feature reports identify likely starting points and uncertainty; they do not assert feasibility or generate unverified game APIs.

## Verification

Run the normal suite plus the real-project read-only workflow smoke:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests scripts
.venv/Scripts/python.exe scripts/future_workflows_smoke.py
```

The smoke creates synthetic diagnostic/replay artifacts, exercises all seven new tools over actual MCP stdio, and investigates three features against the configured pinned co-op source. Its report is kept under ignored `artifacts/validation/future-workflows-smoke.json`. Hosted CI exercises equivalent synthetic fixture workflows without private co-op credentials. Game observations and new native feature acceptance remain separate.
