"""Synthetic offline tapes only. No game process, native memory or desktop access."""

import asyncio
import copy
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from pydantic import ValidationError

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.experiments import Condition, ExperimentPlan, Experiments, check_condition, replay
from ddda_mcp.gameplay_data import Command, GameplayRecording
from ddda_mcp.gameplay_events import GameplayRecordings, derive_events
from ddda_mcp.sdk_contracts import catalog, header, schemas


def actor(role=0, hp=100.0, quantity=1):
    return {
        "entity": {"key": f"party-{role}", "scope": "session", "epoch": "synthetic-one", "incarnation": 1},
        "role": role,
        "kind": "party",
        "hp": hp,
        "hp_max": 200.0,
        "position": [float(role), 0.0, 0.0],
        "action": 0,
        "inventory": {
            "complete": True,
            "items": [{"item_id": 7, "quantity": quantity}, {"item_id": 43, "quantity": 2}],
        },
    }


def fixture(kind="healing"):
    a, b = actor(), actor(1, 0.0)
    command = {
        "action": {
            "combat": "light_attack",
            "healing": "use_item",
            "revival": "interact_target",
            "loot": "interact",
        }[kind]
    }
    if kind == "healing":
        command["item_id"] = 43
    if kind == "revival":
        command["target"] = b["entity"]
    initial = {
        "sequence": 0,
        "elapsed_ms": 0,
        "stage": 220,
        "generation": 1,
        "complete": True,
        "menu_open": False,
        "actors": [a, b],
    }
    end = copy.deepcopy(initial)
    end.update(sequence=1, elapsed_ms=350)
    if kind == "combat":
        end["actors"][0]["hp"] = 90.0
    elif kind == "healing":
        end["actors"][0]["hp"] = 150.0
        end["actors"][0]["inventory"]["items"][1]["quantity"] = 1
    elif kind == "revival":
        end["actors"][1]["hp"] = 30.0
    else:
        end["actors"][0]["inventory"]["items"][0]["quantity"] = 2
    goal = {"kind": kind, "subject": {"role": 1 if kind == "revival" else 0}}
    if kind == "loot":
        goal["item_id"] = 7
    plan = {
        "label": "Synthetic " + kind,
        "goal": goal,
        "steps": [
            {"kind": "require", "condition": {"predicate": "menu_closed"}},
            {"kind": "action", "command": command},
            {"kind": "wait"},
        ],
    }
    recording = {
        "label": "Synthetic " + kind,
        "identity": {
            "session": "synthetic-one",
            "clock": "fixture-clock",
            "game_sha256": "a" * 64,
            "source_commit": "b" * 40,
            "backend": "synthetic",
        },
        "frames": [initial, end],
        "actions": [{"command": command, "before_sequence": 0, "after_sequence": 1, "outcome": "accepted"}],
        "cleanup": {"input_released": True, "observers_sealed": True, "restoration": "not_applicable"},
    }
    return plan, recording


def run(plan, recording):
    return replay(ExperimentPlan.model_validate(plan), GameplayRecording.model_validate(recording))


@pytest.mark.parametrize("kind", ["combat", "healing", "revival", "loot"])
def test_real_executor_replays_all_four_goal_types_without_game_access(kind, monkeypatch):
    # A stronger separation than simply mocking a game: the engine owns no game
    # backend. Trips on accidental future calls even if one gets introduced.
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("Process launch in replay"))
    report = run(*fixture(kind))
    assert report["summary"]["outcome"] == "passed"
    assert report["summary"]["native_acceptance"] == "unverified"
    assert report["summary"]["metrics"]["model_tokens"] is None
    assert report["summary"]["metrics"]["actions_matched"] == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        ("generation", "world_changed"),
        ("stage", "world_changed"),
        ("omitted", "incomplete_observation"),
        ("complete", "incomplete_observation"),
        ("epoch", "entity_lifetime_changed"),
        ("incarnation", "entity_lifetime_changed"),
        ("scope", "entity_lifetime_changed"),
        ("missing_actor", "subject_unavailable"),
        ("sequence", "sequence_gap"),
        ("elapsed_ms", "sampling_gap"),
    ],
)
def test_positive_hp_does_not_hide_identity_and_capture_failures(change, reason):
    plan, recording = fixture()
    frame = recording["frames"][1]
    if change == "complete":
        frame[change] = False
    elif change == "missing_actor":
        frame["actors"] = []
    elif change in {"epoch", "incarnation", "scope"}:
        frame["actors"][0]["entity"][change] = {"epoch": "different", "incarnation": 2, "scope": "capture"}[
            change
        ]
    elif change == "sequence":
        frame[change] = 2
        recording["actions"][0]["after_sequence"] = 2
    else:
        frame[change] = {"generation": 2, "stage": 702, "omitted": 1, "elapsed_ms": 3000}[change]
    report = run(plan, recording)
    assert report["summary"]["outcome"] == "inconclusive"
    assert report["summary"]["reason"] == reason


@pytest.mark.parametrize("terminal", ["cancelled", "timeout", "failed", "outcome_unknown"])
def test_interrupted_recordings_never_report_pass(terminal):
    plan, recording = fixture()
    recording["terminal"] = terminal
    report = run(plan, recording)
    assert report["summary"]["outcome"] == "inconclusive"
    assert report["summary"]["reason"] == "recording_" + terminal
    assert report["summary"]["measurement"]["passed"] is True  # Retain partial evidence.


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_released", False),
        ("observers_sealed", None),
        ("restoration", "unknown"),
        ("restoration", "failed"),
    ],
)
def test_cleanup_prevents_false_pass(field, value):
    plan, recording = fixture()
    recording["cleanup"][field] = value
    assert run(plan, recording)["summary"]["reason"] == "recorded_cleanup_unverified"


@pytest.mark.parametrize(
    "change,reason",
    [
        ("command", "recorded_action_mismatch"),
        ("duration", "recorded_action_mismatch"),
        ("refused", "command_refused"),
        ("unknown", "command_unknown"),
        ("missing", "recorded_action_missing"),
        ("short", "action_observation_too_short"),
    ],
)
def test_actions_are_matched_exactly_and_never_retried(change, reason):
    plan, recording = fixture("combat")
    # Unshare the dictionaries so the recording change cannot alter the plan.
    recording = copy.deepcopy(recording)
    if change == "command":
        recording["actions"][0]["command"]["action"] = "heavy_attack"
    elif change == "duration":
        recording["actions"][0]["command"]["duration_ms"] = 100
    elif change == "missing":
        recording["actions"] = []
    elif change == "short":
        recording["frames"][1]["elapsed_ms"] = 100
    else:
        recording["actions"][0]["outcome"] = change
    report = run(plan, recording)
    assert report["summary"]["reason"] == reason
    assert report["summary"]["metrics"]["actions_matched"] == 0


def test_wait_only_consumes_observations_and_distinguishes_short_tape_from_failed_deadline():
    plan, recording = fixture()
    plan["steps"] = [{"kind": "wait", "timeout_ms": 500}]
    recording["actions"] = []
    assert run(plan, recording)["summary"]["outcome"] == "passed"
    recording["frames"][1]["actors"][0]["hp"] = 100.0
    assert run(plan, recording)["summary"]["reason"] == "recording_ended_before_deadline"
    recording["frames"][1]["elapsed_ms"] = 500
    assert run(plan, recording)["summary"]["outcome"] == "failed"
    assert run(plan, recording)["summary"]["reason"] == "wait_deadline_exceeded"


def test_wait_cannot_attribute_an_unplanned_action_to_observation():
    plan, recording = fixture()
    plan["steps"] = [{"kind": "wait"}]
    assert run(plan, recording)["summary"]["reason"] == "unplanned_action_during_wait"


def test_unknown_inventory_is_not_zero_and_revival_needs_zero_initial_hp():
    plan, recording = fixture("loot")
    recording["frames"][0]["actors"][0]["inventory"]["complete"] = False
    assert run(plan, recording)["summary"]["outcome"] == "inconclusive"
    plan, recording = fixture("revival")
    recording["frames"][0]["actors"][1]["hp"] = 1.0
    assert run(plan, recording)["summary"]["reason"] == "goal_precondition_unmet"


def test_target_distance_and_command_identity_are_explicit():
    plan, recording = fixture("revival")
    condition = Condition.model_validate(
        {
            "predicate": "within_distance",
            "threshold": 2.0,
            "subject": {"role": 0},
            "target": recording["frames"][0]["actors"][1]["entity"],
        }
    )
    frame = GameplayRecording.model_validate(recording).frames[0]
    assert check_condition(condition, frame)[0] is True
    condition.target.incarnation += 1
    assert check_condition(condition, frame)[0] is None
    plan = copy.deepcopy(plan)
    plan["steps"][1]["command"]["target"]["incarnation"] = 99
    assert run(plan, recording)["summary"]["reason"] == "target_identity_unavailable"

    # Inventory can rise even while the interaction target is replaced. The
    # selected target's lifetime must survive the action as well as P1's.
    plan, recording = fixture("loot")
    command = {"action": "interact_target", "target": recording["frames"][0]["actors"][1]["entity"]}
    plan["steps"][1]["command"] = command
    recording["actions"][0]["command"] = command
    recording["frames"][1]["actors"][1]["entity"]["incarnation"] = 2
    assert run(plan, recording)["summary"]["reason"] == "entity_lifetime_changed"


@pytest.mark.parametrize(
    "change", ["pointer", "nan", "duplicate_role", "duplicate_identity", "time", "bool", "no_incarnation"]
)
def test_recording_schema_refuses_ambiguous_or_unbounded_values(change):
    _, recording = fixture()
    frame = recording["frames"][1]
    if change == "pointer":
        frame["actors"][0]["pointer"] = "0x12345678"
    elif change == "nan":
        frame["actors"][0]["hp"] = float("nan")
    elif change == "duplicate_role":
        frame["actors"][1]["role"] = 0
    elif change == "duplicate_identity":
        frame["actors"][1]["entity"] = frame["actors"][0]["entity"]
    elif change == "time":
        frame["elapsed_ms"] = 0
    elif change == "bool":
        frame["sequence"] = True
    else:
        del frame["actors"][0]["entity"]["incarnation"]
    with pytest.raises(ValidationError):
        GameplayRecording.model_validate(recording)


@pytest.mark.parametrize(
    "change", ["budget", "solo_p2", "unknown_step", "unknown_action", "missing_item", "extra_item"]
)
def test_plan_schema_rejects_invalid_commands_and_budgets(change):
    plan, _ = fixture()
    if change == "budget":
        plan["max_duration_ms"] = 500
    elif change == "solo_p2":
        plan["steps"][1]["command"]["role"] = 1
    elif change == "unknown_step":
        plan["steps"][0]["kind"] = "eval"
    elif change == "unknown_action":
        plan["steps"][1]["command"]["action"] = "native_write"
    elif change == "missing_item":
        del plan["steps"][1]["command"]["item_id"]
    else:
        plan["steps"][1]["command"]["action"] = "interact"
    with pytest.raises(ValidationError):
        ExperimentPlan.model_validate(plan)


def test_event_decoder_preserves_identity_unknowns_and_combines_inventory_stacks():
    _, raw = fixture("healing")
    raw["frames"][0]["actors"][0]["inventory"]["items"] = [
        {"item_id": 43, "quantity": 1},
        {"item_id": 43, "quantity": 1},
        {"item_id": 7, "quantity": 1},
    ]
    decoded = derive_events(GameplayRecording.model_validate(raw))
    assert decoded["summary"]["kinds"] == {"hp_increased": 1, "inventory_delta": 1}
    delta = next(e for e in decoded["events"] if e["kind"] == "inventory_delta")
    assert delta["delta"] == -1 and delta["attribution"] == "unavailable"
    raw["frames"][1]["actors"][0]["entity"]["incarnation"] += 1
    assert derive_events(GameplayRecording.model_validate(raw))["events"] == []


def test_partial_inventory_missing_actor_and_capture_scope_never_infer_changes():
    _, raw = fixture("loot")
    raw["frames"][0]["actors"][0]["inventory"]["complete"] = False
    assert derive_events(GameplayRecording.model_validate(raw))["events"] == []
    raw["frames"][0]["actors"] = []
    assert derive_events(GameplayRecording.model_validate(raw))["events"] == []
    _, raw = fixture("healing")
    for i, frame in enumerate(raw["frames"]):
        frame["actors"][0]["entity"].update(scope="capture", epoch=f"capture-{i}")
    assert derive_events(GameplayRecording.model_validate(raw))["events"] == []


def test_event_overflow_is_bounded_and_counted():
    _, raw = fixture("loot")
    for n, frame in enumerate(raw["frames"]):
        frame["actors"] = []
        for i in range(26):
            a = actor()
            a.pop("role")
            a["kind"] = "registry_actor"
            a["entity"]["key"] = f"actor-{i}"
            a["inventory"]["items"] = [{"item_id": j, "quantity": n + 1} for j in range(256)]
            frame["actors"].append(a)
    decoded = derive_events(GameplayRecording.model_validate(raw))
    assert len(decoded["events"]) == 4096
    assert decoded["omitted_events"] == 26 * 256 - 4096


def test_artifact_integrity_pagination_and_compact_result(config):
    artifacts = Artifacts(config)
    recordings = GameplayRecordings(artifacts)
    experiments = Experiments(artifacts, recordings)
    plan, recording = fixture()
    saved_plan = experiments.create(plan)
    saved = recordings.save(recording)
    page = recordings.query(saved["artifact_id"], limit=1)
    assert len(page["events"]) == 1 and page["next_offset"] == 1
    assert page["matches_recorded_decode"]
    result = experiments.run(saved_plan["artifact_id"], saved["artifact_id"])
    assert result["summary"]["outcome"] == "passed"
    assert result["response_payload_bytes"] < 2048
    assert "steps" not in result
    doc = artifacts.get(saved["artifact_id"])
    doc["data"]["recording"]["frames"][1]["actors"][0]["hp"] = 1.0
    atomic_json(artifacts.path(saved["artifact_id"]), doc)
    with pytest.raises(ToolFailure, match="changed"):
        experiments.run(saved_plan["artifact_id"], saved["artifact_id"])


def test_sdk_contract_extension_preserves_live_capability_limits():
    info = catalog()
    assert not info["native_stream_available"]
    assert not info["backends"]["standalone"]["fixed_input"]
    assert not info["backends"]["coop"]["use_item"]
    assert "Thingolus" in header()
    assert "@FIXED_ACTIONS@" not in header()
    assert schemas()["recording"]["additionalProperties"] is False
    for action in ("neutral", "use_item", "interact_target"):
        assert action in Command.model_json_schema()["properties"]["action"]["enum"]


def test_new_workflows_through_actual_stdio_and_restart(config):
    atomic_json(config.root / "config/local.json", config.settings.model_dump())
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "ddda_mcp", "--project", str(config.root)]
    )

    async def test():
        async with Client(parameters, read_timeout_seconds=20) as client:

            async def call(name, args):
                response = await client.call_tool(name, args)
                assert not response.is_error, response.structured_content
                return response.structured_content["data"]

            assert (await call("experiment_catalog", {}))["execution_backends"] == [
                "offline_replay",
                "native_coop",
            ]
            for kind in ("combat", "healing", "revival", "loot"):
                plan, recording = fixture(kind)
                p = await call("create_experiment_plan", {"plan": plan})
                r = await call("record_gameplay_observations", {"recording": recording})
                result = await call(
                    "replay_gameplay_experiment",
                    {"plan_id": p["artifact_id"], "recording_id": r["artifact_id"]},
                )
                assert result["summary"]["outcome"] == "passed"
                assert result["summary"]["evidence_class"] == "offline_replay"
        async with Client(parameters, read_timeout_seconds=20) as client:
            response = await client.call_tool(
                "query_gameplay_events", {"recording_id": r["artifact_id"], "kind": "inventory_delta"}
            )
            assert response.structured_content["data"]["total"] == 1
            bad = copy.deepcopy(recording)
            bad["frames"][0]["raw_pointer"] = "0x12345678"
            assert (await client.call_tool("record_gameplay_observations", {"recording": bad})).is_error

    asyncio.run(test())
    assert list(config.game.iterdir()) == []
