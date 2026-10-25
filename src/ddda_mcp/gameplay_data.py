"""Pointer-free observation and command contracts. Copyright (c) 2026 Thingolus. MIT.

These are host-side schemas, not new native exports or evidence of engine semantics.
Caller-supplied recordings always remain offline evidence.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .control import ACTIONS
from .diagnostics import U32

Token = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Position = Annotated[list[float], Field(min_length=3, max_length=3)]
ItemId = Annotated[int, Field(strict=True, ge=-32768, le=32767)]
ActionName = Literal[
    "forward",
    "backward",
    "left",
    "right",
    "run_forward",
    "run_backward",
    "run_left",
    "run_right",
    "camera_left",
    "camera_right",
    "camera_up",
    "camera_down",
    "jump_forward",
    "light_attack",
    "heavy_attack",
    "jump",
    "interact",
    "sheath",
    "grab",
    "dodge",
    "menu",
    "inventory",
    "menu_up",
    "menu_down",
    "confirm",
    "cancel",
    "neutral",
    "use_item",
    "interact_target",
    "approach_target",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class EntityRef(Contract):
    key: Token
    scope: Literal["capture", "session"]
    epoch: Token
    incarnation: U32 | None = None

    @model_validator(mode="after")
    def lifetime(self):
        if self.scope == "session" and self.incarnation is None:
            raise ValueError("Session identities require an explicit lifetime incarnation.")
        return self

    def identity(self):
        return self.scope, self.epoch, self.key, self.incarnation


class Item(Contract):
    item_id: ItemId
    quantity: U32


class Inventory(Contract):
    complete: bool
    items: Annotated[list[Item], Field(max_length=256)]

    def totals(self):
        result = {}
        for item in self.items:
            result[item.item_id] = result.get(item.item_id, 0) + item.quantity
        return result


class ActorObservation(Contract):
    entity: EntityRef
    kind: Literal["party", "registry_actor", "unknown"] = "unknown"
    role: Literal[0, 1] | None = None
    position: Position | None = None
    hp: Annotated[float | None, Field(ge=0)] = None
    hp_max: Annotated[float | None, Field(ge=0)] = None
    stamina: Annotated[float | None, Field(ge=0)] = None
    action: U32 | None = None
    vocation: U32 | None = None
    inventory: Inventory | None = None

    @model_validator(mode="after")
    def party_role(self):
        if self.role is not None and self.kind != "party":
            raise ValueError("Only party observations may claim a player role.")
        return self


class ObservationFrame(Contract):
    sequence: U32
    elapsed_ms: Annotated[int, Field(strict=True, ge=0, le=120000)]
    stage: U32
    generation: U32
    complete: bool
    omitted: U32 = 0
    menu_open: bool | None = None
    actors: Annotated[list[ActorObservation], Field(max_length=26)]

    @model_validator(mode="after")
    def unique_entities(self):
        keys = [actor.entity.key for actor in self.actors]
        roles = [actor.role for actor in self.actors if actor.role is not None]
        if len(set(keys)) != len(keys) or len(set(roles)) != len(roles):
            raise ValueError("A frame cannot contain duplicate entity keys or party roles.")
        return self


class Subject(Contract):
    role: Literal[0, 1] | None = None
    entity_key: Token | None = None

    @model_validator(mode="after")
    def one_selector(self):
        if (self.role is None) == (self.entity_key is None):
            raise ValueError("Select exactly one party role or entity key.")
        return self

    def select(self, frame):
        return next(
            (
                actor
                for actor in frame.actors
                if (self.role is not None and actor.role == self.role)
                or (self.entity_key is not None and actor.entity.key == self.entity_key)
            ),
            None,
        )


class Command(Contract):
    action: ActionName
    role: Literal[0, 1] = 0
    duration_ms: Annotated[int, Field(strict=True, ge=50, le=1000)] = 350
    item_id: ItemId | None = None
    target: EntityRef | None = None

    @model_validator(mode="after")
    def parameters(self):
        if (self.action == "use_item") != (self.item_id is not None):
            raise ValueError("Only use_item requires an item ID.")
        if (self.action in {"approach_target", "interact_target"}) != (self.target is not None):
            raise ValueError("Targeted commands require an exact entity identity.")
        return self


class RecordedAction(Contract):
    command: Command
    before_sequence: U32
    after_sequence: U32
    outcome: Literal["accepted", "refused", "unknown"]


class RecordedCleanup(Contract):
    input_released: bool | None = None
    observers_sealed: bool | None = None
    restoration: Literal["verified", "not_applicable", "failed", "unknown"] = "unknown"

    def complete(self):
        return (
            self.input_released is True
            and self.observers_sealed is True
            and self.restoration in {"verified", "not_applicable"}
        )


class RecordingIdentity(Contract):
    session: Token
    clock: Token
    game_sha256: Hash
    source_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    backend: Literal["synthetic", "coop", "standalone"]
    runtime_sha256: Hash | None = None
    bridge_sha256: Hash | None = None

    @model_validator(mode="after")
    def build_identity(self):
        if self.backend == "coop" and self.runtime_sha256 is None:
            raise ValueError("Co-op recordings need a runtime identity.")
        if self.backend == "standalone" and self.bridge_sha256 is None:
            raise ValueError("Standalone recordings need a bridge identity.")
        return self


class GameplayRecording(Contract):
    schema_version: Literal[1] = 1
    label: Annotated[str, Field(min_length=1, max_length=120)]
    identity: RecordingIdentity
    frames: Annotated[list[ObservationFrame], Field(min_length=1, max_length=256)]
    actions: Annotated[list[RecordedAction], Field(max_length=64)] = Field(default_factory=list)
    cleanup: RecordedCleanup = Field(default_factory=RecordedCleanup)
    terminal: Literal["completed", "cancelled", "timeout", "failed", "outcome_unknown"] = "completed"

    @model_validator(mode="after")
    def ordered(self):
        for first, second in zip(self.frames, self.frames[1:], strict=False):
            if second.sequence <= first.sequence or second.elapsed_ms <= first.elapsed_ms:
                raise ValueError("Frame sequences and relative times must strictly increase.")
        frames = {frame.sequence: frame for frame in self.frames}
        previous_end = -1
        for action in self.actions:
            if (
                action.before_sequence not in frames
                or action.after_sequence not in frames
                or action.before_sequence >= action.after_sequence
                or action.before_sequence < previous_end
            ):
                raise ValueError("Actions need ordered, nonoverlapping before/after frame references.")
            previous_end = action.after_sequence
        return self


def backend_capabilities(backend):
    """Static reviewed capability declarations, never a live readiness check."""
    return {
        "copied_world": backend in {"coop", "standalone"},
        "fixed_input": backend == "coop",
        "use_item": False,
        "interact_target": False,
        "approach_target": False,
        "session_entity_identity": False,
        "observation_stream_v1": False,
        "attributed_damage": False,
        "quest_state": False,
    }


def command_capability(command):
    return "fixed_input" if command.action in ACTIONS else command.action
