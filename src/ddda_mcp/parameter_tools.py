"""Typed item parameter operations. Copyright (c) 2026 Thingolus. MIT."""

from typing import Annotated, Literal

from pydantic import Field

from .gameplay_data import Contract


class ItemStatEdit(Contract):
    item_id: Annotated[int, Field(strict=True, ge=0, le=4095)]
    field: Literal[
        "mAttack",
        "mMagicAttack",
        "mElementAttack",
        "mDefense",
        "mMagicDefense",
        "mAlterItemNo",
        "mWeight",
        "mBuy",
        "mSell",
        "mAddHp",
        "mAddAp",
    ]
    expected: int | float
    value: int | float


def register_tools(mcp, app):
    from .server import Read, Result, Write

    @mcp.tool(annotations=Read)
    async def item_parameter_catalog() -> Result:
        """List the reviewed ITL2 item fields, numeric/reference bounds and unsupported formats. No game access."""
        return await app.invoke("item_parameter_catalog", app.parameters.catalog)

    @mcp.tool(annotations=Read)
    async def inspect_item_parameters(
        entry_id: str,
        item_id: Annotated[int | None, Field(ge=0, le=4095)] = None,
        offset: Annotated[int, Field(ge=0, le=4096)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Read named item stats from a privately extracted ITL2 asset; validate version, extent, IDs and references."""
        return await app.invoke(
            "inspect_item_parameters", app.parameters.inspect, entry_id, item_id, offset, limit
        )

    @mcp.tool(annotations=Write)
    async def edit_item_parameters(
        entry_id: str,
        edits: Annotated[list[ItemStatEdit], Field(min_length=1, max_length=100)],
    ) -> Result:
        """Patch named item fields privately with expected-original checks, reference validation and exact preservation of all unselected bits."""
        return await app.invoke(
            "edit_item_parameters", app.parameters.edit, entry_id, [e.model_dump() for e in edits]
        )

    @mcp.tool(annotations=Read)
    async def diff_item_parameters(
        before_id: str,
        after_id: str,
        offset: Annotated[int, Field(ge=0, le=50000)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> Result:
        """Compare named item fields and flag changes outside the reviewed schema; no gameplay-effect claim."""
        return await app.invoke(
            "diff_item_parameters", app.parameters.diff, before_id, after_id, offset, limit
        )
