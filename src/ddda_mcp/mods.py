"""Private mod profiles, declared conflicts and journaled installation. MIT, Thingolus."""

import hashlib
import json
import os
import shutil
import uuid
import zipfile

from .assets import relative_name
from .common import ToolFailure, atomic_json, contained, digest, identifier, read_json
from .ownership import game_lease, require_closed
from .saves import Saves

LOADERS = {"dinput8.dll", "xinput1_3.dll", "dxgi.dll", "d3d9.dll"}


def target_name(value):
    name = relative_name(value)
    if not (
        (name.startswith("nativePC/") and name.lower().endswith(".arc"))
        or ("/" not in name and name.lower().endswith((".dll", ".ini")))
    ):
        raise ToolFailure("mod_target", "Profiles support nativePC ARC files and root DLL/INI files.")
    return name


def require_profile_clear(config, allow_applied=False):
    marker = config.game / ".ddda-mcp-profile.json"
    if marker.exists():
        data = read_json(marker, 4096)
        if not allow_applied or data.get("state") != "applied":
            raise ToolFailure(
                "profile_recovery_required",
                "Restore the active mod profile before changing installation state.",
            )
        root = config.artifacts / "profiles"
        if data.get("root") != str(root):
            raise ToolFailure("profile_owner", "Launch through the project that owns this profile.")
        folder = contained(root, root / identifier(data["id"]))
        journal = read_json(folder / "journal.json")
        if journal.get("state") != "applied" or journal.get("id") != data["id"]:
            raise ToolFailure("profile_recovery_required", "Profile journal and marker disagree.")
        for row in journal["files"]:
            path = contained(config.game, config.game / target_name(row["target"]))
            if (digest(path) if path.exists() else None) != row["new"]:
                raise ToolFailure("profile_changed", "Active profile payload differs; restore before launch.")


class Mods:
    def __init__(self, config, artifacts, assets):
        self.config, self.artifacts, self.assets = config, artifacts, assets
        self.root = config.artifacts / "profiles"
        self.marker = config.game / ".ddda-mcp-profile.json"

    def register(self, label, files, hooks=None, requires=None):
        self.config.require_development()
        hooks, requires = hooks or [], requires or []
        if (
            not label.strip()
            or len(label) > 120
            or not 1 <= len(files) <= 128
            or len(hooks) > 64
            or len(requires) > 32
        ):
            raise ToolFailure("mod_invalid", "Use a label and bounded files, hooks and dependencies.")
        names, rows = set(), []
        for row in files:
            name = target_name(row["target"])
            if name.casefold() in names:
                raise ToolFailure("mod_invalid", "Duplicate case-insensitive target.")
            names.add(name.casefold())
            data, raw = self.assets.read(row["asset_id"])
            if name.lower().endswith(".arc"):
                from .assets import arc_table

                arc_table(raw)
            elif name.lower().endswith(".dll"):
                import pefile

                try:
                    with pefile.PE(data=raw, fast_load=True) as pe:
                        if pe.FILE_HEADER.Machine != 0x14C or not pe.FILE_HEADER.Characteristics & 0x2000:
                            raise ValueError("not x86")
                except Exception as exc:
                    raise ToolFailure("mod_invalid", "DLL must be a valid x86 PE.") from exc
            rows.append({"target": name, "asset_id": row["asset_id"], "sha256": data["sha256"]})
        for required in requires:
            if self.artifacts.get(required)["kind"] != "mod_definition":
                raise ToolFailure("mod_invalid", "Dependency is not a registered mod.")
        if any(not isinstance(h, str) or not 1 <= len(h) <= 120 for h in hooks):
            raise ToolFailure("mod_invalid", "Hooks must be bounded named declarations.")
        return self.artifacts.put(
            "mod_definition",
            {
                "label": label,
                "files": rows,
                "hooks": sorted(set(hooks)),
                "requires": sorted(set(requires)),
                "summary": {"label": label, "files": len(rows)},
            },
            {"evidence_class": "declared_mod", "creator": "Thingolus"},
        )

    def import_named(self, source_name):
        self.config.require_development()
        configured = self.config.settings.mod_sources.get(source_name)
        if not configured:
            raise ToolFailure("mod_source", "Select a trusted mod_sources entry from local configuration.")
        root = (self.config.root / configured).resolve()
        manifest = read_json(root / "mod.json", 65536)
        files = []
        if not 1 <= len(manifest["files"]) <= 128:
            raise ToolFailure("mod_invalid", "Mod inventory exceeds bounds.")
        for row in manifest["files"]:
            path = contained(root, root / relative_name(row["source"]))
            if path.stat().st_size > 512 * 1024 * 1024 or digest(path) != row["sha256"]:
                raise ToolFailure("mod_changed", "Imported file differs from its manifest.")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ToolFailure("mod_changed", "Imported file changed while reading.")
            blob = self.assets.blob(raw, {"imported_mod": source_name})
            files.append({"target": row["target"], "asset_id": blob["artifact_id"]})
        return self.register(manifest["label"], files, manifest.get("hooks"), manifest.get("requires"))

    def merge_archives(self, left_id, right_id):
        left, _ = self.assets.read(left_id, "asset_archive")
        right, _ = self.assets.read(right_id, "asset_archive")
        if not left.get("base_id") or left.get("base_sha256") != right.get("base_sha256"):
            raise ToolFailure("mod_conflict", "Archive changes do not share the same recorded base.")
        base, _ = self.assets.read(left["base_id"], "asset_archive")
        if base["sha256"] != left["base_sha256"]:
            raise ToolFailure("mod_changed", "Archive base changed.")
        by_index = {r["index"]: r for r in left["changes"]}
        for change in right["changes"]:
            previous = by_index.get(change["index"])
            if previous and previous["after"] != change["after"]:
                a, _ = self.assets.read(previous["replacement"])
                b, _ = self.assets.read(change["replacement"])
                if (
                    a.get("format") != "gmd_unlabelled_v1"
                    or b.get("format") != a.get("format")
                    or not a.get("base_id")
                    or a.get("base_sha256") != b.get("base_sha256")
                ):
                    raise ToolFailure("mod_conflict", "Both mods replace the same opaque archive entry.")
                edits = {e["index"]: e for e in a["edits"]}
                for edit in b["edits"]:
                    if edit["index"] in edits and edits[edit["index"]] != edit:
                        raise ToolFailure("mod_conflict", "Both mods change the same text index differently.")
                    edits[edit["index"]] = edit
                merged = self.assets.edit_text(a["base_id"], list(edits.values()))
                blob, _ = self.assets.read(merged["artifact_id"])
                change = {**change, "replacement": merged["artifact_id"], "after": blob["sha256"]}
            by_index[change["index"]] = change
        return self.assets.repack(
            left["base_id"],
            [
                {"index": r["index"], "artifact_id": r["replacement"], "expected_sha256": r["before"]}
                for r in by_index.values()
            ],
        )

    def compose(self, label, mod_ids, disable_loaders=None):
        self.config.require_development()
        disable_loaders = disable_loaders or []
        if (
            not 1 <= len(mod_ids) <= 16
            or len(set(mod_ids)) != len(mod_ids)
            or not label.strip()
            or len(label) > 120
        ):
            raise ToolFailure("mod_invalid", "Select 1–16 distinct mods and a label.")
        if set(disable_loaders) - LOADERS:
            raise ToolFailure("mod_invalid", "Only named proxy loaders can be temporarily disabled.")
        files, hooks, conflicts, mods = {}, {}, [], []
        for ident in mod_ids:
            doc = self.artifacts.get(ident)
            if doc["kind"] != "mod_definition":
                raise ToolFailure("mod_invalid", "Expected mod definitions.")
            data = doc["data"]
            mods.append({"id": ident, "sha256": digest(self.artifacts.path(ident)), "label": data["label"]})
            if set(data["requires"]) - set(mod_ids):
                conflicts.append({"mod": ident, "reason": "missing_dependency"})
            for hook in data["hooks"]:
                if hook in hooks:
                    conflicts.append(
                        {"hook": hook, "mods": [hooks[hook], ident], "reason": "declared_hook_overlap"}
                    )
                hooks[hook] = ident
            for row in data["files"]:
                asset, _ = self.assets.read(row["asset_id"])
                if asset["sha256"] != row["sha256"]:
                    raise ToolFailure("mod_changed", "Registered asset changed.")
                key = row["target"].casefold()
                if key in files and files[key]["sha256"] != row["sha256"]:
                    try:
                        merged = self.merge_archives(files[key]["asset_id"], row["asset_id"])
                        blob, _ = self.assets.read(merged["artifact_id"])
                        files[key] = {**row, "asset_id": merged["artifact_id"], "sha256": blob["sha256"]}
                    except ToolFailure as exc:
                        conflicts.append({"target": row["target"], "reason": exc.code, "message": str(exc)})
                else:
                    files[key] = row
        for loader in disable_loaders:
            if loader in files:
                conflicts.append({"target": loader, "reason": "enabled_and_disabled"})
        summary = {"label": label, "mods": len(mod_ids), "files": len(files), "compatible": not conflicts}
        receipt = self.artifacts.put(
            "mod_profile",
            {
                "label": label,
                "mods": mods,
                "files": list(files.values()),
                "disable_loaders": sorted(set(disable_loaders)),
                "conflicts": conflicts,
                "summary": summary,
                "limitations": "Static file/declared-hook compatibility only. Undeclared hooks and gameplay conflicts require trials.",
            },
            {"evidence_class": "static_mod_compatibility"},
        )
        return {**receipt, "summary": summary, "conflicts": conflicts}

    def status(self):
        return read_json(self.marker, 4096) if self.marker.exists() else {"state": "clear"}

    def apply(self, profile_id, owner_id=None):
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            require_profile_clear(self.config)
            Saves(self.config).require_clear()
            doc = self.artifacts.get(profile_id)
            if doc["kind"] != "mod_profile" or not doc["data"]["summary"]["compatible"]:
                raise ToolFailure("mod_conflict", "Profile has unresolved conflicts.")
            data = doc["data"]
            for mod in data["mods"]:
                if digest(self.artifacts.path(mod["id"])) != mod["sha256"]:
                    raise ToolFailure("mod_changed", "Mod definition changed after profile composition.")
            ident = uuid.uuid4().hex
            folder = self.root / ident
            folder.mkdir(parents=True)
            rows = []
            for i, row in enumerate(
                [
                    *data["files"],
                    *[{"target": n, "asset_id": None, "sha256": None} for n in data["disable_loaders"]],
                ]
            ):
                name = target_name(row["target"])
                target = contained(self.config.game, self.config.game / name)
                old = digest(target) if target.exists() else None
                if old:
                    shutil.copyfile(target, folder / f"{i}.original")
                    if digest(folder / f"{i}.original") != old:
                        raise ToolFailure("mod_changed", "Original changed during backup.")
                if row["asset_id"]:
                    blob, raw = self.assets.read(row["asset_id"])
                    if blob["sha256"] != row["sha256"]:
                        raise ToolFailure("mod_changed", "Profile asset changed.")
                    (folder / f"{i}.candidate").write_bytes(raw)
                rows.append({"target": name, "old": old, "new": row["sha256"], "index": i})
            journal = {
                "id": ident,
                "profile_id": profile_id,
                "owner_id": owner_id,
                "state": "prepared",
                "files": rows,
            }
            atomic_json(folder / "journal.json", journal)
            atomic_json(
                self.marker,
                {
                    "id": ident,
                    "root": str(self.root),
                    "state": "applying",
                    "profile_id": profile_id,
                    "owner_id": owner_id,
                },
            )
            for row in rows:
                self._replace(folder, row, "new")
            journal["state"] = "applied"
            atomic_json(folder / "journal.json", journal)
            atomic_json(
                self.marker,
                {
                    "id": ident,
                    "root": str(self.root),
                    "state": "applied",
                    "profile_id": profile_id,
                    "owner_id": owner_id,
                },
            )
            return {"id": ident, "state": "applied", "files": len(rows)}

    def _replace(self, folder, row, direction):
        target = contained(self.config.game, self.config.game / target_name(row["target"]))
        actual = digest(target) if target.exists() else None
        if actual not in {row["old"], row["new"]}:
            raise ToolFailure("mod_changed", "Installation has an unknown edit; preserve it before recovery.")
        expected = row[direction]
        if actual == expected:
            return
        if expected is None:
            target.unlink()
        else:
            source = folder / f"{row['index']}.{'original' if direction == 'old' else 'candidate'}"
            if digest(source) != expected:
                raise ToolFailure("mod_changed", "Recovery payload hash differs.")
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(target.name + ".mcp-" + folder.name)
            if staged.exists():
                # A crash may leave an unfinished staging file; it is not an installed original.
                if staged.is_symlink():
                    raise ToolFailure("mod_changed", "Unexpected linked staging file.")
                staged.unlink()
            with source.open("rb") as inp, staged.open("xb") as out:
                shutil.copyfileobj(inp, out)
                out.flush()
                os.fsync(out.fileno())
            if digest(staged) != expected:
                raise ToolFailure("mod_changed", "Staged payload hash differs.")
            os.replace(staged, target)
        if (digest(target) if target.exists() else None) != expected:
            raise ToolFailure("mod_changed", "Installation replacement did not verify.")

    def restore(self):
        self.config.require_development()
        with game_lease(self.config.game):
            require_closed()
            marker = self.status()
            if marker["state"] == "clear":
                return {"state": "clear"}
            if marker["root"] != str(self.root):
                raise ToolFailure("profile_owner", "Use the project that owns this profile journal.")
            folder = contained(self.root, self.root / identifier(marker["id"]))
            journal = read_json(folder / "journal.json")
            if journal["id"] != marker["id"]:
                raise ToolFailure("profile_invalid", "Journal identity differs.")
            atomic_json(self.marker, {**marker, "state": "restoring"})
            for row in reversed(journal["files"]):
                self._replace(folder, row, "old")
            journal["state"] = "restored"
            atomic_json(folder / "journal.json", journal)
            self.marker.unlink()
            return {"state": "restored", "id": journal["id"], "verified": True}

    def package(self, profile_id):
        self.config.require_development()
        doc = self.artifacts.get(profile_id)
        if doc["kind"] != "mod_profile" or not doc["data"]["summary"]["compatible"]:
            raise ToolFailure("mod_conflict", "Only compatible profiles can be packaged.")
        path = self.root / (profile_id + ".zip")
        self.root.mkdir(parents=True, exist_ok=True)
        files = {
            "profile.json": json.dumps(doc, sort_keys=True, indent=2).encode(),
            "CREDITS.txt": b"Package assembled by Dragons Dogma Dark MCP. Creator: Thingolus.\nThird-party and game asset rights remain with their owners.\n",
        }
        for row in doc["data"]["files"]:
            blob, raw = self.assets.read(row["asset_id"])
            if blob["sha256"] != row["sha256"]:
                raise ToolFailure("mod_changed", "Profile asset changed.")
            files["payload/" + target_name(row["target"])] = raw
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(files):
                info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, files[name])
        return {
            "path": str(path),
            "sha256": digest(path),
            "private": True,
            "distribution": "Local test package; may contain proprietary game assets. Not a public release artifact.",
        }
