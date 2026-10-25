"""Bounded derived events from immutable copied recordings. MIT, Thingolus."""

import json
from collections import Counter

from .common import ToolFailure, digest
from .diagnostics import fingerprint
from .gameplay_data import GameplayRecording

DECODER_VERSION = 1
EVENT_LIMIT = 4096
EVENT_KINDS = ("hp_decreased", "hp_increased", "zero_hp_to_positive", "inventory_delta", "action_changed")


def boundary(first, second, max_gap_ms=2000):
    if (first.stage, first.generation) != (second.stage, second.generation):
        return "world_changed"
    if not first.complete or not second.complete or first.omitted or second.omitted:
        return "incomplete_observation"
    if second.sequence != first.sequence + 1:
        return "sequence_gap"
    if second.elapsed_ms - first.elapsed_ms > max_gap_ms:
        return "sampling_gap"
    return None


def actor_pair(first, second, subject, max_gap_ms=2000):
    reason = boundary(first, second, max_gap_ms)
    a, b = subject.select(first), subject.select(second)
    if reason:
        return None, None, reason
    if a is None or b is None:
        return None, None, "subject_unavailable"
    if a.entity.identity() != b.entity.identity() or (a.kind, a.role) != (b.kind, b.role):
        return None, None, "entity_lifetime_changed"
    return a, b, None


def derive_events(recording, max_gap_ms=2000):
    events, gaps = [], []
    omitted = 0

    def emit(first, second, actor, kind, before, after, item_id=None):
        nonlocal omitted
        if len(events) >= EVENT_LIMIT:
            omitted += 1
            return
        event = {
            "kind": kind,
            "entity": actor.entity.model_dump(),
            "role": actor.role,
            "from_sequence": first.sequence,
            "to_sequence": second.sequence,
            "from_ms": first.elapsed_ms,
            "to_ms": second.elapsed_ms,
            "before": before,
            "after": after,
            "delta": after - before,
            "item_id": item_id,
            "attribution": "unavailable",
        }
        event["event_id"] = fingerprint({"identity": recording.identity.model_dump(), **event})
        events.append(event)

    for first, second in zip(recording.frames, recording.frames[1:], strict=False):
        reason = boundary(first, second, max_gap_ms)
        if reason:
            gaps.append({"from_sequence": first.sequence, "to_sequence": second.sequence, "reason": reason})
            continue
        old = {actor.entity.key: actor for actor in first.actors}
        for actor in second.actors:
            prior = old.get(actor.entity.key)
            if prior is None:
                continue
            if prior.entity.identity() != actor.entity.identity() or (prior.kind, prior.role) != (
                actor.kind,
                actor.role,
            ):
                gaps.append(
                    {
                        "from_sequence": first.sequence,
                        "to_sequence": second.sequence,
                        "entity_key": actor.entity.key,
                        "reason": "entity_lifetime_changed",
                    }
                )
                continue
            if prior.hp is not None and actor.hp is not None and prior.hp != actor.hp:
                emit(
                    first,
                    second,
                    actor,
                    "hp_decreased" if actor.hp < prior.hp else "hp_increased",
                    prior.hp,
                    actor.hp,
                )
                if prior.hp == 0 and actor.hp > 0:
                    emit(first, second, actor, "zero_hp_to_positive", prior.hp, actor.hp)
            if prior.action is not None and actor.action is not None and prior.action != actor.action:
                emit(first, second, actor, "action_changed", prior.action, actor.action)
            if (
                prior.inventory is not None
                and actor.inventory is not None
                and prior.inventory.complete
                and actor.inventory.complete
            ):
                a, b = prior.inventory.totals(), actor.inventory.totals()
                for item_id in sorted(a.keys() | b.keys()):
                    if a.get(item_id, 0) != b.get(item_id, 0):
                        emit(
                            first,
                            second,
                            actor,
                            "inventory_delta",
                            a.get(item_id, 0),
                            b.get(item_id, 0),
                            item_id,
                        )
    return {
        "decoder_version": DECODER_VERSION,
        "events": events,
        "gaps": gaps,
        "omitted_events": omitted,
        "summary": {
            "frames": len(recording.frames),
            "events": len(events),
            "gaps": len(gaps),
            "omitted_events": omitted,
            "kinds": dict(Counter(e["kind"] for e in events)),
            "native_acceptance": "unverified",
        },
        "limitations": [
            "Sample deltas are not engine notifications or attribution to a particular action/attacker.",
            "Zero-to-positive HP does not establish complete engine revival state.",
            "Inventory gains do not identify loot, purchases, transfers or their cause.",
            "Continuity is trusted only within the supplied identity scope; native session-wide IDs are not implemented.",
            "Missing, partial or nonadjacent samples never produce inferred changes.",
        ],
    }


class GameplayRecordings:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def save(self, recording):
        recording = GameplayRecording.model_validate(recording)
        payload = recording.model_dump()
        if len(json.dumps(payload, allow_nan=False).encode()) > 2 * 1024 * 1024:
            raise ToolFailure("recording_too_large", "Use a recording of at most 2 MiB.")
        decoded = derive_events(recording)
        data = {
            "recording": payload,
            "payload_sha256": fingerprint(payload),
            "decoded": decoded,
            "summary": decoded["summary"],
        }
        receipt = self.artifacts.put("gameplay_recording", data, {"evidence_class": "offline_supplied"})
        return {**receipt, "summary": data["summary"]}

    def load(self, recording_id):
        doc = self.artifacts.get(recording_id)
        if doc["kind"] != "gameplay_recording":
            raise ToolFailure("recording_invalid", "Select a copied gameplay recording.")
        payload = doc["data"]["recording"]
        if fingerprint(payload) != doc["data"]["payload_sha256"]:
            raise ToolFailure("evidence_changed", "Recorded observations changed.")
        return GameplayRecording.model_validate(payload), doc

    def query(self, recording_id, kind=None, entity_key=None, offset=0, limit=20):
        if kind not in (None, *EVENT_KINDS) or not 0 <= offset <= 4096 or not 1 <= limit <= 100:
            raise ToolFailure("invalid_parameters", "Use a known event kind and a bounded page.")
        recording, doc = self.load(recording_id)
        decoded = derive_events(recording)
        rows = [
            event
            for event in decoded["events"]
            if (kind is None or event["kind"] == kind)
            and (entity_key is None or event["entity"]["key"] == entity_key)
        ]
        return {
            "recording_id": recording_id,
            "source_sha256": digest(self.artifacts.path(recording_id)),
            "evidence_class": "offline_replay",
            "decoder_version": DECODER_VERSION,
            "matches_recorded_decode": decoded == doc["data"]["decoded"],
            "summary": decoded["summary"],
            "events": rows[offset : offset + limit],
            "total": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "limitations": decoded["limitations"],
        }
