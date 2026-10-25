"""Typed general-modding MCP tools. Copyright (c) 2026 Thingolus. MIT."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class TextEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, le=100000)
    expected: str = Field(max_length=65536)
    text: str = Field(max_length=65536)


class Replacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, le=8191)
    artifact_id: str
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(max_length=240)
    asset_id: str


class SuiteCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture_id: str
    plan_id: str | None = None
    recipe: Literal[
        "observe_idle", "movement_pair", "attack_pair", "jump_pair", "menu_roundtrip", "interaction_menu"
    ] = "observe_idle"
    predicate: Literal["scenario", "damage", "healed", "revived", "inventory_gain"] = "scenario"
    role: Literal[0, 1] = 0
    item_id: int | None = Field(default=None, ge=-32768, le=32767)
    minimum: float = Field(default=1, gt=0, le=1000000, allow_inf_nan=False)


def register_tools(mcp, app):
    from .server import Read, Replace, Result, Write

    @mcp.tool(annotations=Write)
    async def capture_native_sdk_events(seconds: Annotated[float, Field(ge=0.2, le=10)] = 2) -> Result:
        """Capture bounded native SDK events on the owned standalone game; retain drops/errors and verified hook cleanup."""
        return await app.invoke("capture_native_sdk_events", app.sdk.events, app.sessions, seconds)

    @mcp.tool(annotations=Write)
    async def compare_behavior(
        before_id: str,
        after_id: str,
        feature: str,
        terms: Annotated[list[str] | None, Field(max_length=8)] = None,
        ghidra_ids: Annotated[list[str] | None, Field(max_length=8)] = None,
    ) -> Result:
        """Compare compatible gameplay captures and link field differences to source candidates and analyzed Ghidra references."""
        return await app.invoke(
            "compare_behavior", app.behaviors.compare, before_id, after_id, feature, terms, ghidra_ids
        )

    @mcp.tool(annotations=Write)
    async def capture_behavior_experiment(
        action: str, role: Literal[0, 1] = 0, duration_ms: Annotated[int, Field(ge=50, le=1000)] = 350
    ) -> Result:
        """Capture world before, a fixed action plus health events, then world after; release input and preserve partial evidence."""
        return await app.invoke(
            "capture_behavior_experiment", app.behaviors.experiment, action, role, duration_ms
        )

    @mcp.tool(annotations=Read)
    async def ddda_sdk_catalog() -> Result:
        """Describe the versioned copied-value SDK and standalone versus co-op backend capabilities."""
        return await app.invoke("ddda_sdk_catalog", app.sdk.catalog)

    @mcp.tool(annotations=Write)
    async def generate_ddda_sdk() -> Result:
        """Generate C++ interfaces, schema, contract test and isolated minimal offline bridge sources with provenance and licenses."""
        return await app.invoke("generate_ddda_sdk", app.sdk.generate)

    @mcp.tool(annotations=Write)
    async def build_research_bridge(bundle_id: str) -> Result:
        """Build and test the generated x86 standalone research bridge; no co-op DLL or gameplay hooks included."""

        def submit():
            app.config.require_development()
            return app.jobs.submit("build_research_bridge", lambda: app.sdk.build(bundle_id))

        return await app.invoke("build_research_bridge", submit)

    @mcp.tool(annotations=Write)
    async def inspect_standalone_world(seconds: Annotated[float, Field(ge=0.2, le=10)] = 2) -> Result:
        """Capture party/resources/inventory/enemies in an owned standalone session without the co-op runtime."""
        return await app.invoke("inspect_standalone_world", app.sdk.capture, app.sessions, seconds)

    @mcp.tool(annotations=Read)
    async def list_asset_archives(
        query: str = "",
        offset: Annotated[int, Field(ge=0, le=10000)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Find local game ARC paths without extracting or modifying them."""
        return await app.invoke("list_asset_archives", app.assets.catalog, query, offset, limit)

    @mcp.tool(annotations=Write)
    async def open_asset_archive(relative_path: str) -> Result:
        """Snapshot a nativePC ARC v7 into a private immutable workspace and return its index."""
        return await app.invoke("open_asset_archive", app.assets.open, relative_path)

    @mcp.tool(annotations=Write)
    async def inspect_asset(
        artifact_id: str,
        operation: Literal["entries", "extract", "text"],
        index: Annotated[int, Field(ge=0, le=8191)] = 0,
        query: str = "",
        offset: Annotated[int, Field(ge=0, le=100000)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Search archive entries, extract one to private storage, or read supported unlabelled GMD text by index."""

        def perform():
            if operation == "entries":
                return app.assets.entries(artifact_id, query, offset, limit)
            if operation == "extract":
                return app.assets.extract(artifact_id, index)
            return app.assets.text(artifact_id, offset, limit)

        return await app.invoke("inspect_asset", perform)

    @mcp.tool(annotations=Write)
    async def edit_asset_text(
        entry_id: str, edits: Annotated[list[TextEdit], Field(min_length=1, max_length=100)]
    ) -> Result:
        """Edit DDDA unlabelled GMD text with expected-original checks; preserve IDs and unknown header fields."""
        return await app.invoke(
            "edit_asset_text", app.assets.edit_text, entry_id, [e.model_dump() for e in edits]
        )

    @mcp.tool(annotations=Write)
    async def repack_asset_archive(
        archive_id: str, replacements: Annotated[list[Replacement], Field(max_length=100)]
    ) -> Result:
        """Repack selected ARC entries privately; unchanged payloads remain byte-identical and replacements are decompression-verified."""
        return await app.invoke(
            "repack_asset_archive", app.assets.repack, archive_id, [r.model_dump() for r in replacements]
        )

    @mcp.tool(annotations=Write)
    async def import_mod(source_name: str) -> Result:
        """Import files from a configured mod_sources directory using its hash-pinned mod.json manifest."""
        return await app.invoke("import_mod", app.mods.import_named, source_name)

    @mcp.tool(annotations=Write)
    async def register_mod(
        label: str,
        files: Annotated[list[ModFile], Field(min_length=1, max_length=128)],
        hooks: Annotated[list[str] | None, Field(max_length=64)] = None,
        requires: Annotated[list[str] | None, Field(max_length=32)] = None,
    ) -> Result:
        """Register private asset payloads, target paths, declared hooks and mod dependencies."""
        return await app.invoke(
            "register_mod", app.mods.register, label, [f.model_dump() for f in files], hooks, requires
        )

    @mcp.tool(annotations=Write)
    async def compose_mod_profile(
        label: str,
        mod_ids: Annotated[list[str], Field(min_length=0, max_length=16)],
        disable_loaders: Annotated[list[str] | None, Field(max_length=4)] = None,
    ) -> Result:
        """Detect file/dependency/hook conflicts; merge independent ARC entries and nonconflicting supported GMD text edits."""
        return await app.invoke("compose_mod_profile", app.mods.compose, label, mod_ids, disable_loaders)

    @mcp.tool(annotations=Replace)
    async def mod_profile(
        operation: Literal["status", "apply", "restore", "package"], profile_id: str | None = None
    ) -> Result:
        """Apply a profile with a crash-recovery journal, restore original files, or package privately. Game must be closed for replacement."""

        def perform():
            if operation == "status":
                return app.mods.status()
            if operation == "restore":
                return app.mods.restore()
            return app.mods.apply(profile_id) if operation == "apply" else app.mods.package(profile_id)

        return await app.invoke("mod_profile", perform)

    @mcp.tool(annotations=Write)
    async def register_gameplay_fixture(
        checkpoint_id: str, label: str, world_id: str | None = None
    ) -> Result:
        """Register a save checkpoint and optional matching native world traits for reusable gameplay suites."""
        return await app.invoke(
            "register_gameplay_fixture", app.suites.fixture, checkpoint_id, label, world_id
        )

    @mcp.tool(annotations=Read)
    async def list_gameplay_fixtures() -> Result:
        """List registered save fixtures with observed stages, vocations and enemy counts where available."""
        return await app.invoke("list_gameplay_fixtures", app.suites.fixtures)

    @mcp.tool(annotations=Write)
    async def create_gameplay_suite(
        label: str,
        cases: Annotated[list[SuiteCase], Field(min_length=1, max_length=12)],
        profiles: Annotated[list[str | None] | None, Field(min_length=1, max_length=16)] = None,
        repeats: Literal[1, 2, 3] = 1,
        candidate: str | None = None,
    ) -> Result:
        """Build a fixture/profile matrix with fresh save reloads and actual damage, HP or inventory assertions; maximum 24 trials."""
        return await app.invoke(
            "create_gameplay_suite",
            app.suites.create,
            label,
            [c.model_dump() for c in cases],
            profiles,
            repeats,
            candidate,
        )

    @mcp.tool(annotations=Replace)
    async def advance_gameplay_suite(
        suite_id: str, action: Literal["prepare", "evaluate", "abort"]
    ) -> Result:
        """Advance one durable trial, returning observed-menu navigation instructions; evaluation restores files and saves before the next trial."""

        def submit():
            app.config.require_development()
            return app.jobs.submit("gameplay_suite", lambda: app.suites.advance(suite_id, action))

        return await app.invoke("advance_gameplay_suite", submit)

    @mcp.tool(annotations=Read)
    async def gameplay_suite_status(suite_id: str) -> Result:
        """Read suite progress, per-profile outcomes, evidence and recovery state."""
        return await app.invoke("gameplay_suite_status", app.suites.status, suite_id)
