"""Typed asset authoring tools. Copyright (c) 2026 Thingolus. MIT."""

from typing import Annotated

from pydantic import Field, StrictBool, StrictFloat, StrictInt

from .gameplay_data import Contract


class ParameterEdit(Contract):
    path: Annotated[str, Field(min_length=1, max_length=8192)]
    expected: StrictBool | StrictInt | StrictFloat
    value: StrictBool | StrictInt | StrictFloat


def register_tools(mcp, app):
    from .server import Read, Result, Write

    @mcp.tool(annotations=Read)
    async def inspect_game_parameters(
        entry_id: str,
        query: Annotated[str, Field(max_length=120)] = "",
        offset: Annotated[int, Field(ge=0, le=200000)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Read named XFS/PRPZ, SKL, LOT encounter and IST loot fields with explicit writable/structural boundaries."""
        return await app.invoke(
            "inspect_game_parameters", app.game_parameters.inspect, entry_id, query, offset, limit
        )

    @mcp.tool(annotations=Write)
    async def edit_game_parameters(
        entry_id: str, edits: Annotated[list[ParameterEdit], Field(min_length=1, max_length=100)]
    ) -> Result:
        """Patch named serialized fields privately; verify expected values, structure and unchanged bytes."""
        return await app.invoke(
            "edit_game_parameters", app.game_parameters.edit, entry_id, [e.model_dump() for e in edits]
        )

    @mcp.tool(annotations=Read)
    async def diff_game_parameters(
        before_id: str,
        after_id: str,
        offset: Annotated[int, Field(ge=0, le=200000)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Show named parameter changes and count changed bytes outside reviewed fields."""
        return await app.invoke(
            "diff_game_parameters", app.game_parameters.diff, before_id, after_id, offset, limit
        )

    @mcp.tool(annotations=Write)
    async def build_asset_index(query: Annotated[str, Field(max_length=120)] = "") -> Result:
        """Index up to 10,000 ARC headers into a private searchable catalog; returns a cancellable job."""

        def submit():
            app.config.require_development()
            return app.jobs.submit("build_asset_index", lambda: app.asset_atlas.build(query))

        return await app.invoke("build_asset_index", submit)

    @mcp.tool(annotations=Read)
    async def search_assets(
        index_id: str,
        query: Annotated[str, Field(max_length=120)] = "",
        duplicates_only: bool = False,
        type_hash: Annotated[int | None, Field(ge=0, le=4294967295)] = None,
        offset: Annotated[int, Field(ge=0, le=2000000)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Search across indexed archives and find repeated logical names; duplicates do not imply equal bytes."""
        return await app.invoke(
            "search_assets",
            app.asset_atlas.search,
            index_id,
            query,
            duplicates_only,
            type_hash,
            offset,
            limit,
        )

    @mcp.tool(annotations=Write)
    async def extract_indexed_asset(
        index_id: str, asset_id: Annotated[int, Field(ge=1, le=2000000)]
    ) -> Result:
        """Validate the indexed archive header and extract a selected occurrence into private immutable storage."""
        return await app.invoke("extract_indexed_asset", app.asset_atlas.extract, index_id, asset_id)

    @mcp.tool(annotations=Read)
    async def inspect_asset_references(
        index_id: str,
        entry_id: str,
        offset: Annotated[int, Field(ge=0, le=200000)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Resolve serialized parameter strings against indexed asset paths; report candidate references and missing matches."""
        return await app.invoke(
            "inspect_asset_references", app.asset_atlas.references, index_id, entry_id, offset, limit
        )

    @mcp.tool(annotations=Write)
    async def export_texture(entry_id: str, mip: Annotated[int, Field(ge=0, le=13)] = 0) -> Result:
        """Export supported TEX textures to DDS and a PNG preview; preserve all mip payloads."""
        return await app.invoke("export_texture", app.textures.export, entry_id, mip)

    @mcp.tool(annotations=Write)
    async def import_texture_dds(
        entry_id: str,
        source_name: str,
        relative_path: str,
        expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    ) -> Result:
        """Import a hash-checked DDS from configured mod_sources; retain TEX metadata and enforce matching dimensions/mips/format."""
        return await app.invoke(
            "import_texture_dds", app.textures.replace, entry_id, source_name, relative_path, expected_sha256
        )
