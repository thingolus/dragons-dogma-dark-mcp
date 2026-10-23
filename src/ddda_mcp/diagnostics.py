"""Reviewed copied-value adapters and reproducible offline replay. MIT, Thingolus."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from .common import ToolFailure
from .death import POINTER_COLUMNS, decode_death

U32 = Annotated[int, Field(strict=True, ge=0, le=0xFFFFFFFF)]
I32 = Annotated[int, Field(strict=True, ge=-(2**31), le=2**31 - 1)]


def uint64_text(value):
    if int(value) > 2**64 - 1:
        raise ValueError("Counter exceeds unsigned 64-bit range.")
    return value


U64Text = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,19})$"), AfterValidator(uint64_text)]


class Copied(BaseModel):
    # Only declared copied values survive: unknown fields (including addresses)
    # never enter replay payloads. Native adapters must ALSO redact before RPC.
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)


class Actor(Copied):
    observed: U32
    action: U32
    movement: U32
    held: U32
    frames: U32
    position: Annotated[list[float], Field(min_length=3, max_length=3)]
    angle: float


class Runtime(Copied):
    size: Literal[132]
    version: Literal[2]
    runtime: I32
    p1: I32
    p2: I32
    session: I32
    transport: I32
    native_offline: I32
    native_errors: I32
    faults: I32
    stage: I32
    generation: I32
    physical_mask: I32
    developer_input: I32
    menu_gated: I32
    guard_transport: I32
    actors: Annotated[list[Actor], Field(min_length=2, max_length=2)]


class Performance(Copied):
    size: Literal[2448]
    version: Literal[1]
    state: U32
    coverage_mask: U32
    frequency: U64Text
    admitted_roots: U64Text
    completed_roots: U64Text
    active_roots: U64Text
    clock_failures: U64Text
    start_failures: U64Text


@dataclass(frozen=True)
class Adapter:
    name: str
    export: str
    size: int
    abi_version: int
    source: str
    model: type[Copied] | None = None
    decoder_version: int = 1
    word_decoder: Callable[[list[int]], dict] | None = None
    word_count: int = 0
    redacted_indices: tuple[int, ...] = ()
    requires_developer: bool = False
    limitations: tuple[str, ...] = ()

    def describe(self):
        return {
            "adapter": self.name,
            "export": self.export,
            "byte_size": self.size,
            "abi_version": self.abi_version,
            "decoder_version": self.decoder_version,
            "source_path": self.source,
            "payload_schema": self.model.model_json_schema()
            if self.model
            else {
                "type": "object",
                "required": ["words"],
                "properties": {
                    "words": {
                        "type": "array",
                        "minItems": self.word_count,
                        "maxItems": self.word_count,
                        "items": {"type": "integer", "minimum": 0, "maximum": 4294967295},
                    }
                },
            },
            "live_requirements": [
                "owned session",
                "supported executable",
                "offline transport guard",
                "matching ABI",
            ]
            + (["healthy developer runtime"] if self.requires_developer else []),
            "availability": "Offline decoder available; live export/readiness checked only in an owned session.",
        }

    def decode(self, payload):
        if not isinstance(payload, dict):
            raise ToolFailure("invalid_diagnostic", "Diagnostic payload must be an object.")
        if self.word_decoder is not None:
            words = payload.get("words")
            if (
                not isinstance(words, list)
                or len(words) != self.word_count
                or any(type(word) is not int or not 0 <= word <= 0xFFFFFFFF for word in words)
            ):
                raise ToolFailure("invalid_diagnostic", f"Expected {self.word_count} unsigned 32-bit words.")
            if words[:2] != [self.size, self.abi_version]:
                raise ToolFailure("abi_mismatch", "Word diagnostic header does not match its reviewed ABI.")
            redacted = list(words)
            for index in self.redacted_indices:
                redacted[index] = 0
            decoded = self.word_decoder(redacted)
            return {"words": redacted}, decoded
        if self.model is None:
            raise ToolFailure("diagnostic_unavailable", "Adapter has no reviewed schema or decoder.")
        if any(type(payload.get(key)) is not int for key in ("size", "version")) or (
            payload.get("size"),
            payload.get("version"),
        ) != (self.size, self.abi_version):
            raise ToolFailure(
                "abi_mismatch", f"{self.name} requires size={self.size}/version={self.abi_version}."
            )
        try:
            copied = self.model.model_validate(payload).model_dump()
        except ValidationError as exc:
            # Do not echo invalid input values, which may contain private addresses.
            raise ToolFailure("invalid_diagnostic", "Copied fields do not match the adapter schema.") from exc
        return copied, {
            "values": copied,
            "limitations": [
                "Copied values are observations, not gameplay acceptance.",
                *self.limitations,
            ],
        }


ADAPTERS = {
    adapter.name: adapter
    for adapter in (
        Adapter(
            "death_refusals",
            "CoopSharedLifeDownDebugStatus",
            2080,
            1,
            "include/coop/shared_life_down_debug.hpp",
            word_decoder=decode_death,
            word_count=520,
            redacted_indices=tuple(8 + row * 64 + column for row in range(8) for column in POINTER_COLUMNS),
            requires_developer=True,
        ),
        Adapter(
            "runtime",
            "CoopGetStatus",
            132,
            2,
            "include/coop/runtime_status.hpp",
            Runtime,
            limitations=(
                "Actor observation flags determine availability; absent actors are not zero-valued observations.",
            ),
        ),
        Adapter(
            "performance",
            "CoopGetPerformanceStatus",
            2448,
            1,
            "include/coop/performance.hpp",
            Performance,
            limitations=(
                "Performance coverage is limited to existing callback instrumentation; no whole-game latency claim.",
            ),
        ),
    )
}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def differences(before, after, limit=25):
    """Bounded leaf differences for regression triage; inputs are already redacted."""
    changes = []

    def walk(first, second, path=""):
        if type(first) is type(second) and first == second:
            return
        if isinstance(first, dict) and isinstance(second, dict):
            for key in sorted(first.keys() | second.keys()):
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                if key in first and key in second:
                    yield from walk(first[key], second[key], path + "/" + escaped)
                else:
                    yield {"path": path + "/" + escaped, "change": "removed" if key in first else "added"}
        elif isinstance(first, list) and isinstance(second, list):
            for index in range(max(len(first), len(second))):
                if index < len(first) and index < len(second):
                    yield from walk(first[index], second[index], path + f"/{index}")
                else:
                    yield {"path": path + f"/{index}", "change": "removed" if index < len(first) else "added"}
        else:
            yield {"path": path or "/", "before": json.dumps(first)[:200], "after": json.dumps(second)[:200]}

    for change in walk(before, after):
        if len(changes) == limit:
            return {"changes": changes, "truncated": True}
        changes.append(change)
    return {"changes": changes, "truncated": False}


def decode(adapter, payload):
    if adapter not in ADAPTERS:
        raise ToolFailure("diagnostic_unavailable", "No reviewed adapter with that name.")
    clean, decoded = ADAPTERS[adapter].decode(payload)
    return {
        "adapter": adapter,
        "decoder_version": ADAPTERS[adapter].decoder_version,
        "payload": clean,
        "decoded": decoded,
        "payload_sha256": fingerprint(clean),
    }


class Diagnostics:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def catalog(self):
        return {
            "adapters": [adapter.describe() for adapter in ADAPTERS.values()],
            "extension_policy": "New adapters require reviewed code, schemas, native redaction and replay fixtures. No dynamic code loading.",
        }

    def save(self, adapter, payload):
        data = decode(adapter, payload)
        data["summary"] = {
            "adapter": adapter,
            "decoder_version": data["decoder_version"],
            "payload_sha256": data["payload_sha256"],
            "evidence_class": "offline_supplied",
        }
        receipt = self.artifacts.put("diagnostic_capture", data, {"evidence_class": "offline_supplied"})
        return {**receipt, "summary": data["summary"], "decoded": data["decoded"]}

    def read_capture(self, artifact_id):
        doc = self.artifacts.get(artifact_id)
        return doc, self.normalize_capture(doc)

    def normalize_capture(self, doc):
        if doc["kind"] == "death_diagnostic":
            result = decode("death_refusals", {"words": doc["data"]["words"]})
            if doc["data"].get("payload_sha256", result["payload_sha256"]) != result["payload_sha256"]:
                raise ToolFailure("evidence_changed", "Stored death diagnostic hash no longer matches.")
            return result
        if doc["kind"] != "diagnostic_capture":
            raise ToolFailure("incompatible_evidence", "Expected a diagnostic capture or death diagnostic.")
        result = decode(doc["data"]["adapter"], doc["data"]["payload"])
        if result["payload_sha256"] != doc["data"]["payload_sha256"]:
            raise ToolFailure("evidence_changed", "Stored diagnostic payload hash no longer matches.")
        return result

    def replay(self, artifact_id):
        doc, result = self.read_capture(artifact_id)
        prior = doc["data"].get("decoded")
        if not isinstance(prior, dict):
            raise ToolFailure("invalid_diagnostic", "Capture has no recorded decoder result to compare.")
        summary = {
            "adapter": result["adapter"],
            "matches_recorded_decode": prior == result["decoded"],
            "recorded_decoder_version": doc["data"].get("decoder_version", 1),
            "current_decoder_version": result["decoder_version"],
            "evidence_class": "offline_replay",
        }
        changes = differences(prior, result["decoded"])
        receipt = self.artifacts.put(
            "diagnostic_replay",
            {"summary": summary, "decoded": result["decoded"], "differences": changes},
            {
                "source_artifact_id": artifact_id,
                "source_sha256": fingerprint(doc),
                "source_evidence_class": doc["provenance"].get("evidence_class", "unknown"),
                "evidence_class": "offline_replay",
            },
        )
        return {**receipt, "summary": summary, "differences": changes}
