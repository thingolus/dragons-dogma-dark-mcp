"""Offline, condition-driven experiment execution and replay. MIT, Thingolus.

The executor has no session, process, deployment or desktop dependencies. Its only
backend is a recorded action/observation tape; live dispatch is deliberately absent.
"""

import json
import math
import time
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ToolFailure, digest
from .diagnostics import fingerprint
from .gameplay_data import (
    Command,
    Contract,
    EntityRef,
    ItemId,
    Subject,
    backend_capabilities,
    command_capability,
)
from .gameplay_events import actor_pair, boundary


class Goal(Contract):
    kind: Literal["combat", "healing", "revival", "loot", "movement"]
    subject: Subject
    minimum: Annotated[float, Field(gt=0, le=1000000)] = 1.0
    item_id: ItemId | None = None

    @model_validator(mode="after")
    def item_required(self):
        if (self.kind == "loot") != (self.item_id is not None):
            raise ValueError("Only a loot goal requires an item ID.")
        return self


class Condition(Contract):
    predicate: Literal[
        "hp_at_least", "hp_below", "hp_zero", "item_at_least", "within_distance", "menu_open", "menu_closed"
    ]
    subject: Subject | None = None
    threshold: Annotated[float | None, Field(ge=0, le=1000000)] = None
    item_id: ItemId | None = None
    target: EntityRef | None = None

    @model_validator(mode="after")
    def parameters(self):
        menu = self.predicate in {"menu_open", "menu_closed"}
        needs_threshold = self.predicate in {"hp_at_least", "hp_below", "item_at_least", "within_distance"}
        if menu != (self.subject is None):
            raise ValueError("Actor conditions require a subject; menu conditions do not accept one.")
        if needs_threshold != (self.threshold is not None):
            raise ValueError("This condition has a missing or extraneous threshold.")
        if (self.predicate == "item_at_least") != (self.item_id is not None):
            raise ValueError("Only inventory conditions require an item ID.")
        if (self.predicate == "within_distance") != (self.target is not None):
            raise ValueError("Distance conditions require an exact target identity.")
        return self


class RequireStep(Contract):
    kind: Literal["require"]
    condition: Condition


class ActionStep(Contract):
    kind: Literal["action"]
    command: Command
    timeout_ms: Annotated[int, Field(strict=True, ge=50, le=10000)] = 5000

    @model_validator(mode="after")
    def fits(self):
        if self.timeout_ms < self.command.duration_ms:
            raise ValueError("Action duration exceeds its deadline.")
        return self


class WaitStep(Contract):
    kind: Literal["wait"]
    timeout_ms: Annotated[int, Field(strict=True, ge=50, le=30000)] = 5000
    # Absent condition means wait for the plan's measured outcome.
    condition: Condition | None = None


Step = Annotated[RequireStep | ActionStep | WaitStep, Field(discriminator="kind")]


class ExperimentPlan(Contract):
    schema_version: Literal[1] = 1
    label: Annotated[str, Field(min_length=1, max_length=120)]
    goal: Goal
    steps: Annotated[list[Step], Field(min_length=1, max_length=32)]
    control_mode: Literal["solo", "pair"] = "solo"
    max_duration_ms: Annotated[int, Field(strict=True, ge=50, le=120000)] = 30000
    max_sample_gap_ms: Annotated[int, Field(strict=True, ge=50, le=10000)] = 2000
    fixture_id: Annotated[str | None, Field(pattern=r"^[0-9a-f]{32}$")] = None

    @model_validator(mode="after")
    def bounded(self):
        budget = sum(step.timeout_ms for step in self.steps if isinstance(step, ActionStep | WaitStep))
        if budget > self.max_duration_ms:
            raise ValueError("Step deadlines exceed the total experiment budget.")
        if self.control_mode == "solo" and any(
            isinstance(step, ActionStep) and step.command.role != 0 for step in self.steps
        ):
            raise ValueError("Solo plans cannot command P2.")
        return self


def check_condition(condition, frame):
    if not frame.complete or frame.omitted:
        return None, "incomplete_observation"
    if condition.predicate in {"menu_open", "menu_closed"}:
        if frame.menu_open is None:
            return None, "menu_unavailable"
        return frame.menu_open == (condition.predicate == "menu_open"), "menu_state"
    actor = condition.subject.select(frame)
    if actor is None:
        return None, "subject_unavailable"
    if condition.predicate.startswith("hp_"):
        if actor.hp is None:
            return None, "hp_unavailable"
        if condition.predicate == "hp_zero":
            return actor.hp == 0, "hp_zero"
        if condition.predicate == "hp_below":
            return actor.hp < condition.threshold, "hp_below"
        return actor.hp >= condition.threshold, "hp_at_least"
    if condition.predicate == "item_at_least":
        if actor.inventory is None or not actor.inventory.complete:
            return None, "inventory_unavailable"
        return actor.inventory.totals().get(condition.item_id, 0) >= condition.threshold, "item_at_least"
    target = next((a for a in frame.actors if a.entity.identity() == condition.target.identity()), None)
    if actor.position is None or target is None or target.position is None:
        return None, "target_position_unavailable"
    return math.dist(actor.position, target.position) <= condition.threshold, "within_distance"


def measure_goal(plan, frames):
    goal = plan.goal
    for first, second in zip(frames, frames[1:], strict=False):
        _, _, reason = actor_pair(first, second, goal.subject, plan.max_sample_gap_ms)
        if reason:
            return {"passed": None, "reason": reason}
    subjects = [goal.subject.select(frame) for frame in frames]
    if any(not f.complete or f.omitted for f in frames) or any(a is None for a in subjects):
        return {"passed": None, "reason": "subject_or_complete_observation_unavailable"}
    before, after = subjects[0], subjects[-1]
    if goal.kind == "movement":
        if any(a.position is None for a in subjects):
            return {"passed": None, "reason": "position_unavailable"}
        a, b = before.position, after.position
        amount = math.dist(a, b)
        scope = "Straight-line displacement in game units; path length and cause are unknown."
    elif goal.kind == "loot":
        if any(a.inventory is None or not a.inventory.complete for a in subjects):
            return {"passed": None, "reason": "inventory_unavailable"}
        a, b = (actor.inventory.totals().get(goal.item_id, 0) for actor in (before, after))
        amount = b - a
        scope = "Net item quantity increase; acquisition cause is unknown."
    else:
        if any(a.hp is None for a in subjects):
            return {"passed": None, "reason": "hp_unavailable"}
        a, b = before.hp, after.hp
        if (goal.kind == "revival" and a != 0) or (goal.kind in {"combat", "healing"} and a <= 0):
            return {"passed": None, "reason": "goal_precondition_unmet"}
        amount = a - b if goal.kind == "combat" else b - a
        scope = "Net HP change; cause and attacker are unknown."
        if goal.kind == "revival":
            scope = "Zero-to-positive HP only; full engine revival state is unknown."
    return {
        "passed": amount >= goal.minimum,
        "before": a,
        "after": b,
        "amount": amount,
        "minimum": goal.minimum,
        "scope": scope,
    }


def command_guard(command, frame):
    if not frame.complete or frame.omitted:
        return "incomplete_observation"
    actor = Subject(role=command.role).select(frame)
    if actor is None:
        return "controlled_actor_unavailable"
    menu_actions = {"menu", "inventory", "menu_up", "menu_down", "confirm", "cancel", "neutral", "use_item"}
    if command.action not in menu_actions and frame.menu_open is not False:
        return "menu_open_or_unknown"
    if command.target and not any(a.entity.identity() == command.target.identity() for a in frame.actors):
        return "target_identity_unavailable"
    if command.action == "use_item":
        if actor.inventory is None or not actor.inventory.complete:
            return "inventory_unavailable"
        if actor.inventory.totals().get(command.item_id, 0) <= 0:
            return "item_unavailable"
    return None


def replay(plan, recording):
    """Run the plan against a tape. Never dispatch, repeat or guess an action."""
    started = time.perf_counter()
    frames = recording.frames
    index = action_index = 0
    by_sequence = {frame.sequence: i for i, frame in enumerate(frames)}
    steps, failure = [], None

    def fail(reason, passed=None):
        return {"reason": reason, "outcome": "failed" if passed is False else "inconclusive"}

    for number, step in enumerate(plan.steps):
        row = {"step": number, "kind": step.kind, "from_sequence": frames[index].sequence}
        if isinstance(step, RequireStep):
            passed, reason = check_condition(step.condition, frames[index])
            if passed is not True:
                failure = fail(reason, passed)
        elif isinstance(step, ActionStep):
            reason = command_guard(step.command, frames[index])
            if reason:
                failure = fail(reason)
            elif action_index >= len(recording.actions):
                failure = fail("recorded_action_missing")
            else:
                action = recording.actions[action_index]
                if action.before_sequence != frames[index].sequence or action.command != step.command:
                    failure = fail("recorded_action_mismatch")
                elif action.outcome != "accepted":
                    failure = fail("command_" + action.outcome)
                else:
                    target = by_sequence[action.after_sequence]
                    elapsed = frames[target].elapsed_ms - frames[index].elapsed_ms
                    if elapsed < step.command.duration_ms:
                        failure = fail("action_observation_too_short")
                    elif elapsed > step.timeout_ms:
                        failure = fail("action_deadline_exceeded")
                    else:
                        # A capture gap during input makes the action's result unknown.
                        subjects = [Subject(role=step.command.role)]
                        if step.command.target:
                            subjects.append(Subject(entity_key=step.command.target.key))
                        for a, b in zip(frames[index:target], frames[index + 1 : target + 1], strict=True):
                            for subject in subjects:
                                _, _, reason = actor_pair(a, b, subject, plan.max_sample_gap_ms)
                                if reason:
                                    failure = fail(reason)
                                    break
                            if failure:
                                break
                        index = target
                        action_index += 1
        else:
            deadline = frames[index].elapsed_ms + step.timeout_ms
            while True:
                if step.condition:
                    passed, reason = check_condition(step.condition, frames[index])
                else:
                    measured = measure_goal(plan, frames[: index + 1])
                    passed, reason = measured["passed"], measured.get("reason", "goal_not_observed")
                if passed is True:
                    break
                if passed is None:
                    failure = fail(reason)
                    break
                if frames[index].elapsed_ms >= deadline:
                    failure = fail("wait_deadline_exceeded", False)
                    break
                if index + 1 >= len(frames):
                    failure = fail("recording_ended_before_deadline")
                    break
                if (
                    action_index < len(recording.actions)
                    and recording.actions[action_index].before_sequence < frames[index + 1].sequence
                ):
                    failure = fail("unplanned_action_during_wait")
                    break
                reason = boundary(frames[index], frames[index + 1], plan.max_sample_gap_ms)
                if reason:
                    failure = fail(reason)
                    break
                if frames[index + 1].elapsed_ms > deadline:
                    failure = fail("wait_deadline_exceeded", False)
                    break
                index += 1
        if frames[index].elapsed_ms - frames[0].elapsed_ms > plan.max_duration_ms:
            failure = fail("experiment_deadline_exceeded")
        row.update(
            {"to_sequence": frames[index].sequence, "outcome": failure["outcome"] if failure else "completed"}
        )
        if failure:
            row["reason"] = failure["reason"]
        steps.append(row)
        if failure:
            break

    measured = measure_goal(plan, frames[: index + 1])
    # Cancellation, unknown action outcomes and cleanup always override a positive
    # measurement. A replay cannot certify the actual installation's restoration.
    terminal_reasons = []
    if recording.terminal != "completed":
        terminal_reasons.append("recording_" + recording.terminal)
    if not recording.cleanup.complete():
        terminal_reasons.append("recorded_cleanup_unverified")
    if not failure and action_index != len(recording.actions):
        terminal_reasons.append("unconsumed_recorded_actions")
    if terminal_reasons:
        prior_failure = failure
        failure = fail(terminal_reasons[0])
        if prior_failure:
            failure["step_failure"] = prior_failure
    result = (
        failure["outcome"]
        if failure
        else "inconclusive"
        if measured["passed"] is None
        else "passed"
        if measured["passed"]
        else "failed"
    )
    summary = {
        "label": plan.label,
        "goal": plan.goal.kind,
        "outcome": result,
        "reason": failure["reason"] if failure else measured.get("reason", "measured_goal"),
        "evidence_class": "offline_replay",
        "native_acceptance": "unverified",
        "measurement": measured,
        "metrics": {
            "replay_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "recorded_elapsed_ms": frames[index].elapsed_ms - frames[0].elapsed_ms,
            "steps_completed": sum(s["outcome"] == "completed" for s in steps),
            "actions_matched": action_index,
            "frames_consumed": index + 1,
            "unused_frames": len(frames) - index - 1,
            "model_tokens": None,
        },
    }
    return {
        "summary": summary,
        "steps": steps,
        "failure": failure,
        "terminal_reasons": terminal_reasons,
        "recorded_cleanup": recording.cleanup.model_dump(),
        "limitations": [
            "All actions and cleanup are replayed claims, not operations performed on the game.",
            "Timing is decoder execution and recorded sample time, not measured development savings.",
        ],
    }


class Experiments:
    def __init__(self, artifacts, recordings):
        self.artifacts, self.recordings = artifacts, recordings

    def catalog(self):
        return {
            "schema_version": 1,
            "execution_backends": ["offline_replay", "native_coop"],
            "goals": {
                "combat": "Net observed HP decrease; no attacker attribution",
                "healing": "Net HP increase from a positive initial HP",
                "revival": "Zero-to-positive HP transition only",
                "loot": "Net quantity increase for a selected item ID; cause unknown",
                "movement": "Straight-line displacement in game units; cause unknown",
            },
            "steps": ["require", "action", "wait"],
            "limits": {"steps": 32, "duration_ms": 120000, "frames": 256, "recorded_actions": 64},
            "live_backend_capabilities": {b: backend_capabilities(b) for b in ("coop", "standalone")},
            "live_execution": "run_native_experiment: owned offline co-op session, fixed input actions, callback observations and verified cleanup. Fixture-bound plans require a gameplay suite.",
            "native_acceptance": "unverified",
        }

    def create(self, plan):
        plan = ExperimentPlan.model_validate(plan)
        references = {}
        if plan.fixture_id:
            doc = self.artifacts.get(plan.fixture_id)
            if doc["kind"] != "gameplay_fixture":
                raise ToolFailure("fixture_invalid", "Use a registered gameplay fixture.")
            references[plan.fixture_id] = digest(self.artifacts.path(plan.fixture_id))
            checkpoint_id = doc["data"]["checkpoint_id"]
            if digest(self.artifacts.path(checkpoint_id)) != doc["data"]["checkpoint_sha256"]:
                raise ToolFailure("evidence_changed", "The fixture checkpoint changed.")
            references[checkpoint_id] = doc["data"]["checkpoint_sha256"]
        required = sorted({command_capability(s.command) for s in plan.steps if isinstance(s, ActionStep)})
        missing = {
            backend: [key for key in required if not backend_capabilities(backend).get(key)]
            for backend in ("coop", "standalone")
        }
        payload = plan.model_dump()
        summary = {
            "label": plan.label,
            "goal": plan.goal.kind,
            "steps": len(plan.steps),
            "required_capabilities": required,
            "missing_live_capabilities": missing,
            "live_execution_available": not missing["coop"] and plan.max_sample_gap_ms >= 500,
            "native_acceptance": "unverified",
        }
        receipt = self.artifacts.put(
            "experiment_plan",
            {
                "plan": payload,
                "payload_sha256": fingerprint(payload),
                "references": references,
                "summary": summary,
            },
            {"evidence_class": "offline_plan", "creator": "Thingolus"},
        )
        return {**receipt, "summary": summary}

    def run(self, plan_id, recording_id):
        doc = self.artifacts.get(plan_id)
        if doc["kind"] != "experiment_plan":
            raise ToolFailure("plan_invalid", "Use a saved experiment plan.")
        data = doc["data"]
        if fingerprint(data["plan"]) != data["payload_sha256"]:
            raise ToolFailure("evidence_changed", "Experiment plan changed.")
        for ident, sha in data["references"].items():
            if digest(self.artifacts.path(ident)) != sha:
                raise ToolFailure("evidence_changed", "An experiment fixture reference changed.")
        plan = ExperimentPlan.model_validate(data["plan"])
        recording, _ = self.recordings.load(recording_id)
        report = replay(plan, recording)
        sources = {
            "plan_id": plan_id,
            "plan_sha256": digest(self.artifacts.path(plan_id)),
            "recording_id": recording_id,
            "recording_sha256": digest(self.artifacts.path(recording_id)),
        }
        receipt = self.artifacts.put(
            "experiment_replay", report, {**sources, "evidence_class": "offline_replay"}
        )
        response = {**receipt, "summary": report["summary"], "failure": report["failure"]}
        # Precisely scoped payload-size metric: excludes this metric itself and MCP envelope/transport copies.
        response["response_payload_bytes"] = len(
            json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
        )
        return response
