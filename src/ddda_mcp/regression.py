"""Durable repeated gameplay bisection with build/deploy/undo. MIT, Thingolus."""

import asyncio
import configparser
import re
import shutil
import uuid

import portalocker

from .common import ToolFailure, atomic_json, contained, digest, identifier, read_json
from .config import GAME_SHA256
from .deployment import installed
from .ownership import game_lease, require_closed
from .source import Source


def candidate_settings(current, target):
    """Overlay shared keys onto the selected revision's defaults; report every omission."""
    old, selected = (
        configparser.ConfigParser(interpolation=None),
        configparser.ConfigParser(interpolation=None),
    )
    old.read_string(current)
    selected.read_string(target)
    omitted = []
    for section in old.sections():
        for key, value in old.items(section):
            if selected.has_option(section, key):
                selected.set(section, key, value)
            else:
                omitted.append({"setting": section + "." + key, "value": value})
    if not selected.has_option("coop", "online_mode") or not selected.has_option("coop", "developer_input"):
        raise ToolFailure(
            "settings_incompatible", "Selected source lacks required offline/developer settings."
        )
    selected.set("coop", "online_mode", "0")
    selected.set("coop", "developer_input", "1")
    return selected, omitted


def choose_trial(revisions, trials, repeats):
    """Endpoints first, then midpoint; never label skips/flakes as a bad commit."""
    verdicts = {}
    for revision in revisions:
        results = [t["outcome"] for t in trials if t["revision"] == revision]
        if any(r not in {"passed", "failed"} for r in results) or len(set(results)) > 1:
            return {
                "state": "inconclusive",
                "reason": "inconsistent_or_inconclusive_trial",
                "revision": revision,
            }
        if len(results) >= repeats:
            verdicts[revision] = results[0]
    for endpoint in (revisions[0], revisions[-1]):
        if endpoint not in verdicts:
            return {"state": "ready", "revision": endpoint}
    if verdicts[revisions[0]] != "passed" or verdicts[revisions[-1]] != "failed":
        return {
            "state": "inconclusive",
            "reason": "endpoints_do_not_bracket_regression",
            "verdicts": verdicts,
        }
    low, high = 0, len(revisions) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if revisions[middle] not in verdicts:
            return {"state": "ready", "revision": revisions[middle]}
        if verdicts[revisions[middle]] == "passed":
            low = middle
        else:
            high = middle
    return {
        "state": "completed",
        "last_passing": revisions[low],
        "first_failing": revisions[high],
        "scope": "Selected ordered revisions and tested predicate, assuming monotonic behavior; unselected commits are not isolated.",
    }


class Regressions:
    def __init__(self, config, source, artifacts, builds, deployment, harness):
        self.config, self.source, self.artifacts, self.builds, self.deployment, self.harness = (
            config,
            source,
            artifacts,
            builds,
            deployment,
            harness,
        )
        self.root = config.artifacts / "regressions"
        self.lock = asyncio.Lock()

    def path(self, campaign_id):
        return contained(self.root, self.root / identifier(campaign_id) / "campaign.json")

    def status(self, campaign_id):
        data = read_json(self.path(campaign_id))
        if data.get("id") != campaign_id:
            raise ToolFailure("campaign_invalid", "Campaign identity differs.")
        return data

    def create(self, checkpoint_id, revisions, repeats=2):
        self.config.require_development()
        self.harness.load(checkpoint_id)
        if not 2 <= len(revisions) <= 16 or len(set(revisions)) != len(revisions) or repeats not in {2, 3}:
            raise ToolFailure(
                "invalid_parameters", "Select 2–16 distinct ordered commits and 2–3 trials per revision."
            )
        self.source.verify()
        for revision in revisions:
            if (
                not re.fullmatch(r"[0-9a-f]{40}", revision)
                or self.source.git("rev-parse", "--verify", revision + "^{commit}").decode().strip()
                != revision
            ):
                raise ToolFailure("invalid_revision", "Use exact existing commit identities.")
        for first, second in zip(revisions, revisions[1:], strict=False):
            self.source.git("merge-base", "--is-ancestor", first, second)
        campaign_id = uuid.uuid4().hex
        data = {
            "id": campaign_id,
            "checkpoint_id": checkpoint_id,
            "checkpoint_sha256": digest(self.artifacts.path(checkpoint_id)),
            "revisions": revisions,
            "repeats": repeats,
            "trials": [],
            "builds": {},
            "state": "ready",
            "active": None,
            "recipe": "observe_idle",
            "predicate": "stable advancing checkpoint world, offline guard and zero faults",
            "limitations": [
                "Native menu loading is performed by the AI client through observed UI.",
                "Shared-life changes make a trial inconclusive; reserve is not silently overwritten.",
                "Finds a boundary among selected revisions, not proof of causality or all gameplay behavior.",
            ],
        }
        atomic_json(self.path(campaign_id), data)
        return data

    def _shared_hash(self):
        path = self.config.game / "ddcoop.shared-lives.state"
        return digest(path) if path.is_file() else None

    def _settings_for_revision(self, revision):
        source = Source(self.config)
        source.commit = revision
        return source.read("config/ddcoop.ini")

    async def _cleanup(self, data):
        active = data.get("active")
        if not active:
            return
        session = self.harness.sessions.receipt
        if session:
            if active.get("session_id") != session.get("session_id"):
                raise ToolFailure("session_busy", "A different owned session is active; cleanup refused.")
            await self.harness.sessions.stop()
        # Each step is individually journaled and can be repeated after interruption.
        if active.get("deployment") and not active.get("deployment_cleaned"):
            receipt = self.deployment._read(active["deployment"])
            if receipt["state"] != "prepared":
                await asyncio.to_thread(self.deployment.rollback, active["deployment"])
            active["deployment_cleaned"] = True
            atomic_json(self.path(data["id"]), data)
        if active.get("save_backup") and not active.get("saves_cleaned"):
            await asyncio.to_thread(self.harness.saves.restore, active["save_backup"])
            active["saves_cleaned"] = True
            atomic_json(self.path(data["id"]), data)
        active["shared_life_unchanged"] = self._shared_hash() == active.get("shared_life_sha256")
        active["cleanup_verified"] = True
        atomic_json(self.path(data["id"]), data)

    async def advance(self, campaign_id, action="prepare"):
        # Cancelling to_thread does not stop a filesystem transaction. Keep the
        # operation alive until its journal is durable, then clean up its session.
        task = asyncio.create_task(self._advance(campaign_id, action))
        cancelled = None
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError as exc:
                cancelled = exc
                if task.done():
                    result = task.result()
                    break
        if cancelled:
            if result.get("active") and result.get("state") == "awaiting_world":
                cleanup = asyncio.create_task(self._advance(campaign_id, "abort"))
                while True:
                    try:
                        await asyncio.shield(cleanup)
                        break
                    except asyncio.CancelledError:
                        if cleanup.done():
                            cleanup.result()
                            break
            raise cancelled
        return result

    async def _advance(self, campaign_id, action="prepare"):
        self.config.require_development()
        if action not in {"prepare", "evaluate", "abort"}:
            raise ToolFailure("invalid_parameters", "Use prepare, evaluate or abort.")
        if self.lock.locked():
            raise ToolFailure("campaign_busy", "Another campaign operation is in progress.")
        async with self.lock:
            path = self.path(campaign_id)
            try:
                with portalocker.Lock(str(path.with_suffix(".lock")), mode="a", timeout=0):
                    data = self.status(campaign_id)
                    if digest(self.artifacts.path(data["checkpoint_id"])) != data["checkpoint_sha256"]:
                        raise ToolFailure("evidence_changed", "Campaign checkpoint changed.")
                    if action == "abort":
                        await self._cleanup(data)
                        data["state"] = "aborted"
                        atomic_json(path, data)
                        return data
                    if action == "evaluate":
                        if data["state"] != "awaiting_world" or not data["active"]:
                            raise ToolFailure("campaign_state", "Prepare a trial before evaluating it.")
                        active = data["active"]
                        if not self.harness.sessions.receipt or self.harness.sessions.receipt[
                            "session_id"
                        ] != active.get("session_id"):
                            raise ToolFailure(
                                "session_unavailable",
                                "Trial owner is gone; abort to recover original deployment and saves.",
                            )
                        data["state"] = "evaluating"
                        atomic_json(path, data)
                        failure = None
                        try:
                            result = await self.harness.run(
                                data["checkpoint_id"], "observe_idle", 2, 60, True
                            )
                            active.update(outcome=result["outcome"], evidence=result)
                        except BaseException as exc:
                            failure = exc
                            active.update(
                                outcome="inconclusive",
                                error=getattr(exc, "code", "trial_interrupted"),
                                evidence=getattr(exc, "details", None),
                            )
                        finally:
                            atomic_json(path, data)
                            await self._cleanup(data)
                        if not active["shared_life_unchanged"]:
                            active["outcome"] = "inconclusive"
                            active["error"] = "shared_life_changed"
                        data["trials"].append(active)
                        data["active"] = None
                        decision = choose_trial(data["revisions"], data["trials"], data["repeats"])
                        data.update(state=decision["state"], decision=decision)
                        atomic_json(path, data)
                        if isinstance(failure, asyncio.CancelledError):
                            raise failure
                        return data
                    if data["state"] != "ready" or data["active"]:
                        raise ToolFailure(
                            "campaign_state",
                            "Campaign is not ready; recover an interrupted trial with abort.",
                        )
                    decision = choose_trial(data["revisions"], data["trials"], data["repeats"])
                    if decision["state"] != "ready":
                        data.update(state=decision["state"], decision=decision)
                        atomic_json(path, data)
                        return data
                    revision = decision["revision"]
                    with game_lease(self.config.game):
                        require_closed()
                        original = installed(self.config)
                    data["state"] = "building"
                    atomic_json(path, data)
                    try:
                        build = data["builds"].get(revision)
                        if build is None:
                            build = await self.builds.build("Debug", "all", revision)
                            data["builds"][revision] = build
                            atomic_json(path, data)
                        doc = self.artifacts.get(build["artifact_id"])
                        if (
                            digest(self.artifacts.path(build["artifact_id"])) != build["sha256"]
                            or doc["kind"] != "build"
                            or doc["provenance"]["source_commit"] != revision
                            or not doc["data"]["summary"]["passed"]
                        ):
                            raise ToolFailure(
                                "build_failed", "Trial requires a successful unchanged build/test artifact."
                            )
                        folder = path.parent / uuid.uuid4().hex
                        folder.mkdir()
                        output = contained(
                            self.config.artifacts, self.config.artifacts / doc["data"]["build_directory"]
                        )
                        if installed(self.config) != original:
                            raise ToolFailure(
                                "deployment_changed", "Installation changed while the candidate built."
                            )
                        for name in original["files"]:
                            if name.endswith(".dll"):
                                src = output / name
                                if not src.is_file() or digest(src) != doc["data"]["binaries"].get(name):
                                    raise ToolFailure("build_changed", "Built runtime/loader hash differs.")
                                shutil.copyfile(src, folder / name)
                            else:
                                shutil.copyfile(self.config.game / name, folder / name)
                        parser, omitted_settings = candidate_settings(
                            (folder / "ddcoop.ini").read_text(encoding="utf-8-sig"),
                            self._settings_for_revision(revision),
                        )
                        with (folder / "ddcoop.ini").open("w", encoding="utf-8") as stream:
                            parser.write(stream)
                        atomic_json(
                            folder / "candidate.json",
                            {
                                "game_sha256": GAME_SHA256,
                                "source_commit": revision,
                                "files": {name: digest(folder / name) for name in original["files"]},
                            },
                        )
                        candidate = "regression_" + folder.name
                        self.config.settings.deployment_candidates[candidate] = str(folder)
                        active = {
                            "revision": revision,
                            "build": build,
                            "candidate": candidate,
                            "shared_life_sha256": self._shared_hash(),
                            "unsupported_current_settings": omitted_settings,
                        }
                        data.update(active=active, state="preparing")
                        atomic_json(path, data)
                        active["save_backup"] = (await asyncio.to_thread(self.harness.saves.backup))[
                            "backup_id"
                        ]
                        active["deployment"] = (await asyncio.to_thread(self.deployment.prepare, candidate))[
                            "receipt_id"
                        ]
                        atomic_json(path, data)
                        await asyncio.to_thread(self.deployment.apply, active["deployment"])
                        launched = await self.harness.launch(data["checkpoint_id"])
                        active["session_id"] = launched["session"]["session_id"]
                        data["state"] = "awaiting_world"
                        data["next_action"] = (
                            "Load Game through observed native menus, then evaluate this campaign. Evaluate runs readiness/scenario/cleanup automatically."
                        )
                        atomic_json(path, data)
                        return data
                    except BaseException as exc:
                        data.update(
                            state="recovery_required", error=getattr(exc, "code", "trial_interrupted")
                        )
                        atomic_json(path, data)
                        await self._cleanup(data)
                        data["state"] = "inconclusive"
                        atomic_json(path, data)
                        raise
            except portalocker.exceptions.LockException as exc:
                raise ToolFailure("campaign_busy", "Another server owns this campaign operation.") from exc
