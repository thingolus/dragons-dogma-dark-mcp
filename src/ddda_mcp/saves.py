"""Journaled local save transactions. Copyright (c) 2026 Thingolus. MIT."""

import os
import re
import shutil
import uuid

from .common import ToolFailure, atomic_json, contained, digest, identifier, read_json
from .config import Config
from .ownership import game_lease, require_closed

TERMINAL = {"completed", "rolled_back"}


def durable_copy(source, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
    if digest(source) != expected or digest(target) != expected:
        raise ToolFailure("save_changed", "Save changed while copying; original files are retained.")


class Saves:
    def __init__(self, config: Config):
        self.config = config

    @property
    def marker(self):
        return contained(self.config.game, self.config.game / ".ddda-mcp-save-restore.json")

    def roots(self):
        roots = [(self.config.root / value).resolve() for value in self.config.settings.save_roots]
        if not roots or any(not root.is_dir() for root in roots):
            raise ToolFailure("save_roots_missing", "Configure explicit existing save_roots.")
        if len(set(roots)) != len(roots):
            raise ToolFailure("invalid_save", "Save roots must be distinct.")
        return roots

    def folder(self, backup_id):
        base = self.config.artifacts / "save-backups"
        return contained(base, base / identifier(backup_id))

    def journal(self, receipt_id):
        base = self.config.artifacts / "save-restores"
        return contained(base, base / (identifier(receipt_id) + ".json"))

    def status(self):
        receipts = []
        for path in sorted((self.config.artifacts / "save-restores").glob("*.json")):
            value = read_json(path, 65536)
            if value["state"] not in TERMINAL:
                receipts.append({"receipt_id": value["receipt_id"], "state": value["state"]})
        marker = read_json(self.marker, 4096) if self.marker.exists() else None
        return {"pending": receipts, "game_blocked": bool(marker or receipts), "marker": marker}

    def require_clear(self):
        if self.status()["game_blocked"]:
            raise ToolFailure("save_recovery_required", "Recover the pending save restore before proceeding.")

    def _manifest(self, backup_id, roots):
        folder = self.folder(backup_id)
        value = read_json(folder / "manifest.json", 65536)
        if value.get("id") != backup_id or value.get("roots") != list(map(str, roots)):
            raise ToolFailure("backup_invalid", "Backup identity or configured save roots differ.")
        files = value.get("files", [])
        if not 1 <= len(files) <= 100:
            raise ToolFailure("backup_invalid", "Backup inventory is empty or too large.")
        seen, total = set(), 0
        for row in files:
            name, index = row.get("name"), row.get("root")
            if (
                type(index) is not int
                or not 0 <= index < len(roots)
                or not isinstance(name, str)
                or not re.fullmatch(r"[^\\/:]+\.sav", name, re.IGNORECASE)
                or not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))
            ):
                raise ToolFailure("backup_invalid", "Unexpected save path or hash.")
            key = (index, name.casefold())
            if key in seen:
                raise ToolFailure("backup_invalid", "Duplicate save path.")
            seen.add(key)
            source = contained(folder, folder / str(index) / name)
            target = roots[index] / name
            if target.is_symlink() or contained(roots[index], target) != target or not target.is_file():
                raise ToolFailure("save_missing", "Restore requires existing ordinary target saves.")
            if digest(source) != row["sha256"]:
                raise ToolFailure("backup_changed", "Save backup hash verification failed.")
            total += source.stat().st_size
        if total > 256 * 1024 * 1024:
            raise ToolFailure("save_limit", "Save inventory exceeds 256 MiB.")
        return files

    def _backup(self, roots, files=None):
        backup_id = uuid.uuid4().hex
        folder, records, total = self.folder(backup_id), [], 0
        paths = (
            [(row["root"], roots[row["root"]] / row["name"]) for row in files]
            if files
            else [(i, p) for i, root in enumerate(roots) for p in sorted(root.glob("*.sav"))]
        )
        for index, path in paths:
            source = contained(roots[index], path)
            if path.is_symlink() or not source.is_file():
                raise ToolFailure("invalid_save", "Save paths must be ordinary files.")
            total += source.stat().st_size
            if total > 256 * 1024 * 1024 or len(records) >= 100:
                raise ToolFailure("save_limit", "Save backup exceeds 100 files / 256 MiB.")
            sha = digest(source)
            durable_copy(source, folder / str(index) / path.name, sha)
            records.append({"root": index, "name": path.name, "sha256": sha})
        if not records:
            raise ToolFailure("saves_missing", "No .sav files exist in the configured save roots.")
        require_closed()
        atomic_json(
            folder / "manifest.json", {"id": backup_id, "roots": list(map(str, roots)), "files": records}
        )
        return {"backup_id": backup_id, "files_verified": len(records), "bytes": total}

    def backup(self):
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            self.require_clear()
            return self._backup(self.roots())

    def restore(self, backup_id):
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            self.require_clear()
            roots = self.roots()
            files = self._manifest(backup_id, roots)
            undo = self._backup(roots, files)["backup_id"]
            receipt = {
                "receipt_id": uuid.uuid4().hex,
                "state": "prepared",
                "restored_backup": backup_id,
                "previous_saves_backup": undo,
                "roots": list(map(str, roots)),
                "files_verified": len(files),
            }
            atomic_json(self.journal(receipt["receipt_id"]), receipt)
            # No target changes can occur until the global blocker is durable.
            atomic_json(
                self.marker,
                {"receipt_id": receipt["receipt_id"], "artifact_root": str(self.config.artifacts)},
            )
            return self._recover(receipt, "resume")

    def recover(self, receipt_id, action="rollback"):
        self.config.require_development()
        if action not in {"resume", "rollback"}:
            raise ToolFailure("invalid_parameters", "Recovery action must be resume or rollback.")
        with game_lease(self.config.game):
            require_closed()
            receipt = read_json(self.journal(receipt_id), 65536)
            if receipt.get("receipt_id") != receipt_id:
                raise ToolFailure("backup_invalid", "Restore receipt identity differs.")
            return self._recover(receipt, action)

    def _recover(self, receipt, action):
        roots = self.roots()
        if receipt["roots"] != list(map(str, roots)):
            raise ToolFailure("backup_invalid", "Recovery roots differ from the original transaction.")
        expected_marker = {"receipt_id": receipt["receipt_id"], "artifact_root": str(self.config.artifacts)}
        if self.marker.exists() and read_json(self.marker, 4096) != expected_marker:
            raise ToolFailure("save_recovery_required", "Another save transaction owns the recovery marker.")
        if receipt["state"] in TERMINAL:
            if self.marker.exists():
                self.marker.unlink()
            return receipt
        if receipt["state"] not in {"prepared", "restoring", "rolling_back"}:
            raise ToolFailure("backup_invalid", "Unknown transaction state.")
        if receipt["state"] == "rolling_back" and action == "resume":
            raise ToolFailure("recovery_direction", "Rollback has started; finish that rollback.")
        before = self._manifest(receipt["previous_saves_backup"], roots)
        after = self._manifest(receipt["restored_backup"], roots)
        old = {(r["root"], r["name"]): r["sha256"] for r in before}
        new = {(r["root"], r["name"]): r["sha256"] for r in after}
        if old.keys() != new.keys():
            raise ToolFailure("backup_invalid", "Undo and restore inventories differ.")
        desired = new if action == "resume" else old
        backup_id = receipt["restored_backup"] if action == "resume" else receipt["previous_saves_backup"]
        # Verify the entire set before touching any file. Unknown external edits are never overwritten.
        for index, name in old:
            if digest(roots[index] / name) not in {old[index, name], new[index, name]}:
                raise ToolFailure(
                    "save_changed", "Save differs from both journaled states; preserve and reconcile it."
                )
        atomic_json(self.marker, expected_marker)
        receipt["state"] = "restoring" if action == "resume" else "rolling_back"
        atomic_json(self.journal(receipt["receipt_id"]), receipt)
        staged = []
        for (index, name), sha in desired.items():
            target = roots[index] / name
            temp = target.with_name(f".ddda-mcp-{receipt['receipt_id']}-{name}.tmp")
            if temp.exists():
                if temp.is_symlink() or not temp.is_file():
                    raise ToolFailure("save_changed", "Unrecognized staging file; refusing to overwrite it.")
                # This exact staging path belongs to the durable receipt. A
                # crash during copy may leave any prefix of the intended bytes.
                temp.unlink()
            durable_copy(self.folder(backup_id) / str(index) / name, temp, sha)
            staged.append((index, name, temp, sha))
        for index, name, temp, sha in staged:
            require_closed()
            target = roots[index] / name
            if target.is_symlink() or digest(target) not in {old[index, name], new[index, name]}:
                raise ToolFailure("save_changed", "Save changed during recovery; journal retained.")
            self._replace(temp, target)
            if digest(target) != sha:
                raise ToolFailure("copy_failed", "Replaced save hash differs; journal retained.")
        receipt["state"] = "completed" if action == "resume" else "rolled_back"
        atomic_json(self.journal(receipt["receipt_id"]), receipt)
        self.marker.unlink()
        return receipt

    @staticmethod
    def _replace(temp, target):
        os.replace(temp, target)
