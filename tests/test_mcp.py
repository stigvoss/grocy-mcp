"""Tests for the MCP server."""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from grocy_mcp.mcp.server import create_mcp_server, main


def test_create_mcp_server_returns_server_with_correct_name():
    server = create_mcp_server()
    assert server.name == "grocy-mcp"


def test_main_stdio_default(monkeypatch):
    """Default transport is stdio."""
    server = MagicMock()
    monkeypatch.setattr("grocy_mcp.mcp.server.create_mcp_server", lambda: server)
    monkeypatch.setattr("sys.argv", ["grocy-mcp"])
    main()
    server.run.assert_called_once_with(transport="stdio")


def test_main_http_with_defaults(monkeypatch):
    """HTTP transport passes host, port, path, stateless_http."""
    server = MagicMock()
    monkeypatch.setattr("grocy_mcp.mcp.server.create_mcp_server", lambda: server)
    monkeypatch.setattr("sys.argv", ["grocy-mcp", "--transport", "streamable-http"])
    main()
    server.run.assert_called_once_with(
        transport="streamable-http",
        host="0.0.0.0",
        port=8000,
        path="/mcp",
        stateless_http=True,
    )


def test_main_http_custom_args(monkeypatch):
    """HTTP transport respects --host, --port, --path."""
    server = MagicMock()
    monkeypatch.setattr("grocy_mcp.mcp.server.create_mcp_server", lambda: server)
    monkeypatch.setattr(
        "sys.argv",
        [
            "grocy-mcp",
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            "9193",
            "--path",
            "/private_abc",
        ],
    )
    main()
    server.run.assert_called_once_with(
        transport="streamable-http",
        host="127.0.0.1",
        port=9193,
        path="/private_abc",
        stateless_http=True,
    )


async def test_entity_create_tool_invalid_json_returns_clear_error():
    mcp = create_mcp_server()

    with pytest.raises(Exception, match="Invalid JSON for data"):
        await mcp.call_tool("entity_create_tool", {"entity": "products", "data": "{bad"})


async def test_userfields_set_tool_invalid_json_returns_clear_error():
    mcp = create_mcp_server()

    with pytest.raises(Exception, match="Invalid JSON for data"):
        await mcp.call_tool(
            "userfields_set_tool", {"entity": "products", "obj_id": 87, "data": "{bad"}
        )


async def test_userfields_set_tool_empty_object_returns_clear_error():
    mcp = create_mcp_server()

    with pytest.raises(Exception, match="non-empty object"):
        await mcp.call_tool(
            "userfields_set_tool", {"entity": "products", "obj_id": 87, "data": "{}"}
        )


async def test_userfields_set_tool_calls_client(monkeypatch):
    mcp = create_mcp_server()

    calls = []

    @asynccontextmanager
    async def fake_client():
        class Client:
            async def update_userfields(self, entity, obj_id, data):
                calls.append((entity, obj_id, data))

        yield Client()

    monkeypatch.setattr("grocy_mcp.mcp.server._get_client", fake_client)

    result = await mcp.call_tool(
        "userfields_set_tool",
        {"entity": "products", "obj_id": 87, "data": '{"ai_notes": "Prefer paprika flavour"}'},
    )

    assert calls == [("products", 87, {"ai_notes": "Prefer paprika flavour"})]
    assert "87" in result.content[0].text


async def test_workflow_match_products_preview_tool_invalid_json_returns_clear_error():
    mcp = create_mcp_server()

    with pytest.raises(Exception, match="Invalid JSON for items"):
        await mcp.call_tool("workflow_match_products_preview_tool", {"items": "{bad"})


async def test_workflow_match_products_preview_tool_returns_structured_data(monkeypatch):
    mcp = create_mcp_server()

    @asynccontextmanager
    async def fake_client():
        class Client:
            async def get_objects(self, entity: str):
                if entity == "products":
                    return [{"id": 12, "name": "Whole Milk"}]
                if entity == "product_barcodes":
                    return [{"id": 2, "product_id": 12, "barcode": "5000112637922"}]
                return []

        yield Client()

    monkeypatch.setattr("grocy_mcp.mcp.server._get_client", fake_client)

    result = await mcp.call_tool(
        "workflow_match_products_preview_tool",
        {"items": '[{"label": "whole milk", "quantity": 2, "barcode": "5000112637922"}]'},
    )

    preview = result.structured_content["result"]
    assert preview[0]["status"] == "matched"
    assert preview[0]["matched_product_id"] == 12


async def test_catalog_list_tool_returns_structured_data(monkeypatch):
    mcp = create_mcp_server()

    @asynccontextmanager
    async def fake_client():
        class Client:
            async def get_objects(self, entity: str):
                assert entity == "shopping_lists"
                return [{"id": 1, "name": "Weekly"}]

        yield Client()

    monkeypatch.setattr("grocy_mcp.mcp.server._get_client", fake_client)

    result = await mcp.call_tool("catalog_list_tool", {"entity": "shopping_lists"})

    rows = result.structured_content["result"]
    assert rows == [{"id": 1, "name": "Weekly"}]


async def test_calendar_summary_tool_returns_structured_data(monkeypatch):
    mcp = create_mcp_server()

    @asynccontextmanager
    async def fake_client():
        class Client:
            async def get_tasks(self):
                return [{"id": 1, "name": "Buy milk", "due_date": "2026-04-05"}]

            async def get_chores(self):
                return []

            async def get_batteries(self):
                return []

            async def get_objects(self, entity: str):
                if entity == "meal_plan":
                    return []
                if entity == "recipes":
                    return []
                return []

        yield Client()

    monkeypatch.setattr("grocy_mcp.mcp.server._get_client", fake_client)

    result = await mcp.call_tool("calendar_summary_tool", {})

    summary = result.structured_content.get("result", result.structured_content)
    assert summary["tasks"][0]["id"] == 1


async def test_file_download_tool_returns_base64(monkeypatch):
    mcp = create_mcp_server()

    @asynccontextmanager
    async def fake_client():
        class Client:
            async def download_file(
                self,
                group: str,
                file_name_b64: str,
                force_serve_as=None,
                best_fit_width=None,
                best_fit_height=None,
            ):
                return b"hello", "text/plain"

        yield Client()

    monkeypatch.setattr("grocy_mcp.mcp.server._get_client", fake_client)

    result = await mcp.call_tool(
        "file_download_tool",
        {"group": "productpictures", "file_name": "milk.jpg"},
    )

    payload = result.structured_content.get("result", result.structured_content)
    assert payload["group"] == "productpictures"
    assert payload["content_type"] == "text/plain"


async def test_new_tools_are_registered():
    tools = {t.name for t in await create_mcp_server().list_tools()}
    assert {"products_list_tool", "stock_levels_tool"} <= tools


def _product_client(calls):
    class Client:
        instance = "http://grocy-test/api"

        async def get_objects(self, entity, query=None):
            return {
                "quantity_units": [{"id": 3, "name": "Pack"}],
                "locations": [{"id": 2, "name": "Fridge"}],
                "product_groups": [],
                "products": [],
            }[entity]

        async def create_object(self, entity, data):
            calls.append(("create", data["name"]))
            return "77"

        async def update_userfields(self, entity, obj_id, data):
            calls.append(("userfields", obj_id, data))

    return Client()


async def test_product_create_tool_accepts_null_userfield_values_and_skips_them(monkeypatch):
    mcp = create_mcp_server()
    calls = []

    @asynccontextmanager
    async def fake_client():
        yield _product_client(calls)

    monkeypatch.setattr("grocy_mcp.mcp.server._get_client", fake_client)

    result = await mcp.call_tool(
        "product_create_tool",
        {
            "name": "Skyr natural",
            "stock_unit": "Pack",
            "location": "Fridge",
            "userfields": {"ai_notes": None, "bilkatogo_ids": "19753", "bilkatogo": None},
        },
    )

    payload = result.structured_content
    assert payload["created"] is True and payload["userfields_set"] == ["bilkatogo_ids"]
    assert ("userfields", 77, {"bilkatogo_ids": "19753"}) in calls


async def test_product_create_tool_with_only_null_userfields_makes_no_userfield_request(
    monkeypatch,
):
    mcp = create_mcp_server()
    calls = []

    @asynccontextmanager
    async def fake_client():
        yield _product_client(calls)

    monkeypatch.setattr("grocy_mcp.mcp.server._get_client", fake_client)

    result = await mcp.call_tool(
        "product_create_tool",
        {
            "name": "Plain thing",
            "stock_unit": "Pack",
            "location": "Fridge",
            "userfields": {"ai_notes": None},
        },
    )

    payload = result.structured_content
    assert payload["created"] is True and "userfields_set" not in payload
    assert not [c for c in calls if c[0] == "userfields"]


async def test_entry_tool_descriptions_warn_that_entry_ids_change():
    tools = {t.name: (t.description or "") for t in await create_mcp_server().list_tools()}
    assert "not stable" in tools["stock_entries_tool"]
    assert "list the entries again" in tools["stock_entries_tool"]
    assert "not stable" in tools["stock_entry_edit_tool"]
    assert "fresh stock_entries_tool call" in tools["stock_entry_edit_tool"]
    assert "new stock entry with a new entry ID" in tools["stock_undo_tool"]


def test_readme_documents_correcting_stock_and_unstable_entry_ids():
    from pathlib import Path

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    section = readme.split('### "Correct a wrong entry or booking"')[1].split("\n### ")[0]
    for tool in (
        "stock_entries_tool",
        "stock_entry_edit_tool",
        "stock_journal_tool",
        "stock_undo_tool",
    ):
        assert tool in section
    assert "not stable" in section and "new* entry" in section
    # it must not promise protection against changes made before the edit call started
    flat = " ".join(section.split())
    assert "while the edit is in progress" in flat and "cannot know what you saw" in flat
