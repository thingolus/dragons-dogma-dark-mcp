import asyncio
import copy
import json
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from test_death import ring
from test_operations import FakeSession

from ddda_mcp.artifacts import Artifacts
from ddda_mcp.common import ToolFailure, atomic_json
from ddda_mcp.diagnostics import Adapter, Copied, Diagnostics, U64Text, decode, differences
from ddda_mcp.timeline import Timelines


def runtime(**changes):
    values = dict(
        size=132,
        version=2,
        runtime=2,
        p1=0,
        p2=1,
        session=1,
        transport=2,
        native_offline=1,
        native_errors=0,
        faults=0,
        stage=220,
        generation=1,
        physical_mask=0,
        developer_input=1,
        menu_gated=0,
        guard_transport=2,
        actors=[
            dict(observed=1, action=3, movement=0, held=0, frames=4, position=[1.0, 2.0, 3.0], angle=0.0)
            for _ in range(2)
        ],
    )
    return {**values, **changes}


def performance(**changes):
    values = dict(
        size=2448,
        version=1,
        state=1,
        coverage_mask=3,
        **{
            key: "0"
            for key in (
                "frequency",
                "admitted_roots",
                "completed_roots",
                "active_roots",
                "clock_failures",
                "start_failures",
            )
        },
    )
    return {**values, **changes}


def provenance(**changes):
    return {
        "session_id": "s1",
        "game_sha256": "g1",
        "runtime_sha256": "r1",
        "evidence_class": "synthetic_native",
        **changes,
    }


def trace(artifacts, samples, identity=None, **summary):
    return artifacts.put(
        "runtime_trace",
        {"samples": samples, "summary": {"outcome": "completed", **summary}},
        provenance() if identity is None else identity,
    )["artifact_id"]


def stamped(second=0, **changes):
    return runtime(captured_at=f"2026-10-23T10:00:{second:02d}+00:00", **changes)


def test_registry_redacts_and_does_not_mutate_inputs(config):
    service = Diagnostics(Artifacts(config))
    assert len(service.catalog()["adapters"]) == 3
    for name, payload in (
        ("runtime", runtime()),
        ("performance", performance()),
        ("death_refusals", {"words": ring()}),
    ):
        payload["caller_pointer"] = "PRIVATE_ADDRESS"
        original = copy.deepcopy(payload)
        result = service.save(name, payload)
        doc = service.artifacts.get(result["artifact_id"])
        assert payload == original
        assert "PRIVATE_ADDRESS" not in json.dumps(doc)
        assert str(0xDECAFBAD) not in json.dumps(doc)
        assert doc["provenance"]["evidence_class"] == "offline_supplied"
        assert service.replay(result["artifact_id"])["summary"]["matches_recorded_decode"]


def test_future_adapter_uses_shared_validation_without_name_switches():
    class FutureCopied(Copied):
        size: int
        version: int
        events: U64Text

    adapter = Adapter("future_fixture", "FixtureExport", 16, 7, "synthetic.hpp", FutureCopied)
    clean, decoded = adapter.decode({"size": 16, "version": 7, "events": "9007199254740993", "address": 123})
    assert clean == decoded["values"] == {"size": 16, "version": 7, "events": "9007199254740993"}
    with pytest.raises(ToolFailure):
        adapter.decode({"size": 16, "version": 7, "events": str(2**64)})
    words = Adapter(
        "future_words",
        "FixtureExport",
        16,
        7,
        "synthetic.hpp",
        word_decoder=lambda values: {"copied": values},
        word_count=4,
        redacted_indices=(2,),
    )
    clean, decoded = words.decode({"words": [16, 7, 123456, 42]})
    assert clean["words"] == decoded["copied"] == [16, 7, 0, 42]
    assert words.describe()["payload_schema"]["properties"]["words"]["maxItems"] == 4


@pytest.mark.parametrize(
    "adapter,payload,code",
    [
        ("unknown", {}, "diagnostic_unavailable"),
        ("runtime", runtime(version=3), "abi_mismatch"),
        ("performance", performance(version=True), "abi_mismatch"),
        ("runtime", runtime(faults=True), "invalid_diagnostic"),
        ("runtime", runtime(actors=[]), "invalid_diagnostic"),
        (
            "runtime",
            runtime(actors=[{**runtime()["actors"][0], "angle": float("nan")}] * 2),
            "invalid_diagnostic",
        ),
        ("performance", {**performance(), "frequency": str(2**64)}, "invalid_diagnostic"),
        ("performance", {**performance(), "frequency": 42}, "invalid_diagnostic"),
        ("performance", {**performance(), "frequency": "001"}, "invalid_diagnostic"),
    ],
)
def test_adapter_validation(adapter, payload, code):
    with pytest.raises(ToolFailure) as failure:
        decode(adapter, payload)
    assert failure.value.code == code


def test_replay_detects_decoder_regression_and_payload_tampering(config):
    artifacts = Artifacts(config)
    service = Diagnostics(artifacts)
    saved = service.save("runtime", runtime())["artifact_id"]
    doc = artifacts.get(saved)
    doc["data"]["decoded"]["values"]["stage"] = 999
    atomic_json(artifacts.path(saved), doc)
    result = service.replay(saved)
    assert not result["summary"]["matches_recorded_decode"]
    assert result["differences"]["changes"][0]["path"] == "/values/stage"
    doc["data"]["payload"]["stage"] = 998
    atomic_json(artifacts.path(saved), doc)
    with pytest.raises(ToolFailure, match="hash"):
        service.replay(saved)


def test_legacy_death_artifact_replays_without_new_metadata(config):
    artifacts = Artifacts(config)
    result = decode("death_refusals", {"words": ring()})
    saved = artifacts.put(
        "death_diagnostic", {"words": result["payload"]["words"], "decoded": result["decoded"]}, {}
    )
    assert Diagnostics(artifacts).replay(saved["artifact_id"])["summary"]["matches_recorded_decode"]


def test_performance_owned_capture_uses_registry_and_never_inputs(development):
    async def run():
        session = FakeSession(development)
        original = session._request

        async def request(operation, **parameters):
            if operation == "performance":
                session.calls.append((operation, parameters))
                return performance()
            return await original(operation, **parameters)

        session._request = request
        result = await session.snapshot("performance")
        assert Diagnostics(session.artifacts).replay(result["artifact_id"])["summary"][
            "matches_recorded_decode"
        ]
        assert [op for op, _ in session.calls] == ["snapshot", "performance"]

    asyncio.run(run())


def test_timeline_rules_filter_pagination_and_exact_replay(config):
    artifacts = Artifacts(config)
    service = Timelines(artifacts)
    first, second = stamped(), stamped(1, faults=1, menu_gated=1)
    second["actors"][1]["action"] = 17
    saved = trace(artifacts, [first, second], outcome="cancelled", input_released=False)
    receipt = service.build([saved])
    data = service.get(receipt["artifact_id"])
    assert {f["rule"] for f in data["findings"]} == {
        "state_changed",
        "actor_changed",
        "runtime_fault_observed",
        "incomplete_capture",
    }
    page = service.query(receipt["artifact_id"], kind="runtime", limit=1)
    assert page["total_matches"] == 2 and page["next_offset"] == 1
    assert (
        service.query(receipt["artifact_id"], kind="runtime", offset=1)["events"][0]["details"]["faults"] == 1
    )
    replay = service.replay(receipt["artifact_id"])["summary"]
    assert replay["matches_recorded_events"] and replay["matches_recorded_findings"]
    doc = artifacts.get(saved)
    doc["data"]["samples"][1]["faults"] = 2
    atomic_json(artifacts.path(saved), doc)
    with pytest.raises(ToolFailure, match="changed"):
        service.replay(receipt["artifact_id"])


@pytest.mark.parametrize(
    "change",
    [
        {"session_id": "other"},
        {"runtime_sha256": "other"},
        {"game_sha256": "other"},
        {"evidence_class": "native_observation"},
        {"session_id": None},
    ],
)
def test_distinct_or_unknown_identities_never_imply_state_change(config, change):
    artifacts = Artifacts(config)
    data = Timelines(artifacts).collect(
        [
            trace(artifacts, [stamped()]),
            trace(artifacts, [stamped(1, stage=999)], provenance(**change)),
        ]
    )
    assert not data["findings"]
    assert data["summary"]["streams"] == 2


def test_cross_capture_known_session_correlation(config):
    artifacts = Artifacts(config)
    data = Timelines(artifacts).collect(
        [trace(artifacts, [stamped()]), trace(artifacts, [stamped(1, stage=999)])]
    )
    assert [f["rule"] for f in data["findings"]] == ["state_changed"]


def test_equal_time_conflicting_captures_do_not_establish_order(config):
    artifacts = Artifacts(config)
    data = Timelines(artifacts).collect(
        [trace(artifacts, [stamped()]), trace(artifacts, [stamped(stage=999), stamped(1, stage=888)])]
    )
    assert [f["rule"] for f in data["findings"]] == ["ambiguous_sample_order"]


def test_bounded_difference_paths_and_truncation():
    assert differences({"a/b": 1}, {"a/b": 2})["changes"][0]["path"] == "/a~1b"
    assert differences([], list(range(30)))["truncated"]
    assert len(differences([], list(range(30)))["changes"]) == 25


def test_replay_exposes_rule_regression(config):
    artifacts = Artifacts(config)
    service = Timelines(artifacts)
    saved = service.build([trace(artifacts, [stamped(), stamped(1, faults=1)])])["artifact_id"]
    doc = artifacts.get(saved)
    doc["data"]["findings"] = []
    atomic_json(artifacts.path(saved), doc)
    result = service.replay(saved)
    assert not result["summary"]["matches_recorded_findings"]
    assert result["summary"]["matches_recorded_events"]
    assert result["differences"]["changes"][0]["path"] == "/findings/0"


def test_unobserved_actor_and_world_change_not_compared_as_actions(config):
    artifacts = Artifacts(config)
    first, second, third = stamped(), stamped(1), stamped(2, generation=2)
    first["actors"][0]["observed"] = second["actors"][0]["observed"] = 0
    second["actors"][0]["action"] = 999
    third["actors"][1]["action"] = 998
    data = Timelines(artifacts).collect([trace(artifacts, [first, second, third])])
    assert [f["rule"] for f in data["findings"]] == ["state_changed"]


def test_death_overlap_preserves_exact_ticks_and_saturated_duplicates(config):
    artifacts = Artifacts(config)
    words = ring(8, serial=2**64 - 1)
    # All eight retained rows can be identical after counter saturation.
    row = words[8 + 7 * 64 : 8 + 8 * 64]
    row[5:9] = [17, 2**22, 18, 2**22]
    for i in range(8):
        words[8 + i * 64 : 8 + (i + 1) * 64] = row
    result = decode("death_refusals", {"words": words})
    ids = [
        artifacts.put(
            "death_diagnostic",
            {"words": result["payload"]["words"], "decoded": result["decoded"]},
            {"session": provenance(), "evidence_class": "synthetic_native"},
        )["artifact_id"]
        for _ in range(2)
    ]
    service = Timelines(artifacts)
    saved = service.build(ids)
    page = service.query(saved["artifact_id"], kind="death_refusal", actor="main_pawn", text="Revival")
    assert page["total_matches"] == 8
    assert all(len(e["sources"]) == 2 for e in page["events"])
    assert page["events"][0]["time"] == str(2**54 + 18)
    assert service.get(saved["artifact_id"])["summary"]["streams"] == 2


def test_performance_failures_and_offline_timestamp_scope(config):
    artifacts = Artifacts(config)
    saved = Diagnostics(artifacts).save(
        "performance", {**performance(), "clock_failures": "9007199254740993"}
    )
    data = Timelines(artifacts).collect([saved["artifact_id"]])
    assert data["events"][0]["clock"] == "utc_artifact"
    assert data["findings"][0]["details"]["value"] == "9007199254740993"


def test_legacy_missing_timestamps_and_bad_clock_refusal(config):
    artifacts = Artifacts(config)
    service = Timelines(artifacts)
    data = service.collect([trace(artifacts, [runtime(), runtime(stage=1)])])
    assert {e["clock"] for e in data["events"]} == {"ordinal", "utc_capture"}
    with pytest.raises(ToolFailure, match="backward"):
        service.collect([trace(artifacts, [stamped(1), stamped()])])
    with pytest.raises(ToolFailure, match="timestamp"):
        service.collect([trace(artifacts, [runtime(captured_at="2026-10-23T10:00:00")])])


def test_bounds_and_unsupported_evidence(config, monkeypatch):
    artifacts = Artifacts(config)
    service = Timelines(artifacts)
    saved = trace(artifacts, [stamped(), stamped(1)])
    for ids in ([], [saved] * 2, [saved] * 17):
        with pytest.raises(ToolFailure):
            service.collect(ids)
    unrelated = artifacts.put("build", {"summary": {}}, {})["artifact_id"]
    with pytest.raises(ToolFailure, match="supports"):
        service.collect([unrelated])
    monkeypatch.setattr("ddda_mcp.timeline.MAX_EVENTS", 1)
    with pytest.raises(ToolFailure):
        service.collect([saved])


def test_all_new_workflows_over_actual_stdio(config):
    atomic_json(config.root / "config/local.json", config.settings.model_dump())

    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "ddda_mcp", "--project", str(config.root)]
        )
        async with Client(params, read_timeout_seconds=30) as client:

            async def call(name, **args):
                result = await client.call_tool(name, args)
                assert not result.is_error, result.structured_content
                return result.structured_content["data"]

            catalog = await call("list_diagnostic_adapters")
            if catalog.get("inline_truncated"):
                catalog = Artifacts(config).get(catalog["artifact_id"])["data"]["result"]["data"]
            assert len(catalog["adapters"]) == 3
            decoded = await call("decode_diagnostic", adapter="death_refusals", payload={"words": ring()})
            assert (await call("replay_diagnostic", artifact_id=decoded["artifact_id"]))["summary"][
                "matches_recorded_decode"
            ]
            timeline = await call("build_event_timeline", artifact_ids=[decoded["artifact_id"]])
            assert (
                await call("query_event_timeline", artifact_id=timeline["artifact_id"], kind="death_refusal")
            )["total_matches"] == 1
            assert (await call("replay_event_timeline", artifact_id=timeline["artifact_id"]))["summary"][
                "matches_recorded_findings"
            ]
            feature = await call("investigate_feature", feature="pawn ownership")
            assert "pawn_movement_consume" in feature["leading_symbols"]
            assert feature["summary"]["native_acceptance"] == "unverified"

    asyncio.run(run())
