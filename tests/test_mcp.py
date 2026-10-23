import asyncio
import json
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from ddda_mcp.common import atomic_json
from ddda_mcp.server import Envelope, create_server


def test_real_sdk_tools_resources_and_errors(config):
    async def run():
        server, _ = create_server(config)
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert len(names) == 50
            assert {"inspect_build", "search_knowledge", "start_session", "rollback_deployment"} <= names
            assert all(tool.output_schema for tool in tools.tools)
            catalog = await client.call_tool("list_scenarios", {})
            assert len(catalog.structured_content["data"]["recipes"]) == 6
            recovery = await client.call_tool("save_restore_status", {})
            assert not recovery.structured_content["data"]["game_blocked"]
            refused_recovery = await client.call_tool("recover_save_restore", {"receipt_id": "a" * 32})
            assert refused_recovery.structured_content["error"]["code"] == "profile_disabled"
            status = await client.call_tool("project_status", {})
            assert not status.is_error
            doc = status.structured_content
            Envelope.model_validate(doc)
            assert doc["data"]["creator"] == "Thingolus"
            refused = await client.call_tool("start_session", {})
            assert refused.is_error
            assert refused.structured_content["error"]["code"] == "profile_disabled"
            search = await client.call_tool("search_knowledge", {"query": "ownership"})
            assert search.structured_content["data"]["results"]
            invalid = await client.call_tool("search_knowledge", {"query": "ownership", "limit": 500})
            assert invalid.is_error
            resources = await client.list_resources()
            assert any(str(resource.uri) == "ddda://project/status" for resource in resources.resources)
            status_resource = await client.read_resource("ddda://project/status")
            assert "Thingolus" in status_resource.contents[0].text

    asyncio.run(run())


def test_actual_stdio_handshake_and_structured_call(config):
    atomic_json(config.root / "config/local.json", config.settings.model_dump())

    async def run():
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "ddda_mcp", "--project", str(config.root)]
        )
        async with Client(parameters, read_timeout_seconds=20) as client:
            result = await client.call_tool("lookup_symbol", {"name_or_rva": "pawn_movement_consume"})
            assert not result.is_error
            assert result.structured_content["data"]["symbols"][0]["name"] == "pawn_movement_consume"

    asyncio.run(run())


def test_inline_size_limit_preserves_full_result(config):
    config.settings.limits.max_inline_result_bytes = 2048

    async def run():
        _, app = create_server(config)
        result = await app.invoke("large_fixture", lambda: {"large": "a" * 6000})
        doc = result.structured_content
        assert doc["data"]["inline_truncated"]
        assert len(json.dumps(doc).encode()) < 2048
        artifact = app.artifacts.get(doc["data"]["artifact_id"])
        assert artifact["data"]["result"]["data"]["large"] == "a" * 6000

    asyncio.run(run())


def test_oversize_artifact_returns_structured_error(config):
    config.settings.limits.max_inline_result_bytes = 2048
    config.settings.limits.max_trace_bytes = 8192

    async def run():
        _, app = create_server(config)
        result = await app.invoke("oversized_fixture", lambda: {"large": "x" * 12000})
        assert result.is_error
        assert result.structured_content["error"]["code"] == "result_too_large"

    asyncio.run(run())


def test_artifact_pagination_preserves_long_strings(config):
    _, app = create_server(config)
    payload = "a" * 12000 + "UNIQUE_TAIL"
    saved = app.artifacts.put("fixture", {"long_string": payload}, {})
    next_line, pages = 1, []
    while next_line is not None:
        page = app.artifacts.read_page(saved["artifact_id"], next_line, 3)
        assert page["lines"]
        pages.extend(page["lines"])
        next_line = page["next_line"]
    assert payload in "".join(pages)


def test_artifact_budget_includes_persisted_format(config):
    from ddda_mcp.common import ToolFailure

    config.settings.limits.max_trace_bytes = 8192
    _, app = create_server(config)
    try:
        saved = app.artifacts.put("fixture", {"rows": [{"k": i} for i in range(500)]}, {})
    except ToolFailure as exc:
        assert exc.code == "result_too_large"
    else:
        assert app.artifacts.get(saved["artifact_id"])["data"]["rows"]


def test_expansion_stdio_memory_restart_checkpoint_and_guards(development):
    from test_expansion import fixture_checkpoint

    harness, _, trace, backup = fixture_checkpoint(development)
    atomic_json(development.root / "config/local.json", development.settings.model_dump())
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "ddda_mcp", "--project", str(development.root)]
    )

    async def run():
        async with Client(parameters, read_timeout_seconds=20) as client:

            async def call(name, args):
                response = await client.call_tool(name, args)
                assert not response.is_error, response.structured_content
                return response.structured_content["data"]

            checkpoint = await call(
                "create_gameplay_checkpoint",
                {"backup_id": backup, "trace_id": trace["artifact_id"], "label": "synthetic stdio fixture"},
            )
            note = await call(
                "record_investigation_note",
                {
                    "title": "Checkpoint fixture",
                    "body": "Synthetic transport check only",
                    "kind": "finding",
                    "evidence_ids": [checkpoint["artifact_id"]],
                },
            )
            read = await call("read_investigation_note", {"note_id": note["note_id"]})
            assert read["evidence_integrity"][0]["unchanged"]
            invalid = await client.call_tool(
                "create_regression_campaign",
                {"checkpoint_id": checkpoint["artifact_id"], "revisions": ["a" * 40, "a" * 40]},
            )
            assert invalid.structured_content["error"]["code"] == "invalid_parameters"
        async with Client(parameters, read_timeout_seconds=20) as client:
            result = await client.call_tool("search_investigations", {"query": "checkpoint fixture"})
            assert result.structured_content["data"]["notes"][0]["id"] == note["note_id"]
            stale = await client.call_tool(
                "record_investigation_note",
                {"title": "stale", "body": "conflict", "note_id": note["note_id"], "expected_revision": 0},
            )
            assert stale.structured_content["error"]["code"] == "revision_conflict"

    asyncio.run(run())
