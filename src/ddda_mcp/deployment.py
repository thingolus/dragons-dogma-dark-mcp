"""Receipt-based deployment with file ownership and crash-recoverable backups."""

import configparser
import os
import shutil
import uuid
from pathlib import Path

import pefile

from .binary import Binary
from .common import ToolFailure, atomic_json, contained, digest, identifier, read_json, utc_now
from .config import GAME_SHA256, Config
from .ownership import game_lease, require_closed

LOADERS = {"dinput8.dll", "xinput1_3.dll"}
PAYLOAD_NAMES = LOADERS | {"ddcoop_runtime.dll", "ddcoop.ini"}
MANIFEST_NAME = "ddcoop-deployment.json"


def verify_payload(root: Path, files: dict) -> None:
    """A candidate is deployable only if it has the x86 DLL/API boundary we use."""
    for name in files:
        if not name.endswith(".dll"):
            continue
        try:
            with pefile.PE(str(contained(root, root / name))) as pe:
                if pe.FILE_HEADER.Machine != 0x14C or not pe.FILE_HEADER.Characteristics & 0x2000:
                    raise ToolFailure("candidate_invalid", f"Expected an x86 DLL: {name}")
                exports = {
                    e.name.decode("ascii", errors="replace")
                    for e in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", [])
                    if e.name
                }
                required = (
                    {"CoopInitialize", "CoopGetStatus", "OfflineState"}
                    if name == "ddcoop_runtime.dll"
                    else {"DirectInput8Create" if name == "dinput8.dll" else "XInputGetState"}
                )
                if not required <= exports:
                    raise ToolFailure("candidate_invalid", f"Required exports are missing: {name}")
        except pefile.PEFormatError as exc:
            raise ToolFailure("candidate_invalid", f"Malformed DLL: {name}") from exc


def verify_offline_settings(root: Path) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string((root / "ddcoop.ini").read_text(encoding="utf-8-sig"))
        if parser.getint("coop", "online_mode", fallback=-1) != 0:
            raise ToolFailure("offline_required", "Research sessions require explicit [coop] online_mode=0.")
    except (configparser.Error, ValueError, UnicodeError) as exc:
        raise ToolFailure("settings_invalid", "Cannot validate offline research settings.") from exc


def installed(config: Config) -> dict:
    """Validate the owned research installation without modifying it."""
    path = contained(config.game, config.game / MANIFEST_NAME)
    if not path.is_file():
        raise ToolFailure(
            "deployment_unowned", "An owned ddcoop-deployment.json research installation is required."
        )
    manifest = read_json(path, 65536)
    files = manifest.get("files", {})
    if (
        set(files) - PAYLOAD_NAMES
        or len(set(files) & LOADERS) != 1
        or not {"ddcoop_runtime.dll", "ddcoop.ini"} <= set(files)
    ):
        raise ToolFailure("deployment_invalid", "Unexpected deployment file inventory.")
    if (
        manifest.get("exe_sha256") != GAME_SHA256
        or str(config.game).lower() != str(Path(manifest.get("game", "")).resolve()).lower()
    ):
        raise ToolFailure("deployment_invalid", "Deployment game identity differs from this installation.")
    for name, expected in files.items():
        file = contained(config.game, config.game / name)
        if not file.is_file() or digest(file) != expected:
            raise ToolFailure(
                "deployment_changed", f"Installed file does not match ownership receipt: {name}"
            )
    for loader in LOADERS - set(files):
        if (config.game / loader).exists():
            raise ToolFailure("foreign_loader", f"Additional loader exists: {loader}")
    return manifest


class Deployment:
    def __init__(self, config: Config):
        self.config = config
        self.root = config.artifacts / "deployments"

    def folder(self, receipt_id: str):
        return contained(self.root, self.root / identifier(receipt_id))

    def candidate(self, name: str):
        value = self.config.settings.deployment_candidates.get(name)
        if value is None:
            raise ToolFailure(
                "candidate_unknown", "Select a named deployment_candidates entry from local config."
            )
        root = (self.config.root / value).resolve()
        manifest = read_json(root / "candidate.json", 65536)
        files = manifest.get("files", {})
        if (
            manifest.get("game_sha256") != GAME_SHA256
            or len(set(files) & LOADERS) != 1
            or set(files) - PAYLOAD_NAMES
        ):
            raise ToolFailure(
                "candidate_invalid", "Candidate must identify the supported game and one loader."
            )
        if len(files) != 3 or not {"ddcoop_runtime.dll", "ddcoop.ini"} <= set(files):
            raise ToolFailure(
                "candidate_invalid", "Candidate must contain loader, runtime and settings hashes."
            )
        for filename, expected in files.items():
            file = contained(root, root / filename)
            if not file.is_file() or digest(file) != expected:
                raise ToolFailure("candidate_changed", f"Candidate hash mismatch: {filename}")
        verify_payload(root, files)
        verify_offline_settings(root)
        return root, manifest

    def prepare(self, candidate_name: str) -> dict:
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            info = Binary(self.config).inventory()
            if info["sha256"] != GAME_SHA256:
                raise ToolFailure("unsupported_build", "Deployment requires the supported executable.")
            _, candidate = self.candidate(candidate_name)
            old = installed(self.config) if (self.config.game / MANIFEST_NAME).exists() else None
            if old and set(old["files"]) != set(candidate["files"]):
                raise ToolFailure(
                    "migration_required", "Loader migration must use the co-op migration workflow first."
                )
            if not old and any(
                (self.config.game / name).exists() for name in PAYLOAD_NAMES | {"ddcoop-install.json"}
            ):
                raise ToolFailure(
                    "foreign_files", "Refusing to overwrite an installation without this research manifest."
                )
            names = sorted(candidate["files"]) + [MANIFEST_NAME]
            before = {
                name: digest(self.config.game / name) if (self.config.game / name).exists() else None
                for name in names
            }
            receipt_id = uuid.uuid4().hex
            receipt = {
                "id": receipt_id,
                "state": "prepared",
                "created_at": utc_now(),
                "candidate": candidate_name,
                "candidate_manifest": candidate,
                "before": before,
                "written": [],
                "game": str(self.config.game),
            }
            atomic_json(self.folder(receipt_id) / "receipt.json", receipt)
            return {
                "receipt_id": receipt_id,
                "state": "prepared",
                "files": candidate["files"],
                "before": before,
                "game_sha256": GAME_SHA256,
            }

    def _read(self, receipt_id: str) -> dict:
        receipt = read_json(self.folder(receipt_id) / "receipt.json", 65536)
        if receipt.get("id") != receipt_id or receipt.get("game") != str(self.config.game):
            raise ToolFailure("receipt_invalid", "Receipt identity differs.")
        names = set(receipt.get("before", {}))
        if names - (PAYLOAD_NAMES | {MANIFEST_NAME}) or MANIFEST_NAME not in names:
            raise ToolFailure("receipt_invalid", "Receipt includes unowned paths.")
        return receipt

    def _write_file(self, name, source, expected_before):
        require_closed()
        target = contained(self.config.game, self.config.game / name)
        actual = digest(target) if target.exists() else None
        if actual != expected_before:
            raise ToolFailure("deployment_changed", f"File changed since preparation: {name}")
        temp = contained(self.config.game, self.config.game / (".ddda-mcp-" + uuid.uuid4().hex + ".tmp"))
        try:
            with temp.open("xb") as out, source.open("rb") as inp:
                shutil.copyfileobj(inp, out)
                out.flush()
                os.fsync(out.fileno())
            if digest(temp) != digest(source):
                raise ToolFailure("copy_failed", "Temporary payload verification failed.")
            require_closed()
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def apply(self, receipt_id: str) -> dict:
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            receipt = self._read(receipt_id)
            if receipt["state"] == "applied":
                installed(self.config)
                return {"receipt_id": receipt_id, "state": "applied", "already_applied": True}
            if receipt["state"] != "prepared":
                raise ToolFailure(
                    "outcome_unknown", "Interrupted/failed apply requires rollback, not replay."
                )
            if Binary(self.config).inventory()["sha256"] != GAME_SHA256:
                raise ToolFailure("unsupported_build", "Executable changed since preparation.")
            root, candidate = self.candidate(receipt["candidate"])
            if candidate != receipt["candidate_manifest"]:
                raise ToolFailure("candidate_changed", "Candidate changed since preparation.")
            folder = self.folder(receipt_id)
            backup = folder / "backup"
            backup.mkdir(exist_ok=True)
            for name, expected in receipt["before"].items():
                target = contained(self.config.game, self.config.game / name)
                if (digest(target) if target.exists() else None) != expected:
                    raise ToolFailure("deployment_changed", f"File changed: {name}")
                if expected is not None:
                    shutil.copyfile(target, backup / name)
                    if digest(backup / name) != expected:
                        raise ToolFailure("backup_failed", "Backup verification failed.")
            new_manifest = {
                "version": 1,
                "kind": "internal research, not release",
                "game": str(self.config.game),
                "exe_sha256": GAME_SHA256,
                "files": candidate["files"],
                "mcp_receipt": receipt_id,
            }
            source_commit = candidate.get("source_commit")
            if source_commit is not None:
                import re

                if not isinstance(source_commit, str) or not re.fullmatch(r"[0-9a-f]{40}", source_commit):
                    raise ToolFailure(
                        "candidate_invalid", "Candidate source commit must be an immutable identity."
                    )
                new_manifest["source_commit"] = source_commit
            atomic_json(folder / "new-manifest.json", new_manifest)
            after = {**candidate["files"], MANIFEST_NAME: digest(folder / "new-manifest.json")}
            receipt.update(state="applying", after=after)
            atomic_json(folder / "receipt.json", receipt)
            # Journal desired hashes before each replacement; rollback also reconciles
            # replacements that completed just before a process crash.
            for name in receipt["before"]:
                source = (
                    folder / "new-manifest.json" if name == MANIFEST_NAME else contained(root, root / name)
                )
                if digest(source) != after[name]:
                    raise ToolFailure("candidate_changed", "Payload changed during apply; rollback required.")
                self._write_file(name, source, receipt["before"][name])
                receipt["written"].append(name)
                atomic_json(folder / "receipt.json", receipt)
            installed(self.config)
            receipt["state"] = "applied"
            atomic_json(folder / "receipt.json", receipt)
            return {"receipt_id": receipt_id, "state": "applied", "files": after}

    def rollback(self, receipt_id: str) -> dict:
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            receipt = self._read(receipt_id)
            if receipt["state"] == "rolled_back":
                return {"receipt_id": receipt_id, "state": "rolled_back", "already_rolled_back": True}
            if receipt["state"] not in {"applying", "applied", "rolling_back"}:
                raise ToolFailure(
                    "invalid_state", "Only an applied or interrupted deployment can be rolled back."
                )
            folder = self.folder(receipt_id)
            # Verify all current files and backup bytes before changing anything.
            for name, before in receipt["before"].items():
                path = contained(self.config.game, self.config.game / name)
                actual = digest(path) if path.exists() else None
                if actual not in {before, receipt["after"][name]}:
                    raise ToolFailure(
                        "deployment_changed", f"Refusing to remove or overwrite changed file: {name}"
                    )
                if before is not None and digest(contained(folder, folder / "backup" / name)) != before:
                    raise ToolFailure("backup_changed", f"Backup hash differs: {name}")
            receipt["state"] = "rolling_back"
            atomic_json(folder / "receipt.json", receipt)
            for name, before in receipt["before"].items():
                require_closed()
                path = contained(self.config.game, self.config.game / name)
                actual = digest(path) if path.exists() else None
                if actual == before:
                    continue
                if before is None:
                    if actual != receipt["after"][name]:
                        raise ToolFailure("deployment_changed", "File changed during rollback.")
                    path.unlink()
                else:
                    self._write_file(name, folder / "backup" / name, receipt["after"][name])
            receipt["state"] = "rolled_back"
            atomic_json(folder / "receipt.json", receipt)
            return {"receipt_id": receipt_id, "state": "rolled_back", "verified_originals": receipt["before"]}
