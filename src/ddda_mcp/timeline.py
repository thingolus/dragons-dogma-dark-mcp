"""Bounded evidence timelines, deterministic rules and replay. MIT, Thingolus."""

import json
from datetime import UTC, datetime

from .common import ToolFailure
from .diagnostics import Diagnostics, decode, differences, fingerprint

RULES_VERSION = 1
MAX_EVENTS = 10000
STATE_FIELDS = ("stage", "generation", "p1", "p2", "menu_gated", "native_offline", "physical_mask")


def utc_stamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ToolFailure("invalid_timeline", "Expected a bounded UTC capture timestamp.")
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError("No timezone")
        return stamp.astimezone(UTC).isoformat()
    except ValueError as exc:
        raise ToolFailure("invalid_timeline", "Invalid capture timestamp.") from exc


class Timelines:
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.diagnostics = Diagnostics(artifacts)

    def collect(self, artifact_ids):
        if not 1 <= len(artifact_ids) <= 16 or len(set(artifact_ids)) != len(artifact_ids):
            raise ToolFailure("invalid_parameters", "Select 1–16 distinct source artifacts.")
        events, inputs, streams, seen = [], [], {}, {}

        def add(doc, clock, stamp, kind, details, index, actor=None):
            provenance = doc["provenance"]
            session = provenance.get("session", provenance)
            # UTC capture order may be correlated only within a known session,
            # executable/runtime identity AND evidence class. Unknowns stay local.
            identity = {key: session.get(key) for key in ("session_id", "game_sha256", "runtime_sha256")}
            identity["evidence_class"] = provenance.get("evidence_class", "unknown")
            identity["clock"] = clock
            if (
                not all(identity.get(key) for key in ("session_id", "game_sha256", "runtime_sha256"))
                or clock == "ordinal"
            ):
                identity["artifact_id"] = doc["id"]
            stream = fingerprint(identity)[:24]
            streams[stream] = identity
            event = {
                "stream": stream,
                "clock": clock,
                "time": str(stamp),
                "kind": kind,
                "actor": actor,
                "details": details,
                "sources": [{"artifact_id": doc["id"], "row": index}],
            }
            # Only deduplicate exact ring rows from overlapping captures; saturated
            # serial values alone are not unique and must never discard evidence.
            signature = fingerprint({k: v for k, v in event.items() if k != "sources"})
            if kind == "death_refusal":
                for existing in seen.get(signature, []):
                    if all(ref["artifact_id"] != doc["id"] for ref in existing["sources"]):
                        existing["sources"].extend(event["sources"])
                        return
            if len(events) >= MAX_EVENTS:
                raise ToolFailure(
                    "timeline_overflow", "Timeline exceeds 10000 events; select fewer captures."
                )
            events.append(event)
            seen.setdefault(signature, []).append(event)

        for artifact_id in artifact_ids:
            doc = self.artifacts.get(artifact_id)
            if not isinstance(doc.get("provenance"), dict) or not isinstance(doc.get("data"), dict):
                raise ToolFailure("invalid_timeline", "Invalid source artifact structure.")
            inputs.append({"artifact_id": artifact_id, "sha256": fingerprint(doc), "kind": doc["kind"]})
            data = doc["data"]
            if doc["kind"] in {"death_diagnostic", "diagnostic_capture"}:
                result = self.diagnostics.normalize_capture(doc)
                capture_clock = (
                    "utc_artifact"
                    if doc["provenance"].get("evidence_class") == "offline_supplied"
                    else "utc_capture"
                )
                if result["adapter"] == "death_refusals":
                    for index, row in enumerate(result["decoded"]["rows"]):
                        add(
                            doc,
                            "native_tick_ms",
                            row["record_poll_tick_ms"],
                            "death_refusal",
                            row,
                            index,
                            row["actor"],
                        )
                    # Retention evidence has capture time, not the native ring clock.
                    add(
                        doc,
                        capture_clock,
                        utc_stamp(doc["created_at"]),
                        "retention",
                        result["decoded"]["summary"],
                        -1,
                    )
                elif result["adapter"] == "performance":
                    add(
                        doc,
                        capture_clock,
                        utc_stamp(doc["created_at"]),
                        "performance",
                        result["decoded"]["values"],
                        0,
                    )
                else:
                    add(
                        doc,
                        capture_clock,
                        utc_stamp(doc["created_at"]),
                        "runtime",
                        result["decoded"]["values"],
                        0,
                    )
            elif doc["kind"] in {"runtime_trace", "movement_trace", "title_start"}:
                samples = (
                    [data["before"], data["after"]] if doc["kind"] == "title_start" else data.get("samples")
                )
                if not isinstance(samples, list) or len(samples) > MAX_EVENTS:
                    raise ToolFailure("invalid_timeline", "Missing or oversized sample list.")
                previous = None
                for index, sample in enumerate(samples):
                    values = decode("runtime", sample)["payload"]
                    # Legacy artifacts lacking timestamps retain ordinal order.
                    clock = "utc_capture" if "captured_at" in sample else "ordinal"
                    stamp = utc_stamp(sample["captured_at"]) if clock == "utc_capture" else index
                    if previous is not None and clock == "utc_capture" and stamp < previous:
                        raise ToolFailure(
                            "clock_regressed",
                            "Capture clock moved backward; split or inspect the original trace.",
                        )
                    previous = stamp if clock == "utc_capture" else None
                    add(doc, clock, stamp, "runtime", values, index)
                summary = data.get("summary", {})
                add(
                    doc,
                    "utc_capture",
                    utc_stamp(doc["created_at"]),
                    "capture_outcome",
                    {
                        key: summary[key]
                        for key in (
                            "outcome",
                            "input_released",
                            "sample_count",
                            "planned_press_ms",
                            "press_ms",
                        )
                        if key in summary
                    },
                    -1,
                )
            else:
                raise ToolFailure(
                    "incompatible_evidence",
                    "Timeline supports runtime/movement/title traces and diagnostic captures only.",
                )
        events.sort(
            key=lambda e: (
                e["stream"],
                e["time"] if e["clock"].startswith("utc_") else int(e["time"]),
                e["sources"][0]["artifact_id"],
                e["sources"][0]["row"],
            )
        )
        observations = {}
        for event in events:
            if event["kind"] in {"runtime", "performance"}:
                key = event["stream"], event["kind"], event["time"]
                bucket = observations.setdefault(key, {"values": set(), "artifacts": set()})
                bucket["values"].add(fingerprint(event["details"]))
                bucket["artifacts"].add(event["sources"][0]["artifact_id"])
        ambiguous = {
            key
            for key, bucket in observations.items()
            if len(bucket["values"]) > 1 and len(bucket["artifacts"]) > 1
        }
        findings, previous, previous_events, reported = [], {}, {}, set()
        for index, event in enumerate(events):
            event["event_id"] = index
            values, stream, kind = event["details"], event["stream"], event["kind"]
            prior = previous.get((stream, kind))

            def finding(rule, details, event_index=index):
                findings.append({"rule": rule, "event_id": event_index, "details": details})

            previous_event = previous_events.get((stream, kind))
            key = stream, kind, event["time"]
            if key in ambiguous:
                if key not in reported:
                    finding("ambiguous_sample_order", {"time": event["time"], "clock": event["clock"]})
                    reported.add(key)
                prior = None
            if previous_event and (stream, kind, previous_event["time"]) in ambiguous:
                prior = None
            if kind == "runtime":
                if prior:
                    changes = {
                        key: [prior[key], values[key]] for key in STATE_FIELDS if prior[key] != values[key]
                    }
                    if changes:
                        finding("state_changed", changes)
                    actor_changes = {}
                    for actor_index, (old, new) in enumerate(
                        zip(prior["actors"], values["actors"], strict=True)
                    ):
                        changes = {
                            key: [old[key], new[key]]
                            for key in ("observed", "action", "movement", "held")
                            if old[key] != new[key]
                            and all(prior[key] == values[key] for key in ("stage", "generation"))
                            and (key == "observed" or old["observed"] == new["observed"] == 1)
                        }
                        if changes:
                            actor_changes[str(actor_index)] = changes
                    if actor_changes:
                        finding("actor_changed", actor_changes)
                for key in ("faults", "native_errors"):
                    if values[key] and (prior is None or prior[key] != values[key]):
                        finding(
                            "runtime_fault_observed",
                            {"counter": key, "value": values[key], "previous": prior[key] if prior else None},
                        )
            elif kind == "death_refusal":
                finding("revival_refused", {"actor": event["actor"], "reasons": values["reasons"]})
            elif kind == "performance":
                for key in ("clock_failures", "start_failures"):
                    if int(values[key]) and (prior is None or values[key] != prior[key]):
                        finding("performance_failure_observed", {"counter": key, "value": values[key]})
            elif kind == "capture_outcome" and (
                values.get("outcome") in {"failed", "cancelled"} or values.get("input_released") is False
            ):
                finding("incomplete_capture", values)
            elif kind == "retention" and values["older_rows_overwritten"]:
                finding("history_overwritten", values)
            previous[(stream, kind)] = values
            previous_events[(stream, kind)] = event
        summary = {
            "events": len(events),
            "findings": len(findings),
            "streams": len(streams),
            "source_artifacts": len(inputs),
            "rules_version": RULES_VERSION,
            "evidence_class": "offline_analysis",
        }
        return {
            "summary": summary,
            "inputs": inputs,
            "streams": streams,
            "events": events,
            "findings": findings,
            "limitations": [
                "Streams with different clocks, sessions, identities or evidence classes are not aligned.",
                "UTC timestamps mark host capture, not exact game-event time. Native tick values are not UTC.",
                "utc_artifact is the time supplied offline data was saved; the actual observation time is unknown.",
                "Polling misses intermediate changes; event proximity does not establish causality.",
                "Input recipe metadata describes requested input, not physical controller actions or confirmed movement.",
            ],
        }

    def build(self, artifact_ids):
        data = self.collect(artifact_ids)
        receipt = self.artifacts.put(
            "event_timeline", data, {"evidence_class": "offline_analysis", "rules_version": RULES_VERSION}
        )
        return {**receipt, "summary": data["summary"], "limitations": data["limitations"]}

    def get(self, artifact_id):
        doc = self.artifacts.get(artifact_id)
        if doc["kind"] != "event_timeline":
            raise ToolFailure("incompatible_evidence", "Expected an event timeline artifact.")
        return doc["data"]

    def query(self, artifact_id, kind="", actor="", text="", offset=0, limit=25):
        if (
            len(text) > 128
            or len(kind) > 40
            or len(actor) > 40
            or not 0 <= offset <= MAX_EVENTS
            or not 1 <= limit <= 100
        ):
            raise ToolFailure("invalid_parameters", "Use bounded filters and pagination.")
        data = self.get(artifact_id)
        rows = [
            row
            for row in data["events"]
            if (not kind or row["kind"] == kind)
            and (not actor or row["actor"] == actor)
            and (not text or text.casefold() in json.dumps(row["details"], ensure_ascii=False).casefold())
        ]
        return {
            "events": rows[offset : offset + limit],
            "total_matches": len(rows),
            "next_offset": offset + limit if len(rows) > offset + limit else None,
            "findings": [
                f
                for f in data["findings"]
                if f["event_id"] in {r["event_id"] for r in rows[offset : offset + limit]}
            ],
        }

    def replay(self, artifact_id):
        prior = self.get(artifact_id)
        current = self.collect([item["artifact_id"] for item in prior["inputs"]])
        if current["inputs"] != prior["inputs"]:
            raise ToolFailure(
                "evidence_changed", "Source evidence changed since timeline creation; comparison refused."
            )
        summary = {
            "matches_recorded_events": current["events"] == prior["events"],
            "matches_recorded_findings": current["findings"] == prior["findings"],
            "recorded_rules_version": prior["summary"]["rules_version"],
            "current_rules_version": RULES_VERSION,
            "evidence_class": "offline_replay",
        }
        changes = differences(
            {key: prior[key] for key in ("events", "findings")},
            {key: current[key] for key in ("events", "findings")},
        )
        receipt = self.artifacts.put(
            "timeline_replay",
            {"summary": summary, "current": current, "differences": changes},
            {"source_timeline_id": artifact_id, "evidence_class": "offline_replay"},
        )
        return {**receipt, "summary": summary, "differences": changes}
