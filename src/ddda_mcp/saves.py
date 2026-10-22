"""Explicit local save backup/restore; never discovers or modifies account settings."""

import os
import shutil
import uuid

from .common import ToolFailure, atomic_json, contained, digest, identifier, read_json
from .config import Config
from .ownership import game_lease, require_closed


class Saves:
    def __init__(self, config: Config):
        self.config = config

    def roots(self):
        roots = [(self.config.root / value).resolve() for value in self.config.settings.save_roots]
        if not roots or any(not root.is_dir() for root in roots):
            raise ToolFailure(
                "save_roots_missing", "Configure explicit existing save_roots before using save tools."
            )
        return roots

    def folder(self, backup_id):
        base = self.config.artifacts / "save-backups"
        return contained(base, base / identifier(backup_id))

    def backup(self) -> dict:
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            roots = self.roots()
            backup_id = uuid.uuid4().hex
            folder = self.folder(backup_id)
            records = []
            total = 0
            for index, root in enumerate(roots):
                for original in sorted(root.glob("*.sav")):
                    source = contained(root, original)
                    if not source.is_file() or original.is_symlink():
                        raise ToolFailure("invalid_save", "Save paths must be ordinary files.")
                    total += source.stat().st_size
                    if total > 256 * 1024 * 1024 or len(records) >= 100:
                        raise ToolFailure("save_limit", "Save backup exceeds 100 files / 256 MiB.")
                    sha = digest(source)
                    target = folder / str(index) / original.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    if digest(source) != sha or digest(target) != sha:
                        raise ToolFailure("save_changed", "Save changed while it was being backed up.")
                    records.append({"root": index, "name": original.name, "sha256": sha})
            if not records:
                raise ToolFailure("saves_missing", "No .sav files exist in the configured save roots.")
            require_closed()
            atomic_json(
                folder / "manifest.json", {"id": backup_id, "roots": list(map(str, roots)), "files": records}
            )
            return {"backup_id": backup_id, "files_verified": len(records), "bytes": total}

    def restore(self, backup_id: str) -> dict:
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            roots = self.roots()
            folder = self.folder(backup_id)
            manifest = read_json(folder / "manifest.json", 65536)
            if manifest.get("id") != backup_id or manifest.get("roots") != list(map(str, roots)):
                raise ToolFailure("backup_invalid", "Backup identity or configured save roots differ.")
            files = manifest.get("files", [])
            if not 1 <= len(files) <= 100:
                raise ToolFailure("backup_invalid", "Backup inventory is empty or too large.")
            for record in files:
                name, index = record["name"], record["root"]
                if (
                    not 0 <= index < len(roots)
                    or "/" in name
                    or "\\" in name
                    or not name.lower().endswith(".sav")
                ):
                    raise ToolFailure("backup_invalid", "Backup contains an unexpected save path.")
                source = contained(folder, folder / str(index) / name)
                target = contained(roots[index], roots[index] / name)
                if not target.is_file():
                    raise ToolFailure(
                        "save_missing",
                        "Restore requires existing target saves so the operation can be undone.",
                    )
                if digest(source) != record["sha256"]:
                    raise ToolFailure("backup_changed", "Save backup hash verification failed.")
            # Preserve the current saves before restoring, so the restore itself is reversible.
            undo_id = uuid.uuid4().hex
            undo = self.folder(undo_id)
            undo_records = []
            for record in files:
                index, name = record["root"], record["name"]
                target = contained(roots[index], roots[index] / name)
                if target.exists():
                    before = digest(target)
                    copy = undo / str(index) / name
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(target, copy)
                    if digest(copy) != before or digest(target) != before:
                        raise ToolFailure("save_changed", "Current save changed during restore preparation.")
                    undo_records.append({"root": index, "name": name, "sha256": before})
            atomic_json(
                undo / "manifest.json", {"id": undo_id, "roots": list(map(str, roots)), "files": undo_records}
            )
            for record in files:
                require_closed()
                index, name = record["root"], record["name"]
                target = contained(roots[index], roots[index] / name)
                temp = target.with_name(".ddda-mcp-" + uuid.uuid4().hex + ".tmp")
                try:
                    expected_current = next(
                        r["sha256"] for r in undo_records if r["root"] == index and r["name"] == name
                    )
                    if digest(target) != expected_current:
                        raise ToolFailure(
                            "save_changed", "Save changed during restore; refusing to overwrite it."
                        )
                    shutil.copyfile(folder / str(index) / name, temp)
                    if digest(temp) != record["sha256"]:
                        raise ToolFailure("copy_failed", "Restored save staging failed.")
                    require_closed()
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
            return {
                "restored_backup": backup_id,
                "files_verified": len(files),
                "previous_saves_backup": undo_id,
                "scope": "Only named files restored; other saves and Steam Cloud settings are unchanged.",
            }
